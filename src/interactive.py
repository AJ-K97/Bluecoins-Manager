import os
import asyncio
from datetime import datetime
from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from src.database import init_db, AsyncSessionLocal
from src.commands import (
    list_accounts, add_account, delete_account, process_import, get_all_accounts,
    get_transactions, update_transaction_category, delete_transaction, export_to_bluecoins_csv,
    get_all_categories
)

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
                print("") # Newline
                
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
            # Date Range?
            # For simplicity let's just export all for now or ask "All Time?"
            # Or ask for start/end string.
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
            # Format: Date | Desc | Amount | Category
            choices = []
            for t in txs[:50]: # Limit to 50 for UI
                cat_name = t.category.name if t.category else "Uncategorized"
                label = f"{t.date.strftime('%Y-%m-%d')} | {t.description[:20]:<20} | {t.amount:>10.2f} | {cat_name}"
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
                    
            elif tx_action == "Delete Transaction":
                confirm = await inquirer.confirm(message="Are you sure?").execute_async()
                if confirm:
                    await delete_transaction(session, selected_tx.id)
                    print("Deleted.")


async def import_wizard(session):
    # 1. Select Bank
    # Hardcoded for now, could load from config
    bank = await inquirer.select(
        message="Select Bank Format:",
        choices=["HSBC", "Wise", "CommBank", Choice(value=None, name="Cancel")]
    ).execute_async()
    
    if not bank: return

    # 2. Select File
    # Simple file input for now
    file_path = await inquirer.filepath(
        message="Path to CSV file:",
        default=os.getcwd() + "/",
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

    # 4. Output?
    do_export = await inquirer.confirm(message="Export to Bluecoins CSV now?").execute_async()
    output_path = None
    if do_export:
        output_path = await inquirer.filepath(
            message="Output Path:",
            default="bluecoins_import.csv",
            validate=lambda x: not os.path.isdir(x)
        ).execute_async()

    print("\nProcessing... (This may take a moment for AI categorization)\n")
    success, msg = await process_import(session, bank, file_path, account_name, output_path)
    
    if success:
        print(f"\n✅ Success: {msg}\n")
    else:
        print(f"\n❌ Error: {msg}\n")

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
                    "Manage Accounts",
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

if __name__ == "__main__":
    try:
        asyncio.run(interactive_main())
    except KeyboardInterrupt:
        print("\nGoodbye!")
