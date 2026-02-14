import csv
import asyncio
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from src.database import Account, Category, MappingRule, Transaction, AsyncSessionLocal
from src.parser import BankParser
from src.ai import CategorizerAI

async def list_accounts(session):
    result = await session.execute(select(Account))
    accounts = result.scalars().all()
    return accounts

async def add_account(session, name, institution):
    try:
        session.add(Account(name=name, institution=institution))
        await session.commit()
        return True, f"Added account '{name}'."
    except IntegrityError:
        await session.rollback()
        return False, f"Account '{name}' already exists."

async def delete_account(session, name):
    result = await session.execute(select(Account).where(Account.name == name))
    acc = result.scalar_one_or_none()
    if acc:
        await session.delete(acc)
        await session.commit()
        return True, f"Deleted account '{name}'."
    else:
        return False, f"Account '{name}' not found."

async def get_all_accounts(session):
    result = await session.execute(select(Account))
    return result.scalars().all()

async def process_import(session, bank_name, file_path, account_name, output_path=None):
    # Check Account
    result = await session.execute(select(Account).where(Account.name == account_name))
    account = result.scalar_one_or_none()
    if not account:
        return False, f"Account '{account_name}' not found."

    # Parse
    parser = BankParser()
    try:
        transactions = parser.parse(bank_name, file_path)
    except Exception as e:
        return False, f"Error parsing file: {e}"

    # Load Mapping Rules
    mappings_result = await session.execute(select(MappingRule))
    rules = mappings_result.scalars().all()
    rule_map = {r.keyword: r.category_id for r in rules}
    
    # Initialize AI
    ai = CategorizerAI()
    
    new_txs = []
    skipped = 0
    
    for tx in transactions:
        # Check duplicate
        stmt = select(Transaction).where(
            Transaction.date == tx["date"],
            Transaction.amount == tx["amount"],
            Transaction.description == tx["description"],
            Transaction.account_id == account.id
        )
        existing = await session.execute(stmt)
        if existing.scalar_one_or_none():
            skipped += 1
            continue
        
        cat_id = rule_map.get(tx["description"])
        
        # AI Suggestion
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
    
    await session.commit()
    
    result_msg = f"Imported {len(new_txs)} transactions. Skipped {skipped} duplicates."
    
    # Export if requested
    if output_path and new_txs:
        tx_ids = [t.id for t in new_txs]
        stmt = select(Transaction).options(selectinload(Transaction.category)).where(Transaction.id.in_(tx_ids))
        result = await session.execute(stmt)
        export_txs = result.scalars().all()
        
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Type", "Date", "Item or Payee", "Amount", "Parent Category", "Category", "Account Type", "Account", "Notes", "Label", "Status", "Split"])
            
            for tx in export_txs:
                cat_name = tx.category.name if tx.category else ""
                parent_name = tx.category.parent_name if tx.category else ""
                
                writer.writerow([
                    "Expense" if tx.type == "expense" else "Income",
                    tx.date.strftime("%m/%d/%Y"),
                    tx.description,
                    str(tx.amount),
                    parent_name,
                    cat_name,
                    "Bank",
                    account.name,
                    "", "", "", ""
                ])
        result_msg += f"\nExported to {output_path}"
        
    return True, result_msg
