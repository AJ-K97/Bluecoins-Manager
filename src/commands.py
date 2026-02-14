from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from src.database import Account, Category, MappingRule, Transaction, AsyncSessionLocal, AIMemory
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

async def get_all_categories(session):
    result = await session.execute(select(Category).order_by(Category.name))
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
        confidence = 1.0 if cat_id else 0.0
        reasoning = "Matched via Mapping Rule" if cat_id else None
        tx_type = tx["type"] # Default from parser
        
        # AI Suggestion
        if not cat_id:
            print(f"Resolving '{tx['description']}' with AI...")
            cat_id, confidence, reasoning, suggested_type = await ai.suggest_category(tx["description"], session)
            if suggested_type:
                tx_type = suggested_type
        
        new_tx = Transaction(
            date=tx["date"],
            description=tx["description"],
            amount=tx["amount"],
            type=tx_type,
            account_id=account.id,
            category_id=cat_id,
            confidence_score=confidence,
            # ai_reasoning=reasoning, # DEPRECATED
            raw_csv_row=tx["raw_csv_row"],
            is_verified=False # Always false initially, require review
        )
        session.add(new_tx)
        await session.flush() # Get ID
        
        # Create Memory Entry
        words = tx["description"].split()
        pattern_key = words[0].upper() if words else "UNKNOWN"
        
        memory = AIMemory(
            transaction_id=new_tx.id,
            pattern_key=pattern_key,
            ai_suggested_category_id=cat_id,
            ai_reasoning=reasoning
        )
        session.add(memory)
        new_txs.append(new_tx)
    
    await session.commit()
    
    result_msg = f"Imported {len(new_txs)} transactions. Skipped {skipped} duplicates."
    
    # Export if requested
    if output_path and new_txs:
        # Re-fetch with category for export
        tx_ids = [t.id for t in new_txs]
        stmt = select(Transaction).options(selectinload(Transaction.category), selectinload(Transaction.account)).where(Transaction.id.in_(tx_ids))
        result = await session.execute(stmt)
        export_txs = result.scalars().all()
        
        success, msg = export_to_bluecoins_csv(export_txs, output_path)
        result_msg += f"\n{msg}"
        
    return True, result_msg, new_txs

async def get_transactions(session, account_id=None, start_date=None, end_date=None):
    stmt = select(Transaction).options(
        selectinload(Transaction.category),
        selectinload(Transaction.account),
        selectinload(Transaction.memory_entries)
    ).order_by(Transaction.date.desc())
    
    if account_id:
        stmt = stmt.where(Transaction.account_id == account_id)
    if start_date:
        stmt = stmt.where(Transaction.date >= start_date)
    if end_date:
        stmt = stmt.where(Transaction.date <= end_date)
        
    result = await session.execute(stmt)
    return result.scalars().all()

async def update_transaction_category(session, tx_id, category_id):
    # Fetch existing transaction and memory
    stmt = select(Transaction).where(Transaction.id == tx_id)
    result = await session.execute(stmt)
    tx = result.scalar_one_or_none()
    
    if not tx:
        return False, "Transaction not found."

    # Fetch Memory
    mem_stmt = select(AIMemory).where(AIMemory.transaction_id == tx_id).order_by(AIMemory.created_at.desc())
    mem_res = await session.execute(mem_stmt)
    memory = mem_res.scalars().first()
    
    # Check for change
    old_cat_id = tx.category_id
    
    # Update Transaction
    tx.category_id = category_id
    tx.is_verified = True
    session.add(tx)
    
    # Handle Reflection if changed
    if old_cat_id != category_id:
        # Get names
        old_cat_name = "None"
        if old_cat_id:
             r = await session.execute(select(Category).where(Category.id == old_cat_id))
             c = r.scalar_one_or_none()
             if c: old_cat_name = c.name
             
        new_cat_name = "None"
        if category_id:
             r = await session.execute(select(Category).where(Category.id == category_id))
             c = r.scalar_one_or_none()
             if c: new_cat_name = c.name
        
        # Get Reasoning from memory
        prev_reasoning = memory.ai_reasoning if memory else "Unknown"
        
        # Generate Reflection
        ai = CategorizerAI() # Re-init? Or pass in? It's fine to init here for now, or cleaner to pass.
                             # But commands.py functions are called by TUI.
        reflection = await ai.generate_reflection(tx.description, old_cat_name, new_cat_name, prev_reasoning)
        
        # Update Memory
        if memory:
            memory.user_selected_category_id = category_id
            memory.reflection = reflection
            session.add(memory)
        else:
            # Create new if missing
            words = tx.description.split()
            pattern_key = words[0].upper() if words else "UNKNOWN"
            new_mem = AIMemory(
                 transaction_id=tx.id,
                 pattern_key=pattern_key,
                 user_selected_category_id=category_id,
                 reflection=reflection
            )
            session.add(new_mem)
    
    else:
        # Just verification
        if memory:
            memory.user_selected_category_id = category_id
            session.add(memory)
            
    await session.commit()
    return True, "Transaction category updated and verified."

async def update_transaction_amount(session, tx_id, new_amount):
    stmt = update(Transaction).where(Transaction.id == tx_id).values(amount=new_amount, is_verified=True)
    await session.execute(stmt)
    await session.commit()
    return True, "Transaction amount updated and verified."

async def mark_transaction_verified(session, tx_id):
    # Fetch existing transaction and memory
    stmt = select(Transaction).where(Transaction.id == tx_id)
    result = await session.execute(stmt)
    tx = result.scalar_one_or_none()
    
    if tx:
        tx.is_verified = True
        session.add(tx)
        
        # Update Memory
        mem_stmt = select(AIMemory).where(AIMemory.transaction_id == tx_id).order_by(AIMemory.created_at.desc())
        mem_res = await session.execute(mem_stmt)
        memory = mem_res.scalars().first()
        
        if memory:
            memory.user_selected_category_id = tx.category_id
            session.add(memory)
            
    await session.commit()
    return True, "Transaction verified."

async def delete_transaction(session, tx_id):
    stmt = delete(Transaction).where(Transaction.id == tx_id)
    await session.execute(stmt)
    await session.commit()
    return True, "Transaction deleted."

def export_to_bluecoins_csv(transactions, output_path):
    try:
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Type", "Date", "Item or Payee", "Amount", "Parent Category", "Category", "Account Type", "Account", "Notes", "Label", "Status", "Split"])
            
            for tx in transactions:
                cat_name = tx.category.name if tx.category else ""
                parent_name = tx.category.parent_name if tx.category else ""
                
                # Account name might not be loaded if we didn't join Account? 
                # Transaction.account_id is there, but we need Account name.
                # Ideally get_transactions should load Account too.
                # But for `process_import`, we knew it from `account` object.
                # For general export, we need to ensure account is loaded or passed.
                
                # Let's rely on lazy load or ensure eager load in query.
                # But `process_import` passed `new_txs` which are attached to session? 
                # Wait, `get_transactions` does not load Account.
                pass
                
                # We need account name. 
                # Let's assume transactions have account relationship loaded if needed.
                # Or we fetch it.
                
                # Actually, `Transaction` model should have `account` relationship.
                # Let's check `src/database.py`... 
                # Assuming it does.
                
                acc_name = tx.account.name if tx.account else "Unknown"

                writer.writerow([
                    "Expense" if tx.type == "expense" else "Income",
                    tx.date.strftime("%m/%d/%Y"),
                    tx.description,
                    str(tx.amount),
                    parent_name,
                    cat_name,
                    "Bank",
                    acc_name,
                    "", "", "", ""
                ])
        return True, f"Exported {len(transactions)} transactions to {output_path}"
    except Exception as e:
        return False, f"Export failed: {e}"
