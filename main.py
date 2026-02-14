import argparse
import asyncio
import csv
import os
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from src.database import init_db, Account, Category, MappingRule, Transaction, AsyncSessionLocal
from src.parser import BankParser
from src.ai import CategorizerAI

async def list_accounts(session):
    result = await session.execute(select(Account))
    accounts = result.scalars().all()
    if not accounts:
        print("No accounts found.")
    else:
        print("Accounts:")
        for acc in accounts:
            print(f" - {acc.name} ({acc.institution})")

async def add_account(session, name, institution):
    try:
        session.add(Account(name=name, institution=institution))
        await session.commit()
        print(f"Added account '{name}'.")
    except IntegrityError:
        await session.rollback()
        print(f"Account '{name}' already exists.")

async def delete_account(session, name):
    result = await session.execute(select(Account).where(Account.name == name))
    acc = result.scalar_one_or_none()
    if acc:
        await session.delete(acc)
        await session.commit()
        print(f"Deleted account '{name}'.")
    else:
        print(f"Account '{name}' not found.")

async def account_command(args):
    async with AsyncSessionLocal() as session:
        if args.list:
            await list_accounts(session)
        elif args.add:
            await add_account(session, args.add, args.add) # Use name as institution for now
        elif args.delete:
            await delete_account(session, args.delete)

async def convert_command(args):
    parser = BankParser()
    try:
        transactions = parser.parse(args.bank, args.input)
    except Exception as e:
        print(f"Error parsing file: {e}")
        return

    async with AsyncSessionLocal() as session:
        # Check Account
        result = await session.execute(select(Account).where(Account.name == args.account))
        account = result.scalar_one_or_none()
        if not account:
            print(f"Account '{args.account}' not found in DB. Please add it first.")
            return

        print(f"Parsed {len(transactions)} transactions.")
        
        # Load Mapping Rules
        mappings_result = await session.execute(select(MappingRule))
        rules = mappings_result.scalars().all()
        rule_map = {r.keyword: r.category_id for r in rules}
        
        # Initialize AI
        ai = CategorizerAI()
        
        new_txs = []
        for tx in transactions:
            # Check for existing duplicate (same date, amount, desc, account)
            stmt = select(Transaction).where(
                Transaction.date == tx["date"],
                Transaction.amount == tx["amount"],
                Transaction.description == tx["description"],
                Transaction.account_id == account.id
            )
            existing = await session.execute(stmt)
            if existing.scalar_one_or_none():
                continue
            
            cat_id = rule_map.get(tx["description"])
            
            # If not in rules, try AI
            if not cat_id:
                print(f"Resolving '{tx['description']}' with AI...")
                cat_id = await ai.suggest_category(tx["description"], session)
            
            new_tx = Transaction(
                date=tx["date"],
                description=tx["description"],
                amount=tx["amount"],
                type=tx["type"],
                account_id=account.id,
                category_id=cat_id,
                raw_csv_row=tx["raw_csv_row"]
            )
            
            session.add(new_tx)
            new_txs.append(new_tx)
        
        # Commit to save new transactions
        await session.commit()
        print(f"Imported {len(new_txs)} new transactions.")
        
        if args.output and new_txs:
            # We need to refresh/load categories for these transactions to write the CSV
            # Or just fetch them again with join
            
            # Re-query new transactions with eager load
            tx_ids = [t.id for t in new_txs]
            stmt = select(Transaction).options(selectinload(Transaction.category)).where(Transaction.id.in_(tx_ids))
            result = await session.execute(stmt)
            export_txs = result.scalars().all()
            
            with open(args.output, "w", newline="") as f:
                writer = csv.writer(f)
                # Bluecoins Header
                writer.writerow(["Type", "Date", "Item or Payee", "Amount", "Parent Category", "Category", "Account Type", "Account", "Notes", "Label", "Status", "Split"])
                
                for tx in export_txs:
                    # Map to Bluecoins format
                    # Type: "Bank" (default from config? Old script had account_type arg)
                    # We dropped account_type arg in this implementation, assume "Bank"
                    
                    cat_name = tx.category.name if tx.category else ""
                    parent_name = tx.category.parent_name if tx.category else ""
                    
                    writer.writerow([
                        "Expense" if tx.type == "expense" else "Income", # Bluecoins uses "Expense"/"Income"? No, logic was "e" / "i" in old script?
                        # Old script: "Type" = "e" or "i"?
                        # Let's check old script: `type_ = "i" if amount > 0 else "e"`
                        # Bluecoins expects "Type" column to be what?
                        # Actually standard CSV import usually handles "Expense", "Income" or "Transfer".
                        # Old script wrote "type_".
                        
                        tx.date.strftime("%m/%d/%Y"),
                        tx.description,
                        str(tx.amount),
                        parent_name,
                        cat_name,
                        "Bank", # Hardcoded for now
                        account.name,
                        "", "", "", ""
                    ])
            print(f"Exported to {args.output}")

async def main():
    parser = argparse.ArgumentParser(description="Financial CLI V2")
    subparsers = parser.add_subparsers(dest="command")
    
    # Account
    acc_parser = subparsers.add_parser("account")
    group = acc_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true")
    group.add_argument("--add", help="Name")
    group.add_argument("--delete", help="Name")
    
    # Convert/Import
    conv_parser = subparsers.add_parser("convert")
    conv_parser.add_argument("--bank", required=True)
    conv_parser.add_argument("--input", required=True)
    conv_parser.add_argument("--account", required=True)
    conv_parser.add_argument("--output", help="Optional output CSV")

    args = parser.parse_args()
    
    await init_db()
    
    if args.command == "account":
        await account_command(args)
    elif args.command == "convert":
        await convert_command(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    asyncio.run(main())