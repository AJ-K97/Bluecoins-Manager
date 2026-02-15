import os
import textwrap

from datetime import datetime
from sqlalchemy import select
from InquirerPy import inquirer
from InquirerPy.separator import Separator
from InquirerPy.base.control import Choice
from src.database import init_db, AsyncSessionLocal
from src.commands import (
    list_accounts, add_account, delete_account, process_import, get_all_accounts,
    get_transactions, update_transaction_category, delete_transaction, export_to_bluecoins_csv,
    get_all_categories, mark_transaction_verified, update_transaction_amount,
    add_category, delete_category, get_category_display_from_values, add_global_memory_instruction,
    get_global_memory_entries, set_global_memory_active, delete_global_memory_instruction,
    reset_database, seed_reference_data, format_category_obj_label, format_category_label,
    get_resettable_table_names, get_table_row_counts, reset_selected_tables,
    get_queue_transactions, get_queue_stats,
)
from src.ai import CategorizerAI

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


async def choose_category_tree(session, prompt_prefix="Select Category", default_type=None):
    cats = await get_all_categories(session)
    if not cats:
        return None

    grouped = _group_categories_by_type_and_parent(cats)
    available_types = sorted(grouped.keys())
    if default_type and default_type in available_types:
        available_types = [default_type] + [t for t in available_types if t != default_type]

    selected_type = await inquirer.select(
        message=f"{prompt_prefix}: Select Type",
        choices=[Choice(value=t, name=t.upper()) for t in available_types] + [Choice(value=None, name="Cancel")],
    ).execute_async()
    if not selected_type:
        return None

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
            )
            if selected_cat:
                await update_transaction_category(session, tx.id, selected_cat.id)
                await session.refresh(tx, ['category'])
                
        elif action == 'delete':
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
                cat_name = format_category_obj_label(t.category) if t.category else "Uncategorized > Uncategorized [unknown]"
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
                )
                if selected_cat:
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
            cat_name = format_category_obj_label(tx.category) if tx.category else "Uncategorized > Uncategorized [unknown]"
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
            )
            if selected_cat:
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
    def render_box(lines, width=88):
        border = "+" + "-" * (width - 2) + "+"
        print(border)
        for line in lines:
            wrapped = textwrap.wrap(str(line), width=width - 4) or [""]
            for part in wrapped:
                print(f"| {part:<{width - 4}} |")
        print(border)

    ai = CategorizerAI()
    effective_cat_id = current_cat_id
    effective_type = current_type
    effective_confidence = confidence
    effective_reasoning = reasoning
    change_log = []
    discussion_history = []

    while True:
        if effective_type == "transfer":
            effective_cat_id = None

        parent_name, cat_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
        suggestion_label = format_category_label(parent_name, cat_name, effective_type)

        type_disp = effective_type.upper()
        if effective_type == "transfer":
            type_disp = "TRANSFER OUT" if tx_data["amount"] < 0 else "TRANSFER IN"

        render_box([
            f"Date: {tx_data['date']}    Amount: {tx_data['amount']}",
            f"Type: {type_disp}",
            f"Description: {tx_data['description']}",
            f"AI Suggestion: {suggestion_label}",
            f"Confidence: {effective_confidence:.2f}",
            f"Reasoning: {effective_reasoning}"
        ])

        action = await inquirer.select(
            message="Action:",
            choices=[
                Choice(value="accept", name="Accept & Verify"),
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

        if action == "change":
            selected_cat = await choose_category_tree(
                session,
                prompt_prefix="Change Category",
                default_type=effective_type if effective_type in {"income", "expense"} else None,
            )
            if selected_cat:
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
            new_cat_id, new_conf, new_reason, new_type = await ai.suggest_category(tx_data["description"], session)
            effective_cat_id = new_cat_id
            effective_confidence = new_conf
            effective_reasoning = new_reason
            effective_type = new_type or effective_type
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
                new_cat_id, new_conf, new_reason, new_type = await ai.suggest_category(
                    tx_data["description"], session, extra_instruction=coaching_text.strip()
                )
                old_parent, old_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                old_label = format_category_label(old_parent, old_name, effective_type)
                effective_cat_id = new_cat_id
                effective_confidence = new_conf
                effective_reasoning = new_reason
                effective_type = new_type or effective_type
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
                render_box([f"Model: {model_reply}"])

            if discussion_history:
                conversation_instruction = await ai.summarize_review_conversation(
                    tx_description=tx_data["description"],
                    conversation_history=discussion_history
                )
                if conversation_instruction and conversation_instruction.strip():
                    old_parent, old_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                    old_label = format_category_label(old_parent, old_name, effective_type)

                    new_cat_id, new_conf, new_reason, new_type = await ai.suggest_category(
                        tx_data["description"],
                        session,
                        extra_instruction=conversation_instruction.strip()
                    )
                    effective_cat_id = new_cat_id
                    effective_confidence = new_conf
                    effective_reasoning = (
                        f"{new_reason} [Conversation guidance applied: {conversation_instruction.strip()}]"
                    )
                    effective_type = new_type or effective_type

                    new_parent, new_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                    new_label = format_category_label(new_parent, new_name, effective_type)
                    if old_label != new_label:
                        change_log.append(f"discussion-informed update {old_label} -> {new_label}")
            continue

async def import_wizard(session):
    # 1. Select Bank
    # Hardcoded for now, could load from config
    bank = await inquirer.select(
        message="Select Bank Format:",
        choices=["HSBC", "Wise", "CommBank", Choice(value=None, name="Cancel")]
    ).execute_async()
    
    if not bank: return

    # 2. Select File
    file_path = await inquirer.filepath(
        message="Path to CSV file:",
        default=os.getcwd(), # Removed trailing slash
        validate=lambda x: os.path.isfile(x) and x.endswith('.csv'),
        only_files=True
    ).execute_async()
    
    if not file_path: return

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

async def interactive_main():
    print("Welcome to Bluecoins Manager V2")
    await init_db()
    
    async with AsyncSessionLocal() as session:
        _, seed_msg = await seed_reference_data(session)
        print(seed_msg)
        while True:
            action = await inquirer.select(
                message="Main Menu:",
                choices=[
                    "Import Transactions",
                    "Manage Transactions",
                    "Manage Categories",
                    "Manage Accounts",
                    "Manage AI Rulebook",
                    "Reset Database",
                    "Chat with your Data",
                    Choice(value=None, name="Exit")
                ],
            ).execute_async()
            
            if not action:
                print("Goodbye!")
                break
                
            if action == "Manage Accounts":
                await manage_accounts_menu(session)
            elif action == "Import Transactions":
                await import_wizard(session)
            elif action == "Manage Transactions":
                await manage_transactions_menu(session)
            elif action == "Manage Categories":
                await manage_categories_menu(session)
            elif action == "Manage AI Rulebook":
                await manage_global_rulebook_menu(session)
            elif action == "Reset Database":
                await reset_database_menu(session)
            elif action == "Chat with your Data":
                await chat_wizard(session)

if __name__ == "__main__":
    try:
        import asyncio
        asyncio.run(interactive_main())
    except KeyboardInterrupt:
        print("\nGoodbye!")
