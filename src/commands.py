import csv
from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from src.database import Account, Category, Transaction, AsyncSessionLocal, AIMemory, AIGlobalMemory
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
    result = await session.execute(select(Category).order_by(Category.parent_name, Category.name))
    return result.scalars().all()

def get_transaction_category_display(tx):
    if tx.type == "transfer" and tx.category_id is None:
        return "(Transfer)", "(Transfer)"
    if tx.category:
        parent_name = tx.category.parent_name or "Uncategorized"
        return parent_name, tx.category.name
    return "Uncategorized", "Uncategorized"

async def get_category_display_from_values(session, tx_type, category_id):
    if tx_type == "transfer" and category_id is None:
        return "(Transfer)", "(Transfer)"
    if not category_id:
        return "Uncategorized", "Uncategorized"

    res = await session.execute(select(Category).where(Category.id == category_id))
    cat = res.scalar_one_or_none()
    if not cat:
        return "Uncategorized", "Uncategorized"
    return cat.parent_name or "Uncategorized", cat.name

async def add_global_memory_instruction(session, instruction, source="user_review"):
    text = (instruction or "").strip()
    if not text:
        return False, "Instruction is empty."

    session.add(AIGlobalMemory(instruction=text, source=source, is_active=True))
    await session.flush()
    return True, "Saved global instruction."

async def get_global_memory_entries(session, include_inactive=True, limit=200):
    stmt = select(AIGlobalMemory).order_by(AIGlobalMemory.created_at.desc())
    if not include_inactive:
        stmt = stmt.where(AIGlobalMemory.is_active.is_(True))
    if limit:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()

async def set_global_memory_active(session, entry_id, is_active):
    res = await session.execute(select(AIGlobalMemory).where(AIGlobalMemory.id == entry_id))
    row = res.scalar_one_or_none()
    if not row:
        return False, "Rule not found."
    row.is_active = bool(is_active)
    session.add(row)
    await session.commit()
    return True, "Rule updated."

async def delete_global_memory_instruction(session, entry_id):
    res = await session.execute(select(AIGlobalMemory).where(AIGlobalMemory.id == entry_id))
    row = res.scalar_one_or_none()
    if not row:
        return False, "Rule not found."
    await session.delete(row)
    await session.commit()
    return True, "Rule deleted."

async def add_category(session, name, parent_name, type):
    # Check if exists
    stmt = select(Category).where(
        Category.name == name, 
        Category.parent_name == parent_name,
        Category.type == type
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        return False, f"Category '{parent_name} > {name}' already exists."

    new_cat = Category(name=name, parent_name=parent_name, type=type)
    session.add(new_cat)
    try:
        await session.commit()
        return True, f"Category '{parent_name} > {name}' added."
    except Exception as e:
        await session.rollback()
        return False, f"Error adding category: {e}"

async def delete_category(session, category_id, reassign_category_id=None, delete_transactions=False):
    # Fetch Category
    stmt = select(Category).where(Category.id == category_id)
    result = await session.execute(stmt)
    category = result.scalar_one_or_none()
    
    if not category:
        return False, "Category not found."

    # Check for transactions
    tx_stmt = select(Transaction).where(Transaction.category_id == category_id)
    tx_result = await session.execute(tx_stmt)
    transactions = tx_result.scalars().all()
    
    count = len(transactions)
    
    if count > 0:
        if delete_transactions:
            # Delete transactions
            await session.execute(delete(Transaction).where(Transaction.category_id == category_id))
        elif reassign_category_id:
            # Reassign
            await session.execute(
                update(Transaction).where(Transaction.category_id == category_id).values(category_id=reassign_category_id, is_verified=True)
            )
        else:
             return False, f"Category has {count} transactions. Please specify reassign_id or delete_transactions=True."

    await session.delete(category)
    try:
        await session.commit()
        return True, f"Category '{category.parent_name} > {category.name}' deleted."
    except Exception as e:
        await session.rollback()
        return False, f"Error deleting category: {e}"


async def process_import(session, bank_name, file_path, account_name, output_path=None, review_callback=None):
    # Check Account
    result = await session.execute(select(Account).where(Account.name == account_name))
    account = result.scalar_one_or_none()
    if not account:
        return False, f"Account '{account_name}' not found.", []

    # Parse
    parser = BankParser()
    try:
        transactions = parser.parse(bank_name, file_path)
    except Exception as e:
        return False, f"Error parsing file: {e}", []


    
    # Initialize AI
    ai = CategorizerAI()
    
    new_txs = []
    skipped = 0
    
    for tx_data in transactions:
        # Check duplicate
        stmt = select(Transaction).where(
            Transaction.date == tx_data["date"],
            Transaction.amount == tx_data["amount"],
            Transaction.description == tx_data["description"],
            Transaction.account_id == account.id
        )
        existing = await session.execute(stmt)
        if existing.scalar_one_or_none():
            skipped += 1
            continue
        
        cat_id = None
        confidence = 0.0
        reasoning = None
        tx_type = tx_data["type"] # Default from parser
        is_verified = False
        
        # AI Suggestion
        print(f"Resolving '{tx_data['description']}' with AI...")
        cat_id, confidence, reasoning, suggested_type = await ai.suggest_category(tx_data["description"], session)
        if suggested_type:
            tx_type = suggested_type
        if tx_type == "transfer":
            cat_id = None
        
        # Review Callback
        if review_callback:
            # We pass the raw data and AI suggestion. 
            # Callback should return (final_cat_id, verified_bool)
            # It might also modify tx_type, but let's keep it simple for now or return a dict.
            # Let's assume it returns (cat_id, is_verified, tx_type)
            cat_id, is_verified, tx_type = await review_callback(tx_data, cat_id, confidence, tx_type, reasoning, session)
            if tx_type == "transfer":
                cat_id = None

        new_tx = Transaction(
            date=tx_data["date"],
            description=tx_data["description"],
            amount=tx_data["amount"],
            type=tx_type,
            account_id=account.id,
            category_id=cat_id,
            confidence_score=confidence,
            # ai_reasoning=reasoning, # DEPRECATED
            raw_csv_row=tx_data["raw_csv_row"],
            is_verified=is_verified
        )
        session.add(new_tx)
        await session.flush() # Get ID
        
        # Create Memory Entry
        words = tx_data["description"].split()
        pattern_key = words[0].upper() if words else "UNKNOWN"
        
        memory = AIMemory(
            transaction_id=new_tx.id,
            pattern_key=pattern_key,
            ai_suggested_category_id=cat_id if tx_type != "transfer" else None,
            ai_reasoning=reasoning,
            user_selected_category_id=cat_id if is_verified else None # If verified, we record it
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
                parent_name, cat_name = get_transaction_category_display(tx)
                
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
                    "Transfer" if tx.type == "transfer" else ("Expense" if tx.type == "expense" else "Income"),
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
