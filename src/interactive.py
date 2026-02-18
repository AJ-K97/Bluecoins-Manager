import os
import re
import textwrap

from datetime import datetime
from sqlalchemy import select, func
from InquirerPy import inquirer
from InquirerPy.separator import Separator
from InquirerPy.base.control import Choice
from src.database import init_db, AsyncSessionLocal, Account, Transaction, AIMemory
from src.commands import (
    list_accounts, add_account, delete_account, update_account, process_import, get_all_accounts,
    get_transactions, update_transaction_category, delete_transaction, export_to_bluecoins_csv,
    get_all_categories, mark_transaction_verified, update_transaction_amount,
    add_category, delete_category, get_category_display_from_values, add_global_memory_instruction,
    get_global_memory_entries, set_global_memory_active, delete_global_memory_instruction,
    reset_database, seed_reference_data, format_category_obj_label, format_category_label,
    get_transaction_category_display,
    get_resettable_table_names, get_table_row_counts, reset_selected_tables,
    get_queue_transactions, get_queue_stats,
)
from src.ai import CategorizerAI
from src.bank_config import list_bank_names, load_banks_payload, upsert_bank_format
from src.parser import BankParser, format_pdf_debug_report, format_pdf_blocks_report
from src.patterns import extract_pattern_key_result

from src.tui import TransactionReviewApp


def _group_categories_by_type_and_parent(categories):
    grouped = {}
    for c in categories:
        ctype = (c.type or "unknown").lower()
        parent = c.parent_name or "Uncategorized"
        grouped.setdefault(ctype, {}).setdefault(parent, []).append(c)
    for ctype in grouped:
        for parent in grouped[ctype]:
            grouped[ctype][parent] = sorted(grouped[ctype][parent], key=lambda x: x.name.lower())
    return grouped


TRANSFER_CHOICE = "__transfer_no_category__"


async def choose_category_tree(session, prompt_prefix="Select Category", default_type=None, restrict_to_default_type=False):
    cats = await get_all_categories(session)
    if not cats:
        return None

    grouped = _group_categories_by_type_and_parent(cats)
    available_types = sorted(grouped.keys())
    if restrict_to_default_type and default_type and default_type in available_types:
        available_types = [default_type]
    elif default_type and default_type in available_types:
        available_types = [default_type] + [t for t in available_types if t != default_type]

    selected_type = await inquirer.select(
        message=f"{prompt_prefix}: Select Type",
        choices=[
            Choice(value=t, name=t.upper()) for t in available_types
        ] + [
            Choice(value=TRANSFER_CHOICE, name="TRANSFER (no category)"),
            Choice(value=None, name="Cancel"),
        ],
    ).execute_async()
    if not selected_type:
        return None
    if selected_type == TRANSFER_CHOICE:
        return TRANSFER_CHOICE

    tree_choices = []
    parent_names = sorted(grouped[selected_type].keys())
    for parent in parent_names:
        # Parent rows are non-selectable separators; only sub-categories can be selected.
        tree_choices.append(Separator(f"📁 {parent}"))
        children = grouped[selected_type][parent]
        for idx, child in enumerate(children):
            branch = "└─" if idx == len(children) - 1 else "├─"
            tree_choices.append(Choice(value=child, name=f"  {branch} {child.name}"))

    tree_choices.append(Choice(value=None, name="Back"))

    return await inquirer.select(
        message=f"{prompt_prefix}: Select Sub-Category ({selected_type.upper()})",
        choices=tree_choices,
    ).execute_async()


async def _get_or_create_latest_memory_entry(session, tx):
    mem_stmt = (
        select(AIMemory)
        .where(AIMemory.transaction_id == tx.id)
        .order_by(AIMemory.created_at.desc())
        .limit(1)
    )
    mem_res = await session.execute(mem_stmt)
    memory = mem_res.scalars().first()
    if memory:
        return memory

    memory = AIMemory(
        transaction_id=tx.id,
        pattern_key=extract_pattern_key_result(tx.description).keyword,
        ai_suggested_category_id=tx.category_id,
        user_selected_category_id=tx.category_id,
        ai_reasoning=tx.decision_reason or "",
    )
    session.add(memory)
    await session.flush()
    return memory


def _tx_data_from_row(tx):
    return {
        "id": tx.id,
        "date": tx.date.strftime("%Y-%m-%d") if tx.date else "",
        "amount": tx.amount,
        "description": tx.description or "",
        "type": tx.type,
        "raw_csv_row": tx.raw_csv_row or "",
    }


async def _category_label_for_tx(session, tx_type, category_id):
    parent_name, cat_name = await get_category_display_from_values(session, tx_type, category_id)
    return format_category_label(parent_name, cat_name, tx_type)


async def review_transactions(session, transactions):
    """
    Interactive review of new transactions using custom TUI.
    """
    # Filter/Fetch fresh list
    tx_ids = [t.id for t in transactions]
    if not tx_ids:
        return

    from sqlalchemy import select
    from src.database import Transaction
    from sqlalchemy.orm import selectinload
    
    # Initial fetch
    stmt = select(Transaction).options(
        selectinload(Transaction.category),
        selectinload(Transaction.account),
        selectinload(Transaction.memory_entries)
    ).where(Transaction.id.in_(tx_ids)).order_by(Transaction.date.desc())
    
    res = await session.execute(stmt)
    review_list = res.scalars().all()
    
    if not review_list:
        print("No transactions to review.")
        return

    ai = CategorizerAI()

    # Callback for TUI actions
    async def on_update(tx, action):
        if action == 'verify':
            await mark_transaction_verified(session, tx.id)
            # Refresh object state if needed, but simple attribute update might be enough for display
            # tx.is_verified = True # Handled in TUI/Object
            
    # Main Loop
    while True:
        # Check if all done?
        # Maybe not check, user can exit when they want.
        
        app = TransactionReviewApp(review_list, session, update_callback=on_update)
        result = await app.run_async()
        
        if result is None:
            break
            
        action, tx = result
        
        if action == 'modify':
            selected_cat = await choose_category_tree(
                session,
                prompt_prefix=f"'{tx.description}'",
                default_type=tx.type if tx.type in {"income", "expense"} else None,
                restrict_to_default_type=True,
            )
            if selected_cat == TRANSFER_CHOICE:
                await update_transaction_category(session, tx.id, category_id=None, set_transfer=True)
                await session.refresh(tx, ['category', 'memory_entries'])
            elif selected_cat:
                await update_transaction_category(session, tx.id, selected_cat.id)
                await session.refresh(tx, ['category', 'memory_entries'])
            else:
                continue

            follow_up = await inquirer.select(
                message="Post-change learning:",
                choices=[
                    Choice(value="coach", name="Coach model with explicit rule"),
                    Choice(value="discuss", name="Discuss and synthesize guidance"),
                    Choice(value="none", name="Done"),
                ],
                default="coach",
            ).execute_async()
            action = follow_up

        if action == 'coach':
            coaching_text = await inquirer.text(
                message="Coaching instruction to save in global rulebook:"
            ).execute_async()
            coaching_text = (coaching_text or "").strip()
            if not coaching_text:
                continue

            await add_global_memory_instruction(session, coaching_text, source="review_coaching")
            await session.commit()
            print("Saved coaching rule.")

            rerun = await inquirer.confirm(
                message="Re-run AI suggestion for this transaction using this coaching?",
                default=True,
            ).execute_async()
            if rerun:
                locked_expected_type = tx.type if tx.type in {"expense", "income"} else None
                candidates = await ai.suggest_category_candidates(
                    tx.description,
                    session,
                    min_candidates=3,
                    extra_instruction=coaching_text,
                    expected_type=locked_expected_type,
                )
                if candidates:
                    top = candidates[0]
                    suggested_label = await _category_label_for_tx(session, top["type"], top["id"])
                    apply_top = await inquirer.confirm(
                        message=f"Apply top coached suggestion now? {suggested_label}",
                        default=False,
                    ).execute_async()
                    if apply_top:
                        await update_transaction_category(session, tx.id, top["id"])
                        await session.refresh(tx, ['category', 'memory_entries'])
                        print("Applied coached suggestion.")
            continue

        if action == 'discuss':
            print("\nDiscussion mode. Use /done to finish and /search <query> to force web lookup.")
            discussion_history = []
            tx_data = _tx_data_from_row(tx)

            while True:
                user_msg = await inquirer.text(message="You:").execute_async()
                user_msg = (user_msg or "").strip()
                if not user_msg:
                    continue
                if user_msg.lower() in {"/done", "done", "exit"}:
                    break

                forced_search_query = None
                llm_message = user_msg
                if user_msg.lower().startswith("/search"):
                    forced_search_query = user_msg[7:].strip()
                    if not forced_search_query:
                        print("Usage: /search <query>")
                        continue
                    llm_message = (
                        "Use this explicit web search context to evaluate the current decision. "
                        f"Query: {forced_search_query}. Explain whether category/type should change and why."
                    )

                memory = await _get_or_create_latest_memory_entry(session, tx)
                reply = await ai.discuss_transaction(
                    tx_data=tx_data,
                    current_type=tx.type,
                    current_cat_id=tx.category_id,
                    current_reasoning=memory.ai_reasoning or tx.decision_reason or "No reasoning.",
                    session=session,
                    user_message=llm_message,
                    conversation_history=discussion_history,
                    web_search_query=forced_search_query,
                )
                discussion_history.append({"role": "user", "content": user_msg})
                discussion_history.append({"role": "assistant", "content": reply})
                print(f"\nModel: {reply}\n")

            if discussion_history:
                guidance = await ai.summarize_review_conversation(
                    tx_description=tx.description,
                    conversation_history=discussion_history,
                )
                if guidance and guidance.strip():
                    guidance_text = guidance.strip()
                    print("\nSynthesized guidance:\n" + guidance + "\n")
                    persist = await inquirer.confirm(
                        message="Save this guidance in global rulebook?",
                        default=True,
                    ).execute_async()
                    if persist:
                        await add_global_memory_instruction(
                            session,
                            guidance_text,
                            source="review_discussion",
                        )
                        await session.commit()
                        print("Saved guidance rule.")

                    rerun = await inquirer.confirm(
                        message="Re-run AI suggestion for this transaction using this guidance?",
                        default=True,
                    ).execute_async()
                    if rerun:
                        locked_expected_type = tx.type if tx.type in {"expense", "income"} else None
                        candidates = await ai.suggest_category_candidates(
                            tx.description,
                            session,
                            min_candidates=3,
                            extra_instruction=guidance_text,
                            expected_type=locked_expected_type,
                        )
                        if candidates:
                            top = candidates[0]
                            suggested_label = await _category_label_for_tx(session, top["type"], top["id"])
                            apply_top = await inquirer.confirm(
                                message=f"Apply top discussion suggestion now? {suggested_label}",
                                default=False,
                            ).execute_async()
                            if apply_top:
                                await update_transaction_category(session, tx.id, top["id"])
                                await session.refresh(tx, ['category', 'memory_entries'])
                                print("Applied discussion suggestion.")
            continue

        if action == 'reflect':
            current_label = await _category_label_for_tx(session, tx.type, tx.category_id)
            memory = await _get_or_create_latest_memory_entry(session, tx)
            prior_reasoning = memory.ai_reasoning or tx.decision_reason or "No prior reasoning."
            reflection = await ai.generate_correctness_reflection(
                tx.description,
                current_label,
                prior_reasoning,
            )
            memory.user_selected_category_id = tx.category_id
            memory.reflection = reflection
            session.add(memory)
            await session.commit()
            print(f"Saved reflection: {reflection}")

            if not tx.is_verified:
                verify_now = await inquirer.confirm(
                    message="Mark this transaction as verified now?",
                    default=True,
                ).execute_async()
                if verify_now:
                    await mark_transaction_verified(session, tx.id)
                    await session.refresh(tx, ['memory_entries'])
            continue

        if action == 'delete':
            confirm = await inquirer.confirm(message=f"Delete '{tx.description}'?").execute_async()
            if confirm:
                await delete_transaction(session, tx.id)
                review_list.remove(tx)
                if not review_list:
                    print("All transactions deleted.")
                    break



async def manage_accounts_menu(session):
    while True:
        action = await inquirer.select(
            message="Manage Accounts:",
            choices=[
                "List Accounts",
                "Add Account",
                "Edit Account",
                "Delete Account",
                Choice(value=None, name="Back to Main Menu")
            ],
        ).execute_async()
        
        if not action:
            break
            
        if action == "List Accounts":
            accounts = await list_accounts(session)
            if not accounts:
                print("No accounts found.")
            else:
                print("\nAccounts:")
                for acc in accounts:
                    print(f" - {acc.name} ({acc.institution})")
                print("") 
                
        elif action == "Add Account":
            name = await inquirer.text(message="Account Name:").execute_async()
            inst = await inquirer.text(message="Institution (e.g. HSBC):").execute_async()
            success, msg = await add_account(session, name, inst)
            print(f"\n{msg}\n")
            
        elif action == "Delete Account":
            accounts = await list_accounts(session)
            if not accounts:
                print("No accounts to delete.")
                continue
                
            choices = [Choice(value=acc.name, name=acc.name) for acc in accounts]
            choices.append(Choice(value=None, name="Cancel"))
            
            target = await inquirer.select(
                message="Select Account to Delete:",
                choices=choices
            ).execute_async()
            
            if target:
                confirm = await inquirer.confirm(message=f"Are you sure you want to delete '{target}'?").execute_async()
                if confirm:
                    success, msg = await delete_account(session, target)
                    print(f"\n{msg}\n")

        elif action == "Edit Account":
            accounts = await list_accounts(session)
            if not accounts:
                print("No accounts to edit.")
                continue

            choices = [Choice(value=acc.name, name=f"{acc.name} ({acc.institution})") for acc in accounts]
            choices.append(Choice(value=None, name="Cancel"))
            current_name = await inquirer.select(
                message="Select Account to Edit:",
                choices=choices
            ).execute_async()
            if not current_name:
                continue

            acc_res = await session.execute(select(Account).where(Account.name == current_name))
            account = acc_res.scalar_one_or_none()
            if not account:
                print("Account not found.")
                continue

            new_name = await inquirer.text(
                message="New account name:",
                default=account.name,
            ).execute_async()
            if not (new_name or "").strip():
                print("Account name cannot be empty.")
                continue

            linked_tx_count = await session.scalar(
                select(func.count(Transaction.id)).where(Transaction.account_id == account.id)
            )
            linked_tx_count = int(linked_tx_count or 0)

            confirm = await inquirer.confirm(
                message=(
                    f"Rename '{account.name}' to '{new_name.strip()}' and update "
                    f"{linked_tx_count} linked transaction(s)?"
                )
            ).execute_async()
            if not confirm:
                print("Edit canceled.")
                continue

            success, msg, updated_count = await update_account(
                session,
                current_name=account.name,
                new_name=new_name.strip(),
                new_institution=account.institution,
            )
            if success:
                print(f"\n{msg} Updated {updated_count} linked transaction(s).\n")
            else:
                print(f"\n{msg}\n")

async def manage_transactions_menu(session):
    while True:
        action = await inquirer.select(
            message="Manage Transactions:",
            choices=[
                "View / Edit Recent Transactions",
                "Review Queue",
                "Export to CSV",
                Choice(value=None, name="Back to Main Menu")
            ]
        ).execute_async()
        
        if not action: break
        
        # 1. Filter Account
        accounts = await get_all_accounts(session)
        acc_choices = [Choice(value=acc.id, name=acc.name) for acc in accounts]
        acc_choices.insert(0, Choice(value=None, name="All Accounts"))
        
        account_id = await inquirer.select(
            message="Filter by Account:",
            choices=acc_choices
        ).execute_async()
        
        if action == "Export to CSV":
            start_str = await inquirer.text(message="Start Date (YYYY-MM-DD) or Enter for All:").execute_async()
            start_date = datetime.strptime(start_str, "%Y-%m-%d") if start_str else None
            
            output_path = await inquirer.filepath(
                message="Output Path:",
                default="export.csv",
                validate=lambda x: not os.path.isdir(x)
            ).execute_async()
            
            txs = await get_transactions(session, account_id=account_id, start_date=start_date)
            if not txs:
                print("No transactions found.")
                continue
            
            success, msg = export_to_bluecoins_csv(txs, output_path)
            print(f"\n{msg}\n")
        elif action == "Review Queue":
            await review_queue_menu(session, account_id=account_id)
            
        elif action == "View / Edit Recent Transactions":
            # Fetch last 50
            txs = await get_transactions(session, account_id=account_id)
            if not txs:
                print("No transactions found.")
                continue
                
            # Selection Menu
            choices = []
            for t in txs[:50]: 
                status = "✅" if t.is_verified else "  "
                parent_name, cat_name = get_transaction_category_display(t)
                cat_type = t.category.type if t.category else t.type
                cat_name = format_category_label(parent_name, cat_name, cat_type)
                label = f"{status} {t.date.strftime('%Y-%m-%d')} | {t.description[:20]:<20} | {t.amount:>8.2f} | {cat_name}"
                choices.append(Choice(value=t, name=label))
            choices.append(Choice(value=None, name="Back"))
            
            selected_tx = await inquirer.select(
                message="Select Transaction to Edit:",
                choices=choices
            ).execute_async()
            
            if not selected_tx: continue
            
            # Action on Transaction
            tx_action = await inquirer.select(
                message=f"Action for '{selected_tx.description}':",
                choices=[
                    "Change Category",
                    "Verify / Approve", 
                    "Delete Transaction",
                    Choice(value=None, name="Cancel")
                ]
            ).execute_async()
            
            if tx_action == "Change Category":
                selected_cat = await choose_category_tree(
                    session,
                    prompt_prefix="Select New Category",
                    default_type=selected_tx.type if selected_tx.type in {"income", "expense"} else None,
                    restrict_to_default_type=True,
                )
                if selected_cat == TRANSFER_CHOICE:
                    await update_transaction_category(session, selected_tx.id, category_id=None, set_transfer=True)
                    print("Updated!")
                elif selected_cat:
                    await update_transaction_category(session, selected_tx.id, selected_cat.id)
                    print("Updated!")
            
            elif tx_action == "Verify / Approve":
                await mark_transaction_verified(session, selected_tx.id)
                print("Verified!")

            elif tx_action == "Delete Transaction":
                confirm = await inquirer.confirm(message="Are you sure?").execute_async()
                if confirm:
                    await delete_transaction(session, selected_tx.id)
                    print("Deleted.")


async def review_queue_menu(session, account_id=None):
    while True:
        rows = await get_queue_transactions(session, account_id=account_id, limit=200)
        if not rows:
            print("No transactions pending review in queue.")
            return

        choices = []
        for tx in rows:
            parent_name, cat_name = get_transaction_category_display(tx)
            cat_type = tx.category.type if tx.category else tx.type
            cat_name = format_category_label(parent_name, cat_name, cat_type)
            label = (
                f"[{tx.decision_state}/{tx.review_bucket}] p{tx.review_priority or 0} "
                f"{tx.date.strftime('%Y-%m-%d')} | {tx.description[:24]:<24} | {tx.amount:>8.2f} | {cat_name}"
            )
            choices.append(Choice(value=tx, name=label))
        choices.append(Choice(value=None, name="Back"))

        selected_tx = await inquirer.select(
            message="Review Queue: Select Transaction",
            choices=choices,
        ).execute_async()
        if not selected_tx:
            return

        tx_action = await inquirer.select(
            message=f"Queue action for '{selected_tx.description}':",
            choices=[
                "Accept & Verify",
                "Change Category",
                "Delete Transaction",
                Choice(value=None, name="Cancel"),
            ],
        ).execute_async()

        if tx_action == "Accept & Verify":
            await mark_transaction_verified(session, selected_tx.id)
            print("Verified!")
            continue

        if tx_action == "Change Category":
            selected_cat = await choose_category_tree(
                session,
                prompt_prefix="Queue: Select New Category",
                default_type=selected_tx.type if selected_tx.type in {"income", "expense"} else None,
                restrict_to_default_type=True,
            )
            if selected_cat == TRANSFER_CHOICE:
                await update_transaction_category(session, selected_tx.id, category_id=None, set_transfer=True)
                print("Updated and verified.")
            elif selected_cat:
                await update_transaction_category(session, selected_tx.id, selected_cat.id)
                print("Updated and verified.")
            continue

        if tx_action == "Delete Transaction":
            confirm = await inquirer.confirm(message="Are you sure?").execute_async()
            if confirm:
                await delete_transaction(session, selected_tx.id)
                print("Deleted.")
            continue


async def manage_categories_menu(session):
    while True:
        action = await inquirer.select(
            message="Manage Categories:",
            choices=[
                "List Categories",
                "Add Category",
                "Delete Category",
                Choice(value=None, name="Back to Main Menu")
            ]
        ).execute_async()
        
        if not action: break
        
        if action == "List Categories":
            cats = await get_all_categories(session)
            if not cats:
                print("No categories found.")
                continue
                
            grouped = _group_categories_by_type_and_parent(cats)
                
            print("\nCategories:")
            for ctype in sorted(grouped.keys()):
                print(f"Type: {ctype.upper()}")
                for parent in sorted(grouped[ctype].keys()):
                    print(f"  📁 {parent} [{ctype}]")
                    for c in grouped[ctype][parent]:
                        print(f"     └── {c.name} [{ctype}]")
            print("")
            
        elif action == "Add Category":
            cat_type = await inquirer.select(
                message="Category Type:",
                choices=["expense", "income"]
            ).execute_async()
            
            is_new_parent = await inquirer.confirm(message="Is this a new Parent Category Group?").execute_async()
            
            parent_name = ""
            if is_new_parent:
                parent_name = await inquirer.text(message="Enter New Parent Group Name:").execute_async()
            else:
                # Select existing parent
                cats = await get_all_categories(session)
                parents = sorted(list(set(c.parent_name for c in cats if c.type == cat_type)))
                if not parents:
                    print(f"No existing {cat_type} parent categories. You must create one.")
                    parent_name = await inquirer.text(message="Enter New Parent Group Name:").execute_async()
                else:
                    parent_name = await inquirer.fuzzy(
                        message="Select Parent Group:",
                        choices=[f"{p} [{cat_type}]" for p in parents]
                    ).execute_async()
                    if parent_name:
                        parent_name = parent_name.rsplit(" [", 1)[0]
            
            if not parent_name: continue
            
            name = await inquirer.text(message="Enter Category Name:").execute_async()
            if not name: continue
            
            success, msg = await add_category(session, name, parent_name, cat_type)
            print(f"\n{msg}\n")
            
        elif action == "Delete Category":
            cats = await get_all_categories(session)
            if not cats:
                print("No categories to delete.")
                continue
                
            # Select Category
            choices = [Choice(value=c, name=format_category_obj_label(c)) for c in cats]
            choices.append(Choice(value=None, name="Cancel"))
            
            target_cat = await inquirer.fuzzy(
                message="Select Category to Delete:",
                choices=choices
            ).execute_async()
            
            if not target_cat: continue
            
            # Check logic
            # 1. Transactions?
            # 2. If it's the last child of a parent, parent effectively disappears (which is fine, it's just a string)
            
            # Helper to check transactions count
            from src.database import Transaction
            stmt = select(Transaction).where(Transaction.category_id == target_cat.id)
            res = await session.execute(stmt)
            txs = res.scalars().all()
            count = len(txs)
            
            reassign_id = None
            delete_txs = False
            
            if count > 0:
                print(f"\n⚠️  Warning: This category has {count} transactions assigned to it.")
                sub_action = await inquirer.select(
                    message="How to handle these transactions?",
                    choices=[
                        Choice(value="reassign", name="Re-assign to another category"),
                        Choice(value="delete", name="Delete transactions too"),
                        Choice(value="cancel", name="Cancel Operation")
                    ]
                ).execute_async()
                
                if sub_action == "cancel": continue
                
                if sub_action == "delete":
                    confirm_del = await inquirer.confirm(message=f"Are you sure you want to delete {count} transactions?").execute_async()
                    if not confirm_del: continue
                    delete_txs = True
                    
                elif sub_action == "reassign":
                    # Filter out self
                    other_cats = [c for c in cats if c.id != target_cat.id]
                    if not other_cats:
                        print("No other categories to reassign to!")
                        continue
                        
                    rc_choices = [Choice(value=c.id, name=format_category_obj_label(c)) for c in other_cats]
                    reassign_id = await inquirer.fuzzy(
                        message="Select New Category for transactions:",
                        choices=rc_choices
                    ).execute_async()
                    
                    if not reassign_id: continue
            
            # Final Confirm
            confirm = await inquirer.confirm(message=f"Delete category '{format_category_obj_label(target_cat)}'?").execute_async()
            if confirm:
                success, msg = await delete_category(session, target_cat.id, reassign_category_id=reassign_id, delete_transactions=delete_txs)
                print(f"\n{msg}\n")


async def manage_global_rulebook_menu(session):
    while True:
        action = await inquirer.select(
            message="Manage AI Rulebook:",
            choices=[
                "List Rules",
                "Add Rule",
                "Disable Rule",
                "Enable Rule",
                "Delete Rule",
                Choice(value=None, name="Back to Main Menu")
            ]
        ).execute_async()

        if not action:
            break

        if action == "List Rules":
            rules = await get_global_memory_entries(session, include_inactive=True, limit=500)
            if not rules:
                print("No global rules found.")
                continue
            print("\nGlobal AI Rulebook:")
            for r in rules:
                status = "ACTIVE" if r.is_active else "INACTIVE"
                created = r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "-"
                print(f"[{status}] #{r.id} ({created}) [{r.source}] {r.instruction}")
            print("")

        elif action == "Add Rule":
            text = await inquirer.text(message="Rule text to persist:").execute_async()
            ok, msg = await add_global_memory_instruction(session, text, source="manual_rulebook")
            await session.commit()
            print(f"\n{msg}\n")

        elif action in {"Disable Rule", "Enable Rule"}:
            target_active = action == "Enable Rule"
            rules = await get_global_memory_entries(session, include_inactive=True, limit=500)
            if not rules:
                print("No rules available.")
                continue
            filtered = [r for r in rules if r.is_active != target_active]
            if not filtered:
                state_name = "inactive" if target_active else "active"
                print(f"No {state_name} rules found to modify.")
                continue

            choices = [
                Choice(
                    value=r.id,
                    name=f"#{r.id} [{r.source}] {r.instruction[:90]}"
                ) for r in filtered
            ]
            choices.append(Choice(value=None, name="Cancel"))
            selected_id = await inquirer.fuzzy(
                message=f"Select rule to {'enable' if target_active else 'disable'}:",
                choices=choices
            ).execute_async()
            if selected_id:
                ok, msg = await set_global_memory_active(session, selected_id, target_active)
                print(f"\n{msg}\n")

        elif action == "Delete Rule":
            rules = await get_global_memory_entries(session, include_inactive=True, limit=500)
            if not rules:
                print("No rules available.")
                continue
            choices = [
                Choice(
                    value=r.id,
                    name=f"#{r.id} [{'ACTIVE' if r.is_active else 'INACTIVE'}] {r.instruction[:90]}"
                ) for r in rules
            ]
            choices.append(Choice(value=None, name="Cancel"))
            selected_id = await inquirer.fuzzy(
                message="Select rule to delete:",
                choices=choices
            ).execute_async()
            if selected_id:
                confirm = await inquirer.confirm(message=f"Delete rule #{selected_id}?").execute_async()
                if confirm:
                    ok, msg = await delete_global_memory_instruction(session, selected_id)
                    print(f"\n{msg}\n")

async def reset_database_menu(session):
    print("\n⚠️  Danger Zone: Reset Database / Tables")
    action = await inquirer.select(
        message="Reset Options:",
        choices=[
            "Reset Entire Database",
            "Reset Specific Tables",
            Choice(value=None, name="Cancel"),
        ],
    ).execute_async()

    if not action:
        return

    if action == "Reset Entire Database":
        confirm_1 = await inquirer.confirm(
            message="Do you want to reset the entire database?"
        ).execute_async()
        if not confirm_1:
            return

        confirm_text = await inquirer.text(
            message="Type RESET to confirm:"
        ).execute_async()
        if confirm_text != "RESET":
            print("Confirmation text mismatch. Reset cancelled.\n")
            return

        confirm_2 = await inquirer.confirm(
            message="Final confirmation: This cannot be undone. Proceed?"
        ).execute_async()
        if not confirm_2:
            return

        ok, msg = await reset_database()
        print(f"\n{msg}")
        ok_seed, seed_msg = await seed_reference_data(session)
        print(f"{seed_msg}\n")
        return

    table_names = get_resettable_table_names()
    counts = await get_table_row_counts(session, table_names=table_names)
    table_choices = [
        Choice(value=t, name=f"{t} ({counts.get(t, 0)} rows)")
        for t in table_names
    ]
    selected = await inquirer.checkbox(
        message="Select tables to reset:",
        choices=table_choices,
    ).execute_async()

    if not selected:
        print("No tables selected.\n")
        return

    confirm = await inquirer.confirm(
        message=f"Reset selected tables ({', '.join(selected)})?"
    ).execute_async()
    if not confirm:
        return

    ok, msg = await reset_selected_tables(session, selected)
    if ok:
        print(f"\n{msg}\n")
    else:
        print("\nReset blocked:")
        print(msg)
        print("")



async def import_review_callback(tx_data, current_cat_id, confidence, current_type, reasoning, session):
    """
    Called for each transaction during import if review is enabled.
    """
    def box_text(lines, width=88):
        out = []
        border = "+" + "-" * (width - 2) + "+"
        out.append(border)
        for line in lines:
            wrapped = textwrap.wrap(str(line), width=width - 4) or [""]
            for part in wrapped:
                out.append(f"| {part:<{width - 4}} |")
        out.append(border)
        return "\n".join(out)

    def source_block_lines(raw_csv_row):
        raw = (raw_csv_row or "").strip()
        if not raw:
            return []
        # Multiline-table parser stores block lines joined by " | ".
        if " | " in raw:
            return [x.strip() for x in raw.split(" | ") if x.strip()]
        return [raw]

    ai = CategorizerAI()
    effective_cat_id = current_cat_id
    effective_type = current_type
    effective_confidence = confidence
    effective_reasoning = reasoning
    change_log = []
    discussion_history = []
    locked_expected_type = tx_data["type"] if tx_data.get("type") in {"expense", "income"} else None
    suggestion_candidates = await ai.suggest_category_candidates(
        tx_data["description"],
        session,
        min_candidates=3,
        expected_type=locked_expected_type,
    )

    while True:
        if effective_type == "transfer":
            effective_cat_id = None

        parent_name, cat_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
        suggestion_label = format_category_label(parent_name, cat_name, effective_type)

        type_disp = effective_type.upper()
        if effective_type == "transfer":
            type_disp = "TRANSFER OUT" if tx_data["amount"] < 0 else "TRANSFER IN"

        suggestion_lines = []
        for idx, candidate in enumerate(suggestion_candidates[:5], start=1):
            s_parent, s_name = await get_category_display_from_values(session, candidate["type"], candidate["id"])
            s_label = format_category_label(s_parent, s_name, candidate["type"])
            suggestion_lines.append(
                f"  {idx}. {s_label} ({candidate['confidence']:.2f})"
            )
        if not suggestion_lines:
            suggestion_lines = ["  No category suggestions available."]

        block_lines = source_block_lines(tx_data.get("raw_csv_row"))
        block_section = []
        if block_lines:
            block_section.extend(["Source Block:"])
            block_section.extend([f"  - {line}" for line in block_lines])

        summary_box = box_text([
            f"Date: {tx_data['date']}    Amount: {tx_data['amount']}",
            f"Type: {type_disp}",
            f"Description: {tx_data['description']}",
            *block_section,
            f"AI Suggestion: {suggestion_label}",
            f"Confidence: {effective_confidence:.2f}",
            f"Reasoning: {effective_reasoning}",
            "Suggested Categories:",
            *suggestion_lines,
        ])

        action = await inquirer.select(
            message=f"{summary_box}\nAction:",
            choices=[
                Choice(value="accept", name="Accept & Verify"),
                Choice(value="pick_suggested", name="Pick from Suggested Categories"),
                Choice(value="change", name="Change Category"),
                Choice(value="refresh", name="Refresh LLM Reasoning"),
                Choice(value="coach", name="Coach Model"),
                Choice(value="discuss", name="Discuss Current Decision"),
                Choice(value="skip", name="Skip Review (Accept as AI prediction)"),
            ],
            default="accept"
        ).execute_async()

        if action == "accept":
            if change_log:
                change_summary = " | ".join(change_log)
                if effective_reasoning:
                    effective_reasoning = f"{effective_reasoning} [Review changes: {change_summary}]"
                else:
                    effective_reasoning = f"Review changes: {change_summary}"
            return effective_cat_id, True, effective_type, effective_confidence, effective_reasoning

        if action == "skip":
            if change_log:
                change_summary = " | ".join(change_log)
                if effective_reasoning:
                    effective_reasoning = f"{effective_reasoning} [Review changes: {change_summary}]"
                else:
                    effective_reasoning = f"Review changes: {change_summary}"
            return effective_cat_id, False, effective_type, effective_confidence, effective_reasoning

        if action == "pick_suggested":
            if not suggestion_candidates:
                print("No suggested categories available.")
                continue

            choices = []
            for idx, candidate in enumerate(suggestion_candidates[:10], start=1):
                s_parent, s_name = await get_category_display_from_values(session, candidate["type"], candidate["id"])
                s_label = format_category_label(s_parent, s_name, candidate["type"])
                choices.append(
                    Choice(
                        value=candidate,
                        name=f"{idx}. {s_label} | conf={candidate['confidence']:.2f}",
                    )
                )
            choices.append(Choice(value=None, name="Back"))

            selected = await inquirer.select(
                message="Select suggested category:",
                choices=choices,
            ).execute_async()
            if selected:
                old_parent, old_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                old_label = format_category_label(old_parent, old_name, effective_type)
                effective_cat_id = selected["id"]
                effective_type = selected["type"]
                effective_confidence = selected["confidence"]
                effective_reasoning = selected["reasoning"]
                new_parent, new_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                new_label = format_category_label(new_parent, new_name, effective_type)
                if old_label != new_label:
                    change_log.append(f"suggested pick {old_label} -> {new_label}")
            continue

        if action == "change":
            selected_cat = await choose_category_tree(
                session,
                prompt_prefix="Change Category",
                default_type=locked_expected_type or (effective_type if effective_type in {"income", "expense"} else None),
                restrict_to_default_type=bool(locked_expected_type),
            )
            if selected_cat == TRANSFER_CHOICE:
                old_parent, old_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                old_label = format_category_label(old_parent, old_name, effective_type)
                effective_cat_id = None
                effective_type = "transfer"
                new_label = "(Transfer) > (Transfer) [transfer]"
                prior_reasoning = effective_reasoning or "No prior reasoning."
                reflection = await ai.generate_reflection(
                    tx_data["description"],
                    old_label,
                    new_label,
                    prior_reasoning
                )
                effective_reasoning = (
                    f"Manual override during review: changed from {old_label} to {new_label}. "
                    f"Reflection: {reflection}"
                )
                effective_confidence = 1.0
                if old_label != new_label:
                    change_log.append(f"manual override {old_label} -> {new_label}")
            elif selected_cat:
                old_parent, old_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                old_label = format_category_label(old_parent, old_name, effective_type)
                effective_cat_id = selected_cat.id
                effective_type = selected_cat.type
                new_label = format_category_obj_label(selected_cat)
                prior_reasoning = effective_reasoning or "No prior reasoning."
                reflection = await ai.generate_reflection(
                    tx_data["description"],
                    old_label,
                    new_label,
                    prior_reasoning
                )
                effective_reasoning = (
                    f"Manual override during review: changed from {old_label} to {new_label}. "
                    f"Reflection: {reflection}"
                )
                effective_confidence = 1.0
                if old_label != new_label:
                    change_log.append(f"manual override {old_label} -> {new_label}")
            continue

        if action == "refresh":
            old_parent, old_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
            old_label = format_category_label(old_parent, old_name, effective_type)
            suggestion_candidates = await ai.suggest_category_candidates(
                tx_data["description"], session, min_candidates=3, expected_type=locked_expected_type
            )
            if suggestion_candidates:
                top = suggestion_candidates[0]
                effective_cat_id = top["id"]
                effective_confidence = top["confidence"]
                effective_reasoning = top["reasoning"]
                effective_type = top["type"] or effective_type
            new_parent, new_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
            new_label = format_category_label(new_parent, new_name, effective_type)
            if old_label != new_label:
                change_log.append(f"refresh changed suggestion {old_label} -> {new_label}")
            continue

        if action == "coach":
            coaching_text = await inquirer.text(
                message="Add coaching for model memory (global rulebook):"
            ).execute_async()
            if coaching_text and coaching_text.strip():
                await add_global_memory_instruction(session, coaching_text.strip(), source="review_coaching")
                suggestion_candidates = await ai.suggest_category_candidates(
                    tx_data["description"],
                    session,
                    min_candidates=3,
                    extra_instruction=coaching_text.strip(),
                    expected_type=locked_expected_type,
                )
                old_parent, old_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                old_label = format_category_label(old_parent, old_name, effective_type)
                if suggestion_candidates:
                    top = suggestion_candidates[0]
                    effective_cat_id = top["id"]
                    effective_confidence = top["confidence"]
                    effective_reasoning = top["reasoning"]
                    effective_type = top["type"] or effective_type
                new_parent, new_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                new_label = format_category_label(new_parent, new_name, effective_type)
                if old_label != new_label:
                    change_log.append(f"coached update {old_label} -> {new_label}")
            continue

        if action == "discuss":
            print("\nDiscussion mode for current transaction.")
            print("Commands: /done to return, /search <query> to force web search.\n")

            while True:
                user_msg = await inquirer.text(
                    message="You:"
                ).execute_async()
                user_msg = (user_msg or "").strip()

                if not user_msg:
                    continue
                if user_msg.lower() in {"/done", "done", "exit"}:
                    break

                forced_search_query = None
                llm_message = user_msg

                if user_msg.lower().startswith("/search"):
                    forced_search_query = user_msg[7:].strip()
                    if not forced_search_query:
                        print("Usage: /search <query>")
                        continue
                    llm_message = (
                        "Use this explicit web search context to review the current decision. "
                        f"Query: {forced_search_query}. Explain whether category/type should change and why."
                    )

                model_reply = await ai.discuss_transaction(
                    tx_data=tx_data,
                    current_type=effective_type,
                    current_cat_id=effective_cat_id,
                    current_reasoning=effective_reasoning,
                    session=session,
                    user_message=llm_message,
                    conversation_history=discussion_history,
                    web_search_query=forced_search_query
                )

                discussion_history.append({"role": "user", "content": user_msg})
                discussion_history.append({"role": "assistant", "content": model_reply})
                print("\n" + box_text([f"Model: {model_reply}"]))

            if discussion_history:
                conversation_instruction = await ai.summarize_review_conversation(
                    tx_description=tx_data["description"],
                    conversation_history=discussion_history
                )
                if conversation_instruction and conversation_instruction.strip():
                    old_parent, old_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                    old_label = format_category_label(old_parent, old_name, effective_type)

                    suggestion_candidates = await ai.suggest_category_candidates(
                        tx_data["description"],
                        session,
                        min_candidates=3,
                        extra_instruction=conversation_instruction.strip(),
                        expected_type=locked_expected_type,
                    )
                    if suggestion_candidates:
                        top = suggestion_candidates[0]
                        effective_cat_id = top["id"]
                        effective_confidence = top["confidence"]
                        effective_reasoning = (
                            f"{top['reasoning']} [Conversation guidance applied: {conversation_instruction.strip()}]"
                        )
                        effective_type = top["type"] or effective_type

                    new_parent, new_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                    new_label = format_category_label(new_parent, new_name, effective_type)
                    if old_label != new_label:
                        change_log.append(f"discussion-informed update {old_label} -> {new_label}")
            continue

async def import_wizard(session):
    # 1. Select Bank
    bank_names = list_bank_names()
    if not bank_names:
        print("No bank formats configured. Please add one via 'Manage Bank Formats'.")
        return

    bank = await inquirer.select(
        message="Select Bank Format:",
        choices=bank_names + [Choice(value=None, name="Cancel")]
    ).execute_async()
    
    if not bank: return

    # 2. Select File
    file_path = await inquirer.filepath(
        message="Path to CSV/PDF file:",
        default=os.getcwd(), # Removed trailing slash
        validate=lambda x: os.path.isfile(x) and x.lower().endswith((".csv", ".pdf")),
        only_files=True
    ).execute_async()
    
    if not file_path: return

    if file_path.lower().endswith(".pdf"):
        inspect_now = await inquirer.confirm(
            message="Inspect PDF text/blocks before importing?",
            default=True,
        ).execute_async()
        if inspect_now:
            await inspect_pdf_text_menu(default_file_path=file_path, default_bank=bank)

    # 3. Select Account
    accounts = await get_all_accounts(session)
    if not accounts:
        print("No accounts found. Please creates one first.")
        return
        
    choices = [Choice(value=acc.name, name=acc.name) for acc in accounts]
    account_name = await inquirer.select(
        message="Associate with Account:",
        choices=choices
    ).execute_async()
    
    # 3.5 Option to review iteratively
    do_interactive_review = await inquirer.confirm(message="Review each transaction as it is processed?").execute_async()
    callback = import_review_callback if do_interactive_review else None

    print("\nProcessing... (This may take a moment for AI categorization)\n")
    # import logic
    success, msg, new_txs = await process_import(session, bank, file_path, account_name, review_callback=callback) # No export path yet
    
    if success:
        print(f"\n✅ Success: {msg}\n")
        
        # If we didn't do interactive review, maybe ask for bulk review?
        if new_txs and not do_interactive_review:
            do_review = await inquirer.confirm(message="Review and Verify these transactions now?").execute_async()
            if do_review:
                await review_transactions(session, new_txs)
    else:
        print(f"\n❌ Error: {msg}\n")
        return

    # 4. Output? (Post-Review Export)
    do_export = await inquirer.confirm(message="Export to Bluecoins CSV now?").execute_async()
    output_path = None
    if do_export:
        output_path = await inquirer.filepath(
            message="Output Path:",
            default="bluecoins_import.csv",
            validate=lambda x: not os.path.isdir(x)
        ).execute_async()
        
        # We need to re-fetch mainly if reviewed modified them.
        # process_import returned just the message if verify not done in stream. 
        # But we modified them in DB. So just fetch them again.
        
        tx_ids = [t.id for t in new_txs] if new_txs else []
        if tx_ids:
            from sqlalchemy import select
            from src.database import Transaction
            from sqlalchemy.orm import selectinload
            stmt = select(Transaction).options(selectinload(Transaction.category), selectinload(Transaction.account)).where(Transaction.id.in_(tx_ids))
            res = await session.execute(stmt)
            final_txs = res.scalars().all()
            
            success, msg = export_to_bluecoins_csv(final_txs, output_path)
            print(msg)


from src.chat import FinanceChatAI


def _date_regex_hint_from_format(fmt):
    tokens = {
        "%d": r"\d{1,2}",
        "%m": r"\d{1,2}",
        "%Y": r"\d{4}",
        "%y": r"\d{2}",
        "%b": r"[A-Za-z]{3}",
        "%B": r"[A-Za-z]+",
    }
    out = re.escape(fmt)
    for token, repl in tokens.items():
        out = out.replace(re.escape(token), repl)
    out = out.replace(r"\ ", r"\s+")
    return out


def _build_guided_pdf_regex():
    date_pattern = r"\d{1,2}\s+[A-Za-z]{3}"
    amount_pattern = r"\$?[\d,]+\.\d{2}"
    return rf"^({date_pattern})\s+(.+?)\s+({amount_pattern})?\s*({amount_pattern})?\s+{amount_pattern}$"


async def bank_format_builder_menu():
    payload = load_banks_payload()
    existing = sorted(payload["banks"].keys())

    bank_name = await inquirer.text(message="Bank name to add/update (e.g. ANZ):").execute_async()
    bank_name = (bank_name or "").strip()
    if not bank_name:
        return

    if bank_name in existing:
        overwrite = await inquirer.confirm(
            message=f"Bank '{bank_name}' already exists. Overwrite format?"
        ).execute_async()
        if not overwrite:
            return

    source_mode = await inquirer.select(
        message="What input format should this bank support?",
        choices=[
            Choice(value="csv", name="CSV only"),
            Choice(value="pdf", name="PDF only"),
            Choice(value="both", name="CSV and PDF"),
            Choice(value=None, name="Cancel"),
        ],
    ).execute_async()
    if not source_mode:
        return

    date_formats_raw = await inquirer.text(
        message="Date formats (comma-separated strptime patterns):",
        default="%d %b %Y,%d/%m/%Y,%Y-%m-%d,%d-%m-%Y,%d %b",
    ).execute_async()
    date_formats = [x.strip() for x in (date_formats_raw or "").split(",") if x.strip()]
    if not date_formats:
        date_formats = ["%d %b %Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]

    cfg = {"date_formats": date_formats}

    if source_mode in {"csv", "both"}:
        print("\nCSV mapping\n-----------")
        cfg["date_column"] = await inquirer.text(message="Date column name:").execute_async()
        cfg["description_column"] = await inquirer.text(message="Description column name:").execute_async()
        cfg["amount_column"] = await inquirer.text(message="Amount column name:").execute_async()

        type_mode = await inquirer.select(
            message="How should transaction type be inferred?",
            choices=[
                Choice(value="amount_sign", name="Use amount sign (+/-)"),
                Choice(value="direction_column", name="Use direction column (IN/OUT etc.)"),
            ],
        ).execute_async()
        cfg["type_determination"] = type_mode
        cfg["negate_amounts"] = await inquirer.confirm(
            message="Negate parsed amounts? (for statements where signs are reversed)",
            default=False,
        ).execute_async()

        if type_mode == "direction_column":
            cfg["direction_column"] = await inquirer.text(message="Direction column name:").execute_async()
            cfg["direction_in_value"] = await inquirer.text(message="Incoming value (e.g. IN):").execute_async()
            cfg["direction_out_value"] = await inquirer.text(message="Outgoing value (e.g. OUT):").execute_async()

    if source_mode in {"pdf", "both"}:
        print("\nPDF mapping\n-----------")
        pdf_mode = await inquirer.select(
            message="PDF parse mode",
            choices=[
                Choice(value="guided_debit_credit", name="Guided: Date + Description + Credit/Debit + Balance"),
                Choice(value="manual_regex", name="Manual regex"),
            ],
        ).execute_async()

        if pdf_mode == "guided_debit_credit":
            cfg["pdf_regex"] = _build_guided_pdf_regex()
            cfg["pdf_date_group"] = 1
            cfg["pdf_description_group"] = 2
            cfg["pdf_credit_group"] = 3
            cfg["pdf_debit_group"] = 4
            cfg["pdf_prefer_debit_when_single_amount"] = await inquirer.confirm(
                message="If only one amount is found, treat it as Debit (expense)?",
                default=False,
            ).execute_async()
            print("Generated regex for split credit/debit PDF lines.")
        else:
            default_date_re = _date_regex_hint_from_format(date_formats[0]) if date_formats else r"\d{1,2}\s+[A-Za-z]{3}\s+\d{4}"
            default_regex = rf"^({default_date_re})\s+(.+?)\s+(-?\$?[\d,]+\.\d{{2}})$"
            cfg["pdf_regex"] = await inquirer.text(
                message="Regex with groups: date(1), description(2), amount(3)",
                default=default_regex,
            ).execute_async()
            cfg["pdf_date_group"] = 1
            cfg["pdf_description_group"] = 2
            cfg["pdf_amount_group"] = 3

    upsert_bank_format(bank_name, cfg)
    print(f"\nSaved bank format '{bank_name}' to data/banks_config.json\n")
    print(cfg)

    if bank_name.upper() == "ANZ":
        print(
            "\nANZ tip: for lines like '29 Jan ... Credit Debit Balance', use the guided PDF mode.\n"
            "Keep '%d %b' in date formats; the parser can infer the year from text like 'Effective Date 27/01/2026'.\n"
        )

async def chat_wizard(session):
    print("\n💬 Chat with your Finance Data")
    print("Ask questions like 'How much did I spend on Food last month?' or 'Show me top expenses'.")
    print("Type 'exit' or 'q' to go back.\n")
    
    chat_ai = FinanceChatAI()
    
    while True:
        question = await inquirer.text(message="You:").execute_async()
        if question.lower() in ['exit', 'quit', 'q']:
            break
            
        print("🤖 Thinking...")
        response = await chat_ai.chat(question, session)
        print(f"\nAI: {response}\n")


async def inspect_pdf_text_menu(default_file_path=None, default_bank=None):
    file_path = default_file_path
    if not file_path:
        file_path = await inquirer.filepath(
            message="Path to PDF file:",
            default=os.getcwd(),
            validate=lambda x: os.path.isfile(x) and x.lower().endswith(".pdf"),
            only_files=True,
        ).execute_async()
    if not file_path:
        return

    mode = await inquirer.select(
        message="Display mode:",
        choices=[
            Choice(value="both", name="Raw + Cleaned (default)"),
            Choice(value="raw", name="Raw only"),
            Choice(value="cleaned", name="Cleaned only"),
            Choice(value="blocks", name="Blocks (assembled multiline transactions)"),
            Choice(value=None, name="Cancel"),
        ],
    ).execute_async()
    if not mode:
        return

    preview_label = "Max preview blocks:" if mode == "blocks" else "Max preview lines:"
    max_lines_raw = await inquirer.text(
        message=preview_label,
        default="500",
        validate=lambda x: (x or "").strip().isdigit() and int((x or "").strip()) > 0,
        invalid_message="Enter a positive integer.",
    ).execute_async()
    max_lines = int((max_lines_raw or "500").strip())

    parser = BankParser()
    report_preview = None
    full_report = None
    try:
        if mode == "blocks":
            bank_name = default_bank
            if not bank_name:
                bank_name = await inquirer.select(
                    message="Select bank format for block assembly:",
                    choices=list_bank_names() + [Choice(value=None, name="Cancel")],
                ).execute_async()
            if not bank_name:
                return
            blocks_data = parser.extract_pdf_blocks_debug(file_path, bank_name)
            report_preview = format_pdf_blocks_report(blocks_data, max_blocks=max_lines)
            full_report = format_pdf_blocks_report(blocks_data, max_blocks=None)
        else:
            debug_data = parser.extract_pdf_debug(file_path, apply_cleaning=True)
            report_preview = format_pdf_debug_report(debug_data, mode=mode, max_lines=max_lines)
            full_report = format_pdf_debug_report(debug_data, mode=mode, max_lines=None)
    except Exception as e:
        print(f"\n❌ Error: {e}\n")
        return

    print("\n" + report_preview)

    do_export = await inquirer.confirm(message="Export full report to .txt file?").execute_async()
    if not do_export:
        return

    output_path = await inquirer.filepath(
        message="Output path:",
        default="pdf_debug_report.txt",
        validate=lambda x: not os.path.isdir(x),
    ).execute_async()
    if not output_path:
        return

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_report)
    print(f"\nSaved full debug report to {output_path}\n")


async def _main_menu_snapshot(session):
    accounts = await list_accounts(session)
    categories = await get_all_categories(session)
    total_tx = int(await session.scalar(select(func.count(Transaction.id))) or 0)
    verified_tx = int(
        await session.scalar(
            select(func.count(Transaction.id)).where(Transaction.is_verified.is_(True))
        )
        or 0
    )
    unverified_tx = max(total_tx - verified_tx, 0)

    queue_rows = await get_queue_stats(session)
    needs_review = int(
        sum(
            int(count or 0)
            for state, _bucket, count in queue_rows
            if (state or "") in {"needs_review", "force_review"}
        )
    )

    return {
        "accounts": len(accounts),
        "categories": len(categories),
        "total_tx": total_tx,
        "verified_tx": verified_tx,
        "unverified_tx": unverified_tx,
        "needs_review": needs_review,
    }


def _main_menu_message(stats):
    width = 86
    border = "+" + "-" * (width - 2) + "+"
    title = " Bluecoins Manager  |  Interactive CLI "
    title_pad = max((width - 2 - len(title)) // 2, 0)
    title_line = "|" + (" " * title_pad) + title + (" " * (width - 2 - title_pad - len(title))) + "|"

    def row(text=""):
        return ("| " + text).ljust(width - 1) + "|"

    lines = [
        border,
        title_line,
        row(),
        row("Data Snapshot"),
        row(),
        row(
            f"Accounts: {stats['accounts']:<5}    Categories: {stats['categories']:<5}    "
            f"Transactions: {stats['total_tx']:<8}"
        ),
        row(
            f"Verified: {stats['verified_tx']:<8}    Unverified: {stats['unverified_tx']:<8}    "
            f"Needs Review: {stats['needs_review']:<8}"
        ),
        row(),
        row("Tip: Start with 'Import Transactions', then review and verify."),
        row(),
        border,
        "Main Menu:",
        "",
    ]
    return "\n".join(lines)


async def interactive_main():
    print("Welcome to Bluecoins Manager V2")
    await init_db()
    
    async with AsyncSessionLocal() as session:
        _, seed_msg = await seed_reference_data(session)
        print(seed_msg)
        while True:
            stats = await _main_menu_snapshot(session)
            action = await inquirer.select(
                message=_main_menu_message(stats),
                choices=[
                    Separator("=== Workflow ==="),
                    Choice(value="import", name="Import Transactions"),
                    Choice(value="transactions", name="Review / Manage Transactions"),
                    Choice(value="chat", name="Chat with your Data"),
                    Separator(" "),
                    Separator("=== Configuration ==="),
                    Choice(value="categories", name="Manage Categories"),
                    Choice(value="accounts", name="Manage Accounts"),
                    Choice(value="banks", name="Manage Bank Formats"),
                    Choice(value="rulebook", name="Manage AI Rulebook"),
                    Separator(" "),
                    Separator("=== Tools ==="),
                    Choice(value="pdf", name="Inspect PDF Text (pypdf)"),
                    Choice(value="reset", name="Reset Database"),
                    Separator(" "),
                    Choice(value=None, name="Exit"),
                ],
            ).execute_async()
            
            if not action:
                print("Goodbye!")
                break
                
            if action == "accounts":
                await manage_accounts_menu(session)
            elif action == "import":
                await import_wizard(session)
            elif action == "transactions":
                await manage_transactions_menu(session)
            elif action == "categories":
                await manage_categories_menu(session)
            elif action == "banks":
                await bank_format_builder_menu()
            elif action == "pdf":
                await inspect_pdf_text_menu()
            elif action == "rulebook":
                await manage_global_rulebook_menu(session)
            elif action == "reset":
                await reset_database_menu(session)
            elif action == "chat":
                await chat_wizard(session)

if __name__ == "__main__":
    try:
        import asyncio
        asyncio.run(interactive_main())
    except KeyboardInterrupt:
        print("\nGoodbye!")
