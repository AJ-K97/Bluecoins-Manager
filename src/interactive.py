import os
import textwrap

from datetime import datetime
from sqlalchemy import select
from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from src.database import init_db, AsyncSessionLocal
from src.commands import (
    list_accounts, add_account, delete_account, process_import, get_all_accounts,
    get_transactions, update_transaction_category, delete_transaction, export_to_bluecoins_csv,
    get_all_categories, mark_transaction_verified, update_transaction_amount,
    add_category, delete_category, get_category_display_from_values, add_global_memory_instruction,
    get_global_memory_entries, set_global_memory_active, delete_global_memory_instruction
)
from src.ai import CategorizerAI

from src.tui import TransactionReviewApp

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
            # Hierarchical Category Selection
            cats = await get_all_categories(session)
            
            # 1. Select Parent
            parent_names = sorted(list(set(c.parent_name for c in cats if c.parent_name)))
            parent_choices = [Choice(value=p, name=p) for p in parent_names]
            parent_choices.append(Choice(value=None, name="Cancel"))
            
            selected_parent = await inquirer.fuzzy(
                message=f"Select Parent Category for '{tx.description}':",
                choices=parent_choices,
            ).execute_async()
            
            if selected_parent:
                # 2. Select Child (Sub-category)
                child_cats = [c for c in cats if c.parent_name == selected_parent]
                child_choices = [Choice(value=c.id, name=c.name) for c in child_cats]
                child_choices.append(Choice(value=None, name="Back"))
                
                new_cat_id = await inquirer.fuzzy(
                    message=f"Select Sub-Category for '{tx.description}':",
                    choices=child_choices,
                ).execute_async()
                
                if new_cat_id:
                    await update_transaction_category(session, tx.id, new_cat_id)
                    # Refresh transaction to get new category name
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
                cat_name = t.category.name if t.category else "Uncategorized"
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
                cats = await get_all_categories(session)
                cat_choices = [Choice(value=c.id, name=f"{c.parent_name} > {c.name}") for c in cats]
                new_cat_id = await inquirer.fuzzy(
                    message="Select New Category:",
                    choices=cat_choices,
                ).execute_async()
                
                if new_cat_id:
                    await update_transaction_category(session, selected_tx.id, new_cat_id)
                    print("Updated!")
            
            elif tx_action == "Verify / Approve":
                await mark_transaction_verified(session, selected_tx.id)
                print("Verified!")

            elif tx_action == "Delete Transaction":
                confirm = await inquirer.confirm(message="Are you sure?").execute_async()
                if confirm:
                    await delete_transaction(session, selected_tx.id)
                    print("Deleted.")


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
                
            # Group by Parent
            from collections import defaultdict
            grouped = defaultdict(list)
            for c in cats:
                grouped[c.parent_name].append(c)
                
            print("\nCategories:")
            for parent in sorted(grouped.keys()):
                print(f"📁 {parent}")
                for c in sorted(grouped[parent], key=lambda x: x.name):
                    # Count transactions? Maybe overly expensive for simple list usage, 
                    # but helpful. Let's keep it simple for now.
                    print(f"   └── {c.name} ({c.type})")
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
                parents = sorted(list(set(c.parent_name for c in cats)))
                if not parents:
                    print("No existing parent categories. You must create one.")
                    parent_name = await inquirer.text(message="Enter New Parent Group Name:").execute_async()
                else:
                    parent_name = await inquirer.fuzzy(
                        message="Select Parent Group:",
                        choices=parents
                    ).execute_async()
            
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
            choices = [Choice(value=c, name=f"{c.parent_name} > {c.name}") for c in cats]
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
                        
                    rc_choices = [Choice(value=c.id, name=f"{c.parent_name} > {c.name}") for c in other_cats]
                    reassign_id = await inquirer.fuzzy(
                        message="Select New Category for transactions:",
                        choices=rc_choices
                    ).execute_async()
                    
                    if not reassign_id: continue
            
            # Final Confirm
            confirm = await inquirer.confirm(message=f"Delete category '{target_cat.parent_name} > {target_cat.name}'?").execute_async()
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

    while True:
        if effective_type == "transfer":
            effective_cat_id = None

        parent_name, cat_name = await get_category_display_from_values(session, effective_type, effective_cat_id)

        type_disp = effective_type.upper()
        if effective_type == "transfer":
            type_disp = "TRANSFER OUT" if tx_data["amount"] < 0 else "TRANSFER IN"

        render_box([
            f"Date: {tx_data['date']}    Amount: {tx_data['amount']}",
            f"Type: {type_disp}",
            f"Description: {tx_data['description']}",
            f"AI Suggestion: {parent_name} > {cat_name}",
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
                Choice(value="skip", name="Skip Review (Accept as AI prediction)"),
            ],
            default="accept"
        ).execute_async()

        if action == "accept":
            return effective_cat_id, True, effective_type

        if action == "skip":
            return effective_cat_id, False, effective_type

        if action == "change":
            cats = await get_all_categories(session)

            parent_names = sorted(list(set(c.parent_name for c in cats if c.parent_name)))
            parent_choices = [Choice(value=p, name=p) for p in parent_names]
            parent_choices.append(Choice(value=None, name="Cancel (Keep AI)"))

            selected_parent = await inquirer.fuzzy(
                message="Select Parent Category:",
                choices=parent_choices,
            ).execute_async()

            if selected_parent:
                child_cats = [c for c in cats if c.parent_name == selected_parent]
                child_choices = [Choice(value=c, name=c.name) for c in child_cats]
                child_choices.append(Choice(value=None, name="Back"))

                selected_cat = await inquirer.fuzzy(
                    message="Select Sub-Category:",
                    choices=child_choices,
                ).execute_async()

                if selected_cat:
                    effective_cat_id = selected_cat.id
                    effective_type = selected_cat.type
                    effective_reasoning = "User manually selected category during review."
                    effective_confidence = 1.0
            continue

        if action == "refresh":
            new_cat_id, new_conf, new_reason, new_type = await ai.suggest_category(tx_data["description"], session)
            effective_cat_id = new_cat_id
            effective_confidence = new_conf
            effective_reasoning = new_reason
            effective_type = new_type or effective_type
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
                effective_cat_id = new_cat_id
                effective_confidence = new_conf
                effective_reasoning = new_reason
                effective_type = new_type or effective_type
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
        while True:
            action = await inquirer.select(
                message="Main Menu:",
                choices=[
                    "Import Transactions",
                    "Manage Transactions",
                    "Manage Categories",
                    "Manage Accounts",
                    "Manage AI Rulebook",
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
            elif action == "Chat with your Data":
                await chat_wizard(session)

if __name__ == "__main__":
    try:
        import asyncio
        asyncio.run(interactive_main())
    except KeyboardInterrupt:
        print("\nGoodbye!")
