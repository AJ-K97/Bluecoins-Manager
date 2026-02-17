import csv
import json
import os
from datetime import datetime
from collections import Counter
from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from src.database import (
    Account,
    Category,
    Transaction,
    AsyncSessionLocal,
    AIMemory,
    AIGlobalMemory,
    AICategoryUnderstanding,
    LLMKnowledgeChunk,
    LLMSkill,
    LLMFineTuneExample,
    Base,
    engine,
)
from src.parser import BankParser
from src.ai import CategorizerAI
from src.patterns import extract_pattern_key
from src.policy import (
    AUTO_APPROVE_MIN,
    POLICY_VERSION,
    evaluate_decision_policy,
)

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

async def update_account(session, current_name, new_name=None, new_institution=None):
    result = await session.execute(select(Account).where(Account.name == current_name))
    acc = result.scalar_one_or_none()
    if not acc:
        return False, f"Account '{current_name}' not found.", 0

    target_name = (new_name or "").strip() or acc.name
    target_institution = (new_institution or "").strip() or acc.institution

    if target_name == acc.name and target_institution == acc.institution:
        return False, "No account changes provided.", 0

    if target_name != acc.name:
        duplicate = await session.execute(select(Account).where(Account.name == target_name))
        if duplicate.scalar_one_or_none():
            return False, f"Account '{target_name}' already exists.", 0

    linked_tx_count = await session.scalar(
        select(func.count(Transaction.id)).where(Transaction.account_id == acc.id)
    )
    linked_tx_count = int(linked_tx_count or 0)

    acc.name = target_name
    acc.institution = target_institution
    session.add(acc)

    # Force-write linked transactions so downstream consumers that depend on
    # account-linked rows are updated in the same DB transaction.
    if linked_tx_count:
        await session.execute(
            update(Transaction)
            .where(Transaction.account_id == acc.id)
            .values(account_id=acc.id)
        )

    try:
        await session.commit()
        return True, f"Updated account '{current_name}' to '{target_name}'.", linked_tx_count
    except IntegrityError:
        await session.rollback()
        return False, f"Account '{target_name}' already exists.", 0

async def get_all_accounts(session):
    result = await session.execute(select(Account))
    return result.scalars().all()

async def get_all_categories(session):
    result = await session.execute(select(Category).order_by(Category.parent_name, Category.name))
    return result.scalars().all()


def format_category_label(parent_name, cat_name, cat_type):
    parent = parent_name or "Uncategorized"
    name = cat_name or "Uncategorized"
    ctype = (cat_type or "unknown").lower()
    return f"{parent} > {name} [{ctype}]"


def format_category_obj_label(category):
    if not category:
        return "Uncategorized > Uncategorized [unknown]"
    return format_category_label(category.parent_name, category.name, category.type)


async def rebuild_category_understanding(session, category_ids=None):
    """
    Build/update stored category intent profiles from verified transactions.
    """
    stmt = select(Category)
    if category_ids:
        stmt = stmt.where(Category.id.in_(list(set(category_ids))))
    cat_res = await session.execute(stmt)
    categories = cat_res.scalars().all()

    updates = 0
    for cat in categories:
        tx_stmt = (
            select(Transaction)
            .where(
                Transaction.category_id == cat.id,
                Transaction.is_verified.is_(True),
            )
            .order_by(Transaction.date.desc())
            .limit(40)
        )
        tx_res = await session.execute(tx_stmt)
        txs = tx_res.scalars().all()

        pattern_counter = Counter()
        sample_descriptions = []
        for tx in txs:
            key = extract_pattern_key(tx.description)
            if key:
                pattern_counter[key] += 1
            if tx.description:
                sample_descriptions.append(tx.description)

        top_patterns = [k for k, _ in pattern_counter.most_common(8)]
        samples = sample_descriptions[:8]
        verified_count = len(txs)

        understanding = (
            f"Category intent profile for {format_category_obj_label(cat)}. "
            f"Use this when merchant/payee intent matches. "
            f"Verified examples: {verified_count}. "
            f"Common merchant patterns: {', '.join(top_patterns) if top_patterns else 'none yet'}. "
            f"Treat this as a strict hint for this specific category and type ({cat.type})."
        )

        existing_res = await session.execute(
            select(AICategoryUnderstanding).where(AICategoryUnderstanding.category_id == cat.id)
        )
        row = existing_res.scalar_one_or_none()
        payload = json.dumps({"samples": samples, "patterns": top_patterns}, ensure_ascii=True)
        if row:
            row.understanding = understanding
            row.sample_transactions_json = payload
            session.add(row)
        else:
            session.add(
                AICategoryUnderstanding(
                    category_id=cat.id,
                    understanding=understanding,
                    sample_transactions_json=payload,
                )
            )
        updates += 1

    return updates

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

async def reset_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return True, "Database reset complete."


RESETTABLE_MODELS = {
    "accounts": Account,
    "categories": Category,
    "transactions": Transaction,
    "ai_memory": AIMemory,
    "ai_global_memory": AIGlobalMemory,
    "ai_category_understanding": AICategoryUnderstanding,
    "llm_knowledge_chunks": LLMKnowledgeChunk,
    "llm_skills": LLMSkill,
    "llm_finetune_examples": LLMFineTuneExample,
}

# parent -> hard dependent children (FK/consistency must be addressed first if non-empty)
RESET_HARD_DEPENDENCIES = {
    "accounts": ["transactions"],
    "categories": ["transactions", "ai_category_understanding"],
    "transactions": ["ai_memory", "llm_finetune_examples"],
}

# delete order from most dependent to least dependent
RESET_DELETE_ORDER = [
    "ai_memory",
    "llm_finetune_examples",
    "llm_knowledge_chunks",
    "ai_category_understanding",
    "transactions",
    "accounts",
    "categories",
    "ai_global_memory",
    "llm_skills",
]


def get_resettable_table_names():
    return list(RESETTABLE_MODELS.keys())


async def get_table_row_counts(session, table_names=None):
    target = table_names or get_resettable_table_names()
    counts = {}
    for name in target:
        model = RESETTABLE_MODELS.get(name)
        if not model:
            continue
        rows = await session.execute(select(func.count()).select_from(model))
        counts[name] = int(rows.scalar_one() or 0)
    return counts


async def reset_selected_tables(session, table_names):
    selected = list(dict.fromkeys([(t or "").strip().lower() for t in table_names if (t or "").strip()]))
    if not selected:
        return False, "No tables selected."

    invalid = [t for t in selected if t not in RESETTABLE_MODELS]
    if invalid:
        valid = ", ".join(get_resettable_table_names())
        return False, f"Unknown table(s): {', '.join(invalid)}. Valid options: {valid}"

    counts = await get_table_row_counts(session)
    blockers = []
    for parent, dependents in RESET_HARD_DEPENDENCIES.items():
        if parent not in selected:
            continue
        for dep in dependents:
            if dep in selected:
                continue
            dep_count = counts.get(dep, 0)
            if dep_count > 0:
                blockers.append(
                    f"Cannot reset '{parent}' without '{dep}' because '{dep}' has {dep_count} rows dependent on '{parent}'."
                )

    if blockers:
        return False, "\n".join(blockers)

    for table_name in RESET_DELETE_ORDER:
        if table_name not in selected:
            continue
        await session.execute(delete(RESETTABLE_MODELS[table_name]))
    await session.commit()

    note = ""
    if "transactions" in selected and "llm_knowledge_chunks" not in selected:
        note = (
            "\nNote: 'transactions' was reset but 'llm_knowledge_chunks' was not. "
            "Run `python3 main.py llm reindex` or reset 'llm_knowledge_chunks' as well to avoid stale retrieval context."
        )

    return True, f"Reset completed for tables: {', '.join(selected)}.{note}"

async def seed_reference_data(session, accounts_path="data/accounts.json", categories_path="data/categories.json"):
    accounts_added = 0
    categories_added = 0

    if os.path.exists(accounts_path):
        with open(accounts_path, "r", encoding="utf-8") as f:
            accounts_data = json.load(f)
        for account_name in accounts_data:
            name = str(account_name).strip()
            if not name:
                continue
            res = await session.execute(select(Account).where(Account.name == name))
            if not res.scalar_one_or_none():
                session.add(Account(name=name, institution=name))
                accounts_added += 1

    if os.path.exists(categories_path):
        with open(categories_path, "r", encoding="utf-8") as f:
            categories_data = json.load(f)

        for _template_name, types in categories_data.items():
            for type_name, parents in types.items():
                for parent_name, children in parents.items():
                    for child_name in children:
                        child = str(child_name).strip()
                        parent = str(parent_name).strip()
                        tx_type = str(type_name).strip()
                        if not child or not parent or not tx_type:
                            continue

                        stmt = select(Category).where(
                            Category.name == child,
                            Category.parent_name == parent,
                            Category.type == tx_type
                        )
                        existing = await session.execute(stmt)
                        if existing.scalar_one_or_none():
                            continue
                        session.add(Category(name=child, parent_name=parent, type=tx_type))
                        categories_added += 1

    await session.commit()
    return True, f"Seed complete. Added {accounts_added} accounts and {categories_added} categories."

async def add_category(session, name, parent_name, type):
    # Check if exists
    stmt = select(Category).where(
        Category.name == name, 
        Category.parent_name == parent_name,
        Category.type == type
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        return False, f"Category '{format_category_label(parent_name, name, type)}' already exists."

    new_cat = Category(name=name, parent_name=parent_name, type=type)
    session.add(new_cat)
    try:
        await session.flush()
        await rebuild_category_understanding(session, category_ids=[new_cat.id])
        await session.commit()
        return True, f"Category '{format_category_label(parent_name, name, type)}' added."
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

    mem_res = await session.execute(
        select(AICategoryUnderstanding).where(AICategoryUnderstanding.category_id == category_id)
    )
    mem_row = mem_res.scalar_one_or_none()
    if mem_row:
        await session.delete(mem_row)

    await session.delete(category)
    try:
        await session.commit()
        return True, f"Category '{format_category_obj_label(category)}' deleted."
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


    # Keep category intent profiles warm for AI prompting.
    await rebuild_category_understanding(session)
    await session.commit()

    # Initialize AI
    ai = CategorizerAI()
    
    new_txs = []
    skipped = 0
    verified_categories_touched = set()
    
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
        cat_id, confidence, reasoning, suggested_type = await ai.suggest_category(
            tx_data["description"],
            session,
            expected_type=tx_data["type"] if tx_data["type"] in {"expense", "income"} else None,
        )
        if suggested_type:
            tx_type = suggested_type
        if tx_type == "transfer":
            cat_id = None
        ai_suggested_cat_id = cat_id if tx_type != "transfer" else None
        ai_suggested_reasoning = reasoning
        
        conflict_flags = []
        if tx_type != "transfer" and cat_id is None:
            conflict_flags.append("invalid_category_id")
        if tx_type == "transfer" and cat_id is not None:
            conflict_flags.append("transfer_ambiguous")
        if tx_type != "transfer" and cat_id is not None:
            cat_match = await session.execute(select(Category).where(Category.id == cat_id))
            selected_cat = cat_match.scalar_one_or_none()
            if not selected_cat:
                conflict_flags.append("invalid_category_id")
            elif selected_cat.type != tx_type:
                conflict_flags.append("type_category_mismatch")

        decision = evaluate_decision_policy(confidence, conflict_flags)

        # Review Callback
        if review_callback:
            # We pass the raw data and AI suggestion. 
            # Callback returns final reviewed values:
            # (cat_id, is_verified, tx_type, confidence, reasoning)
            cat_id, is_verified, tx_type, confidence, reasoning = await review_callback(
                tx_data, cat_id, confidence, tx_type, reasoning, session
            )
            if tx_type == "transfer":
                cat_id = None
        else:
            is_verified = decision.can_auto_verify

        final_flags = []
        if tx_type != "transfer" and cat_id is None:
            final_flags.append("invalid_category_id")
        if tx_type == "transfer" and cat_id is not None:
            final_flags.append("transfer_ambiguous")
        if tx_type != "transfer" and cat_id is not None:
            cat_match = await session.execute(select(Category).where(Category.id == cat_id))
            selected_cat = cat_match.scalar_one_or_none()
            if not selected_cat:
                final_flags.append("invalid_category_id")
            elif selected_cat.type != tx_type:
                final_flags.append("type_category_mismatch")

        decision = evaluate_decision_policy(confidence, final_flags)

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
            is_verified=is_verified,
            decision_state=decision.state,
            decision_reason=decision.reason,
            review_priority=100 if is_verified else decision.priority,
            review_bucket=decision.bucket,
        )
        session.add(new_tx)
        await session.flush() # Get ID
        if is_verified and cat_id:
            verified_categories_touched.add(cat_id)
        
        # Create Memory Entry
        pattern_key = extract_pattern_key(tx_data["description"])
        
        memory = AIMemory(
            transaction_id=new_tx.id,
            pattern_key=pattern_key,
            ai_suggested_category_id=ai_suggested_cat_id,
            ai_reasoning=reasoning or ai_suggested_reasoning,
            user_selected_category_id=cat_id if is_verified else None, # If verified, we record it
            policy_version=POLICY_VERSION,
            threshold_used=AUTO_APPROVE_MIN,
            conflict_flags_json=json.dumps(final_flags, ensure_ascii=True),
        )
        session.add(memory)
        new_txs.append(new_tx)
    
    await session.commit()

    if verified_categories_touched:
        await rebuild_category_understanding(session, category_ids=list(verified_categories_touched))
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


async def get_queue_transactions(
    session,
    states=None,
    bucket=None,
    account_id=None,
    limit=100,
):
    target_states = states or ["needs_review", "force_review"]
    stmt = select(Transaction).options(
        selectinload(Transaction.category),
        selectinload(Transaction.account),
        selectinload(Transaction.memory_entries),
    ).where(
        Transaction.is_verified.is_(False),
        Transaction.decision_state.in_(target_states),
    ).order_by(
        Transaction.review_priority.asc().nullslast(),
        Transaction.date.desc(),
    )

    if bucket:
        stmt = stmt.where(Transaction.review_bucket == bucket)
    if account_id:
        stmt = stmt.where(Transaction.account_id == account_id)
    if limit:
        stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    return result.scalars().all()


async def get_queue_stats(session):
    stmt = (
        select(
            Transaction.decision_state,
            Transaction.review_bucket,
            func.count().label("count"),
        )
        .where(Transaction.is_verified.is_(False))
        .group_by(Transaction.decision_state, Transaction.review_bucket)
        .order_by(Transaction.decision_state.asc(), Transaction.review_bucket.asc())
    )
    result = await session.execute(stmt)
    return result.all()


async def recalc_queue_decisions(session, since=None):
    stmt = select(Transaction).options(selectinload(Transaction.category))
    if since:
        stmt = stmt.where(Transaction.date >= since)
    result = await session.execute(stmt)
    txs = result.scalars().all()

    updated = 0
    for tx in txs:
        flags = []
        if tx.type != "transfer" and tx.category_id is None:
            flags.append("invalid_category_id")
        if tx.category and tx.type != tx.category.type:
            flags.append("type_category_mismatch")

        decision = evaluate_decision_policy(tx.confidence_score or 0.0, flags)
        tx.decision_state = decision.state
        tx.review_bucket = decision.bucket
        tx.review_priority = decision.priority
        tx.decision_reason = decision.reason
        if tx.is_verified:
            tx.review_priority = 100
        session.add(tx)
        updated += 1

    await session.commit()
    return updated

async def update_transaction_category(session, tx_id, category_id=None, set_transfer=False):
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
    old_type = tx.type
    
    selected_category = None
    if set_transfer:
        category_id = None
    elif category_id:
        cat_stmt = select(Category).where(Category.id == category_id)
        cat_res = await session.execute(cat_stmt)
        selected_category = cat_res.scalar_one_or_none()
        if not selected_category:
            return False, "Selected category not found."
    else:
        return False, "No category selected."

    # Update Transaction
    tx.category_id = category_id
    if set_transfer:
        tx.type = "transfer"
    elif selected_category:
        tx.type = selected_category.type
    tx.is_verified = True
    tx.review_priority = 100
    if not tx.decision_state:
        tx.decision_state = "needs_review"
    session.add(tx)
    
    # Handle Reflection if changed
    if old_cat_id != category_id:
        # Get names
        old_cat_name = "None"
        if old_type == "transfer" and old_cat_id is None:
            old_cat_name = "(Transfer) > (Transfer) [transfer]"
        elif old_cat_id:
            r = await session.execute(select(Category).where(Category.id == old_cat_id))
            c = r.scalar_one_or_none()
            if c:
                old_cat_name = format_category_obj_label(c)
             
        new_cat_name = "None"
        if set_transfer:
            new_cat_name = "(Transfer) > (Transfer) [transfer]"
        elif category_id:
            r = await session.execute(select(Category).where(Category.id == category_id))
            c = r.scalar_one_or_none()
            if c:
                new_cat_name = format_category_obj_label(c)
        
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
            pattern_key = extract_pattern_key(tx.description)
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
            
    touched_categories = [c for c in [old_cat_id, category_id] if c]
    if touched_categories:
        await rebuild_category_understanding(session, category_ids=touched_categories)

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
        tx.review_priority = 100
        if not tx.decision_state:
            tx.decision_state = "needs_review"
        session.add(tx)
        
        # Update Memory
        mem_stmt = select(AIMemory).where(AIMemory.transaction_id == tx_id).order_by(AIMemory.created_at.desc())
        mem_res = await session.execute(mem_stmt)
        memory = mem_res.scalars().first()
        
        if memory:
            memory.user_selected_category_id = tx.category_id
            session.add(memory)

        if tx.category_id:
            await rebuild_category_understanding(session, category_ids=[tx.category_id])

    await session.commit()
    return True, "Transaction verified."

async def delete_transaction(session, tx_id):
    stmt = delete(Transaction).where(Transaction.id == tx_id)
    await session.execute(stmt)
    await session.commit()
    return True, "Transaction deleted."

async def add_transaction(session, date, amount, description, account_name, category_id=None, tx_type=None, confidence=None, decision_reason=None, is_verified=None):
    # 1. Resolve Account
    stmt = select(Account).where(Account.name == account_name)
    result = await session.execute(stmt)
    account = result.scalar_one_or_none()
    if not account:
        return False, f"Account '{account_name}' not found.", None

    # 2. Parse Date
    if isinstance(date, str):
        try:
             # Try YYYY-MM-DD
             tx_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
             return False, "Invalid date format. Use YYYY-MM-DD.", None
    else:
        tx_date = date

    # 3. AI Categorization or Validation
    confidence = confidence if confidence is not None else 1.0
    is_verified = is_verified if is_verified is not None else True
    ai_reasoning = decision_reason if decision_reason else "Manual Entry"
    tx_type = tx_type if tx_type else "expense"
    decision_state = "auto_approved" if is_verified else "needs_review"
    decision_reason = decision_reason if decision_reason else "Manual Entry"
    
    if category_id:
        # Validate Category
        cat_res = await session.execute(select(Category).where(Category.id == category_id))
        category = cat_res.scalar_one_or_none()
        if not category:
             return False, "Invalid Category ID", None
        tx_type = category.type
    else:
        # Auto-Categorize
        ai = CategorizerAI()
        cat_id, conf, reason, suggested_type = await ai.suggest_category(description, session)
        category_id = cat_id
        confidence = conf
        ai_reasoning = reason
        tx_type = suggested_type
        
        # Policy Check
        conflict_flags = []
        if tx_type != "transfer" and category_id is None:
            conflict_flags.append("invalid_category_id")
            
        decision = evaluate_decision_policy(confidence, conflict_flags)
        is_verified = decision.can_auto_verify
        decision_state = decision.state
        decision_reason = decision.reason

    # 4. Create Transaction
    new_tx = Transaction(
        date=tx_date,
        description=description,
        amount=amount,
        type=tx_type,
        account_id=account.id,
        category_id=category_id,
        confidence_score=confidence,
        is_verified=is_verified,
        decision_state=decision_state,
        decision_reason=decision_reason,
        review_priority=100 if is_verified else 50,
        raw_csv_row="MANUAL_ENTRY"
    )
    session.add(new_tx)
    await session.flush()
    
    # 5. Create Memory (if AI used and unverified)
    if not is_verified and category_id:
         pattern_key = extract_pattern_key(description)
         memory = AIMemory(
             transaction_id=new_tx.id,
             pattern_key=pattern_key,
             ai_suggested_category_id=category_id,
             ai_reasoning=ai_reasoning,
             policy_version=POLICY_VERSION,
             threshold_used=AUTO_APPROVE_MIN
         )
         session.add(memory)

    await session.commit()
    
    status_msg = "Added" if is_verified else "Added (Needs Review)"
    return True, f"{status_msg}: #{new_tx.id} {description} ({amount})", new_tx

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
