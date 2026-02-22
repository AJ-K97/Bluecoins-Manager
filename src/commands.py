import csv
import json
import os
import re
import textwrap
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
    MerchantKeywordAlias,
    CategoryBenchmarkItem,
    CategoryBenchmarkRun,
    OperationLog,
    Base,
    engine,
)
from src.parser import BankParser
from src.ai import CategorizerAI
from src.patterns import extract_pattern_key_result
from src.keyword_resolver import KeywordResolver
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


def _serialize_tx_snapshot(tx):
    return {
        "tx_id": int(tx.id),
        "category_id": tx.category_id,
        "tx_type": tx.type,
        "amount": float(tx.amount) if tx.amount is not None else None,
        "is_verified": bool(tx.is_verified),
        "decision_state": tx.decision_state,
        "decision_reason": tx.decision_reason,
        "review_bucket": tx.review_bucket,
        "review_priority": tx.review_priority,
        "note": tx.note,
        "confidence_score": float(tx.confidence_score) if tx.confidence_score is not None else None,
    }


def _serialize_memory_snapshot(memory):
    if not memory:
        return None
    return {
        "memory_id": int(memory.id),
        "user_selected_category_id": memory.user_selected_category_id,
        "reflection": memory.reflection,
    }


def _record_operation(session, operation_type, payload):
    session.add(
        OperationLog(
            operation_type=operation_type,
            payload_json=json.dumps(payload, ensure_ascii=True),
        )
    )


async def rebuild_category_understanding(session, category_ids=None):
    """
    Build/update stored category intent profiles from verified transactions.
    """
    stmt = select(Category)
    if category_ids:
        stmt = stmt.where(Category.id.in_(list(set(category_ids))))
    cat_res = await session.execute(stmt)
    categories = cat_res.scalars().all()

    resolver = KeywordResolver()
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
            resolved = await resolver.resolve(tx.description, session)
            key = resolved.keyword
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
    "merchant_keyword_aliases": MerchantKeywordAlias,
    "ai_global_memory": AIGlobalMemory,
    "ai_category_understanding": AICategoryUnderstanding,
    "llm_knowledge_chunks": LLMKnowledgeChunk,
    "llm_skills": LLMSkill,
    "llm_finetune_examples": LLMFineTuneExample,
    "category_benchmark_items": CategoryBenchmarkItem,
    "category_benchmark_runs": CategoryBenchmarkRun,
    "operation_logs": OperationLog,
}

# parent -> hard dependent children (FK/consistency must be addressed first if non-empty)
RESET_HARD_DEPENDENCIES = {
    "accounts": ["transactions"],
    "categories": ["transactions", "ai_category_understanding", "category_benchmark_items"],
    "transactions": ["ai_memory", "llm_finetune_examples"],
}

# delete order from most dependent to least dependent
RESET_DELETE_ORDER = [
    "ai_memory",
    "llm_finetune_examples",
    "llm_knowledge_chunks",
    "ai_category_understanding",
    "category_benchmark_runs",
    "category_benchmark_items",
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
    def render_box(lines, width=88):
        border = "+" + "-" * (width - 2) + "+"
        print(border)
        for line in lines:
            wrapped = textwrap.wrap(str(line), width=width - 4) or [""]
            for part in wrapped:
                print(f"| {part:<{width - 4}} |")
        print(border)

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
    keyword_resolver = KeywordResolver()
    
    new_txs = []
    new_tx_ids = []
    # Cache AI decisions within one import run to keep identical descriptions consistent.
    ai_decision_cache = {}
    skipped = 0
    verified_categories_touched = set()
    
    for tx_data in transactions:
        raw_block = (tx_data.get("raw_csv_row") or "").strip()
        source_lines = []
        if raw_block:
            if " | " in raw_block:
                source_lines = [x.strip() for x in raw_block.split(" | ") if x.strip()]
            else:
                source_lines = [raw_block]

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
        
        keyword_result = await keyword_resolver.resolve(tx_data["description"], session)

        cat_id = None
        confidence = 0.0
        reasoning = None
        tx_type = tx_data["type"] # Default from parser
        is_verified = False
        cache_key = (
            (tx_data.get("description") or "").strip().upper(),
            (tx_data.get("type") or "").strip().lower(),
        )

        # AI Suggestion
        if cache_key in ai_decision_cache:
            cat_id, confidence, reasoning, suggested_type = ai_decision_cache[cache_key]
            print(f"Resolving '{tx_data['description']}' with AI... (cached)")
        else:
            print(f"Resolving '{tx_data['description']}' with AI...")
            cat_id, confidence, reasoning, suggested_type = await ai.suggest_category(
                tx_data["description"],
                session,
                expected_type=tx_data["type"] if tx_data["type"] in {"expense", "income"} else None,
                amount_hint=tx_data.get("amount"),
            )
            ai_decision_cache[cache_key] = (cat_id, confidence, reasoning, suggested_type)
        if suggested_type:
            tx_type = suggested_type
        if tx_type == "transfer":
            cat_id = None
        ai_suggested_cat_id = cat_id if tx_type != "transfer" else None
        ai_suggested_reasoning = reasoning
        if tx_type == "transfer":
            ai_label = "(Transfer) > (Transfer) [transfer]"
        else:
            ai_parent, ai_name = await get_category_display_from_values(session, tx_type, ai_suggested_cat_id)
            ai_label = format_category_label(ai_parent, ai_name, tx_type)
        
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
            # (cat_id, is_verified, tx_type, confidence, reasoning[, note])
            reviewed = await review_callback(tx_data, cat_id, confidence, tx_type, reasoning, session)
            if isinstance(reviewed, tuple) and len(reviewed) >= 6:
                cat_id, is_verified, tx_type, confidence, reasoning, reviewed_note = reviewed[:6]
                tx_data["note"] = (reviewed_note or "").strip() or None
            else:
                cat_id, is_verified, tx_type, confidence, reasoning = reviewed
            if tx_type == "transfer":
                cat_id = None
        else:
            is_verified = decision.can_auto_verify

        source_block_section = [f"  - {line}" for line in source_lines] if source_lines else ["  - (none)"]
        box_lines = [
            f"Date: {tx_data['date']}    Amount: {tx_data['amount']}",
            f"Type: {(tx_type or '').upper()}",
            f"Description: {tx_data['description']}",
            "Source Block:",
            *source_block_section,
            f"AI Suggestion: {ai_label}",
            f"AI Confidence: {confidence:.2f}",
            f"AI Reasoning: {ai_suggested_reasoning or 'No reasoning provided.'}",
        ]
        render_box(box_lines)

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
        if is_verified:
            decision_state = "auto_approved"
            decision_reason = "User verified during import review."
            decision_bucket = "manual_review"
            decision_priority = 100
        else:
            decision_state = decision.state
            decision_reason = decision.reason
            decision_bucket = decision.bucket
            decision_priority = decision.priority

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
            decision_state=decision_state,
            decision_reason=decision_reason,
            review_priority=decision_priority,
            review_bucket=decision_bucket,
            note=(tx_data.get("note") or "").strip() or None,
        )
        try:
            session.add(new_tx)
            await session.flush() # Get ID
            if is_verified and cat_id:
                verified_categories_touched.add(cat_id)
            
            # Create Memory Entry
            memory = AIMemory(
                transaction_id=new_tx.id,
                pattern_key=keyword_result.keyword,
                ai_suggested_category_id=ai_suggested_cat_id,
                ai_reasoning=reasoning or ai_suggested_reasoning,
                user_selected_category_id=cat_id if is_verified else None, # If verified, we record it
                policy_version=POLICY_VERSION,
                threshold_used=AUTO_APPROVE_MIN,
                conflict_flags_json=json.dumps(final_flags, ensure_ascii=True),
            )
            session.add(memory)
            await session.commit()
            new_txs.append(new_tx)
            new_tx_ids.append(new_tx.id)
            if is_verified:
                try:
                    await keyword_resolver.learn_from_verified(
                        session,
                        tx_data["description"],
                        resolved_keyword=keyword_result.keyword,
                        transaction_id=new_tx.id,
                    )
                    await session.commit()
                except Exception:
                    await session.rollback()
        except Exception as e:
            await session.rollback()
            partial_msg = (
                f"Import stopped due to database error after saving {len(new_txs)} transactions "
                f"(skipped {skipped} duplicates): {e}"
            )
            return False, partial_msg, new_txs

    if verified_categories_touched:
        try:
            await rebuild_category_understanding(session, category_ids=list(verified_categories_touched))
            await session.commit()
        except Exception:
            await session.rollback()
    
    result_msg = f"Imported {len(new_txs)} transactions. Skipped {skipped} duplicates."
    
    # Export if requested
    if output_path and new_tx_ids:
        # Re-fetch with category for export
        stmt = select(Transaction).options(selectinload(Transaction.category), selectinload(Transaction.account)).where(Transaction.id.in_(new_tx_ids))
        result = await session.execute(stmt)
        export_txs = result.scalars().all()
        
        success, msg = export_to_bluecoins_csv(export_txs, output_path)
        result_msg += f"\n{msg}"
        
    # Re-fetch persisted rows so caller gets stable objects even with per-row commits.
    persisted = []
    if new_tx_ids:
        stmt = select(Transaction).options(selectinload(Transaction.category), selectinload(Transaction.account)).where(Transaction.id.in_(new_tx_ids))
        result = await session.execute(stmt)
        persisted = result.scalars().all()
        _record_operation(
            session,
            "import_batch",
            {
                "tx_ids": [int(tx_id) for tx_id in new_tx_ids],
                "account_name": account_name,
                "bank_name": bank_name,
                "source_file": str(file_path),
                "imported_count": len(new_tx_ids),
                "skipped_count": skipped,
            },
        )
        await session.commit()

    return True, result_msg, persisted

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


def _finalize_as_verified(
    tx,
    reason="Finalized by user verification.",
    bucket="manual_review",
):
    tx.is_verified = True
    tx.decision_state = "auto_approved"
    tx.review_bucket = bucket
    tx.review_priority = 100
    tx.decision_reason = reason


async def recalc_queue_decisions(session, since=None):
    stmt = select(Transaction).options(selectinload(Transaction.category))
    if since:
        stmt = stmt.where(Transaction.date >= since)
    result = await session.execute(stmt)
    txs = result.scalars().all()

    updated = 0
    for tx in txs:
        if tx.is_verified:
            reason = tx.decision_reason or "Finalized by verification."
            if reason.startswith("Confidence "):
                reason = "Finalized by verification."
            _finalize_as_verified(tx, reason=reason, bucket="verified")
            session.add(tx)
            updated += 1
            continue

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
    tx_before = _serialize_tx_snapshot(tx)
    memory_before = _serialize_memory_snapshot(memory)
    
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
    _finalize_as_verified(
        tx,
        reason="User verified category during review.",
        bucket="manual_review",
    )
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
            pattern_key = extract_pattern_key_result(tx.description).keyword
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

    _record_operation(
        session,
        "review_action",
        {
            "action": "update_transaction_category",
            "tx_snapshot": tx_before,
            "memory_snapshot": memory_before,
        },
    )
    await session.commit()
    try:
        await keyword_resolver.learn_from_verified(session, tx.description, transaction_id=tx.id)
        await session.commit()
    except Exception:
        await session.rollback()
    return True, "Transaction category updated and verified."

async def update_transaction_amount(session, tx_id, new_amount):
    stmt = select(Transaction).where(Transaction.id == tx_id)
    result = await session.execute(stmt)
    tx = result.scalar_one_or_none()
    if not tx:
        return False, "Transaction not found."

    tx_before = _serialize_tx_snapshot(tx)
    tx.amount = new_amount
    tx.is_verified = True
    tx.decision_state = "auto_approved"
    tx.review_bucket = "manual_review"
    tx.review_priority = 100
    tx.decision_reason = "User verified amount during review."
    session.add(tx)
    _record_operation(
        session,
        "review_action",
        {
            "action": "update_transaction_amount",
            "tx_snapshot": tx_before,
            "memory_snapshot": None,
        },
    )
    await session.commit()
    return True, "Transaction amount updated and verified."


async def update_transaction_note(session, tx_id, note):
    stmt = select(Transaction).where(Transaction.id == tx_id)
    result = await session.execute(stmt)
    tx = result.scalar_one_or_none()
    if not tx:
        return False, "Transaction not found."

    tx_before = _serialize_tx_snapshot(tx)
    text = (note or "").strip()
    tx.note = text if text else None
    session.add(tx)
    _record_operation(
        session,
        "review_action",
        {
            "action": "update_transaction_note",
            "tx_snapshot": tx_before,
            "memory_snapshot": None,
        },
    )
    await session.commit()
    return True, "Transaction note updated."

async def mark_transaction_verified(session, tx_id):
    # Fetch existing transaction and memory
    stmt = select(Transaction).where(Transaction.id == tx_id)
    result = await session.execute(stmt)
    tx = result.scalar_one_or_none()
    
    if tx:
        tx_before = _serialize_tx_snapshot(tx)
        _finalize_as_verified(
            tx,
            reason="User marked transaction as verified.",
            bucket="manual_review",
        )
        session.add(tx)
        
        # Update Memory
        mem_stmt = select(AIMemory).where(AIMemory.transaction_id == tx_id).order_by(AIMemory.created_at.desc())
        mem_res = await session.execute(mem_stmt)
        memory = mem_res.scalars().first()
        memory_before = _serialize_memory_snapshot(memory)
        
        if memory:
            memory.user_selected_category_id = tx.category_id
            session.add(memory)

        if tx.category_id:
            await rebuild_category_understanding(session, category_ids=[tx.category_id])

        _record_operation(
            session,
            "review_action",
            {
                "action": "mark_transaction_verified",
                "tx_snapshot": tx_before,
                "memory_snapshot": memory_before,
            },
        )

    await session.commit()
    if tx:
        try:
            await keyword_resolver.learn_from_verified(session, tx.description, transaction_id=tx.id)
            await session.commit()
        except Exception:
            await session.rollback()
    return True, "Transaction verified."

async def mark_transaction_skipped(session, tx_id):
    stmt = select(Transaction).where(Transaction.id == tx_id)
    result = await session.execute(stmt)
    tx = result.scalar_one_or_none()

    if not tx:
        return False, "Transaction not found."

    tx_before = _serialize_tx_snapshot(tx)
    # Skip means user intentionally resolved this row without further edits.
    # Mark as finalized so it no longer appears in review queues.
    _finalize_as_verified(
        tx,
        reason="User skipped transaction during review.",
        bucket="manual_review",
    )
    session.add(tx)
    _record_operation(
        session,
        "review_action",
        {
            "action": "mark_transaction_skipped",
            "tx_snapshot": tx_before,
            "memory_snapshot": None,
        },
    )
    await session.commit()
    return True, "Transaction skipped and finalized."

async def delete_transaction(session, tx_id):
    stmt = delete(Transaction).where(Transaction.id == tx_id)
    await session.execute(stmt)
    await session.commit()
    return True, "Transaction deleted."


async def undo_last_operation(session):
    stmt = (
        select(OperationLog)
        .where(OperationLog.undone_at.is_(None))
        .order_by(OperationLog.created_at.desc(), OperationLog.id.desc())
        .limit(1)
    )
    res = await session.execute(stmt)
    row = res.scalar_one_or_none()
    if not row:
        return False, "No undoable operations found."

    try:
        payload = json.loads(row.payload_json or "{}")
    except Exception:
        payload = {}

    if row.operation_type == "import_batch":
        tx_ids = [int(x) for x in (payload.get("tx_ids") or []) if str(x).isdigit()]
        if not tx_ids:
            return False, "Last import operation has no transaction IDs to undo."

        await session.execute(delete(AIMemory).where(AIMemory.transaction_id.in_(tx_ids)))
        await session.execute(delete(LLMFineTuneExample).where(LLMFineTuneExample.source_transaction_id.in_(tx_ids)))
        await session.execute(delete(Transaction).where(Transaction.id.in_(tx_ids)))
        row.undone_at = datetime.utcnow()
        session.add(row)
        await session.commit()
        return True, f"Undo complete: removed {len(tx_ids)} imported transactions."

    if row.operation_type == "review_action":
        tx_snapshot = payload.get("tx_snapshot") or {}
        memory_snapshot = payload.get("memory_snapshot")
        tx_id = tx_snapshot.get("tx_id")
        if not tx_id:
            return False, "Last review action is missing transaction snapshot."

        tx_res = await session.execute(select(Transaction).where(Transaction.id == int(tx_id)))
        tx = tx_res.scalar_one_or_none()
        if not tx:
            return False, f"Cannot undo review action: transaction #{tx_id} not found."

        touched_categories = {tx.category_id, tx_snapshot.get("category_id")}
        tx.category_id = tx_snapshot.get("category_id")
        tx.type = tx_snapshot.get("tx_type") or tx.type
        tx.amount = tx_snapshot.get("amount")
        tx.is_verified = bool(tx_snapshot.get("is_verified"))
        tx.decision_state = tx_snapshot.get("decision_state")
        tx.decision_reason = tx_snapshot.get("decision_reason")
        tx.review_bucket = tx_snapshot.get("review_bucket")
        tx.review_priority = tx_snapshot.get("review_priority")
        tx.note = tx_snapshot.get("note")
        tx.confidence_score = tx_snapshot.get("confidence_score")
        session.add(tx)

        if memory_snapshot and memory_snapshot.get("memory_id"):
            mem_res = await session.execute(
                select(AIMemory).where(AIMemory.id == int(memory_snapshot["memory_id"]))
            )
            memory = mem_res.scalar_one_or_none()
            if memory:
                memory.user_selected_category_id = memory_snapshot.get("user_selected_category_id")
                memory.reflection = memory_snapshot.get("reflection")
                session.add(memory)

        touched = [cat_id for cat_id in touched_categories if cat_id]
        if touched:
            await rebuild_category_understanding(session, category_ids=touched)

        row.undone_at = datetime.utcnow()
        session.add(row)
        await session.commit()
        action = payload.get("action") or "review action"
        return True, f"Undo complete: reverted {action} on transaction #{tx_id}."

    return False, f"Unsupported undo operation type: {row.operation_type}"

async def add_transaction(
    session,
    date,
    amount,
    description,
    account_name,
    category_id=None,
    tx_type=None,
    confidence=None,
    decision_reason=None,
    is_verified=None,
    note=None,
):
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
        cat_id, conf, reason, suggested_type = await ai.suggest_category(
            description,
            session,
            amount_hint=amount,
        )
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
        raw_csv_row="MANUAL_ENTRY",
        note=(note or "").strip() or None,
    )
    session.add(new_tx)
    await session.flush()
    
    # 5. Create Memory (if AI used and unverified)
    if not is_verified and category_id:
         pattern_key = extract_pattern_key_result(description).keyword
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
    if is_verified:
        try:
            await keyword_resolver.learn_from_verified(session, description, transaction_id=new_tx.id)
            await session.commit()
        except Exception:
            await session.rollback()
    
    status_msg = "Added" if is_verified else "Added (Needs Review)"
    return True, f"{status_msg}: #{new_tx.id} {description} ({amount})", new_tx

def export_to_bluecoins_csv(transactions, output_path):
    header = [
        "(1)Type",
        "(2)Date",
        "(3)Item or Payee",
        "(4)Amount",
        "(5)Parent Category",
        "(6)Category",
        "(7)Account Type",
        "(8)Account",
        "(9)Notes",
        "(10) Label",
        "(11) Status",
        "(12) Split",
    ]

    def _normalize_whitespace(text):
        return re.sub(r"\s+", " ", str(text or "").replace("\xa0", " ")).strip()

    def _clean_description_for_notes(description):
        raw = _normalize_whitespace(description)
        if not raw:
            return ""

        cleaned = raw
        cleaned = re.sub(r"\b\d{2}[A-Z]{3}\d{2}\b", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", " ", cleaned)
        cleaned = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", " ", cleaned)
        cleaned = re.sub(
            r"\b(?:VISA|EFTPOS|DEBIT|CREDIT|AUD|INTERNET\s+BANKING|JOINT\s+BANK\s+TRANSFE?R?|ATMA\d*|POS)\b",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\b(?=[A-Z0-9]{8,}\b)[A-Z0-9]*\d[A-Z0-9]*\b", " ", cleaned)
        cleaned = _normalize_whitespace(cleaned).strip(" -|,/")
        return cleaned or raw

    def _summarize_item_or_payee(tx):
        user_note = _normalize_whitespace(getattr(tx, "note", None))
        if user_note:
            return user_note
        if tx.type == "transfer":
            return "Transfer"

        cleaned_desc = _clean_description_for_notes(tx.description)
        if not cleaned_desc:
            return "Transaction"
        tokens = cleaned_desc.split()
        if not tokens:
            return "Transaction"

        prefix_tokens = {
            "PURCHASE",
            "PAYMENT",
            "CARD",
            "POS",
            "DEBIT",
            "CREDIT",
            "VISA",
            "MASTERCARD",
            "MC",
            "TXN",
            "TRANSACTION",
        }

        idx = 0
        while idx < len(tokens) and tokens[idx].upper() in prefix_tokens:
            idx += 1
        while idx < len(tokens) and re.fullmatch(r"\d{2,6}", tokens[idx]):
            idx += 1

        merchant_tokens = tokens[idx:] if idx < len(tokens) else tokens
        return " ".join(merchant_tokens[:6])

    def _build_notes_value(tx):
        user_note = _normalize_whitespace(getattr(tx, "note", None))
        cleaned_desc = _clean_description_for_notes(tx.description)
        if user_note and cleaned_desc and user_note.lower() != cleaned_desc.lower():
            return f"{user_note} | Source: {cleaned_desc}"
        return user_note or cleaned_desc

    def _parse_signed_number(value):
        if value is None:
            return None
        text = str(value).strip().replace(",", "").replace("$", "")
        if not text:
            return None
        if text.startswith("(") and text.endswith(")"):
            text = f"-{text[1:-1]}"
        text = re.sub(r"\s+", "", text)
        text = re.sub(r"[^0-9.\-+]", "", text)
        if not text or text in {"+", "-", ".", "+.", "-."}:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def _infer_direction_from_raw_row(tx):
        raw = getattr(tx, "raw_csv_row", None)
        if not raw:
            return "unknown"

        # Prefer structured parse if raw row was persisted as JSON.
        if isinstance(raw, str):
            raw_str = raw.strip()
            if raw_str.startswith("{") and raw_str.endswith("}"):
                try:
                    payload = json.loads(raw_str)
                except Exception:
                    payload = None
                if isinstance(payload, dict):
                    # 1) Explicit direction-like fields.
                    for k, v in payload.items():
                        key = str(k or "").strip().lower()
                        val = str(v or "").strip().upper()
                        if key in {"direction", "dir"}:
                            if val == "IN":
                                return "in"
                            if val == "OUT":
                                return "out"
                        if key in {"credit/debit", "debit/credit", "dr/cr"}:
                            if "CREDIT" in val or val in {"CR", "C"}:
                                return "in"
                            if "DEBIT" in val or val in {"DR", "D"}:
                                return "out"
                        if key.endswith("direction"):
                            if "IN" in val and "OUT" not in val:
                                return "in"
                            if "OUT" in val and "IN" not in val:
                                return "out"

                    # 2) Infer from signed amount-like fields.
                    for k, v in payload.items():
                        key = str(k or "").strip().lower()
                        if "amount" not in key and key not in {"debit", "credit"}:
                            continue
                        parsed = _parse_signed_number(v)
                        if parsed is None:
                            continue
                        if parsed < 0:
                            return "out"
                        if parsed > 0:
                            return "in"

        raw_upper = f" {str(raw).upper()} "
        if re.search(r'"\s*DIRECTION\s*"\s*:\s*"\s*OUT\s*"', raw_upper):
            return "out"
        if re.search(r'"\s*DIRECTION\s*"\s*:\s*"\s*IN\s*"', raw_upper):
            return "in"
        if " DIRECTION " in raw_upper:
            if " OUT " in raw_upper and " IN " not in raw_upper:
                return "out"
            if " IN " in raw_upper and " OUT " not in raw_upper:
                return "in"

        return "unknown"

    def _infer_transfer_direction(tx):
        raw_dir = _infer_direction_from_raw_row(tx)
        if raw_dir != "unknown":
            return raw_dir

        text = f" {_normalize_whitespace(getattr(tx, 'description', '')).upper()} "
        inbound_markers = ("TRANSFER FROM", "PAYMENT FROM")
        outbound_markers = ("TRANSFER TO", "PAYMENT TO")
        has_inbound = any(m in text for m in inbound_markers)
        has_outbound = any(m in text for m in outbound_markers)
        if has_inbound and not has_outbound:
            return "in"
        if has_outbound and not has_inbound:
            return "out"

        has_from_word = re.search(r"\bFROM\b", text) is not None
        has_to_word = re.search(r"\bTO\b", text) is not None
        if has_from_word and not has_to_word:
            return "in"
        if has_to_word and not has_from_word:
            return "out"
        return "unknown"

    def _tx_sort_key(entry):
        tx_id = getattr(entry["tx"], "id", None)
        has_numeric_id = isinstance(tx_id, int)
        return (0 if has_numeric_id else 1, tx_id if has_numeric_id else entry["idx"], entry["idx"])

    def _account_key(tx):
        acc_id = getattr(tx, "account_id", None)
        if acc_id is not None:
            return f"id:{acc_id}"
        account = getattr(tx, "account", None)
        acc_name = _normalize_whitespace(getattr(account, "name", "")) if account else ""
        return f"name:{acc_name}" if acc_name else "unknown"

    def _pair_transfer_transactions():
        entries = []
        for idx, tx in enumerate(transactions):
            if getattr(tx, "type", None) != "transfer":
                continue
            date_val = getattr(tx, "date", None)
            day = date_val.date() if hasattr(date_val, "date") else date_val
            amount_val = getattr(tx, "amount", 0.0)
            try:
                abs_amount = abs(float(amount_val))
            except (TypeError, ValueError):
                abs_amount = abs(amount_val) if amount_val is not None else 0.0
            entries.append(
                {
                    "idx": idx,
                    "tx": tx,
                    "direction": _infer_transfer_direction(tx),
                    "group_key": (day, abs_amount),
                    "account_key": _account_key(tx),
                }
            )

        paired_indices = set()
        pair_lookup = {}
        skip_records = []
        by_group = {}
        for entry in entries:
            by_group.setdefault(entry["group_key"], []).append(entry)

        for group in by_group.values():
            outs = sorted([e for e in group if e["direction"] == "out"], key=_tx_sort_key)
            ins = sorted([e for e in group if e["direction"] == "in"], key=_tx_sort_key)
            used_in_idx = set()

            for out_e in outs:
                candidates = [in_e for in_e in ins if in_e["idx"] not in used_in_idx]
                if not candidates:
                    continue
                candidates.sort(
                    key=lambda in_e: (
                        0 if in_e["account_key"] != out_e["account_key"] else 1,
                        _tx_sort_key(in_e),
                    )
                )
                chosen = candidates[0]
                used_in_idx.add(chosen["idx"])
                paired_indices.add(out_e["idx"])
                paired_indices.add(chosen["idx"])
                pair_lookup[out_e["idx"]] = (out_e, chosen)
                pair_lookup[chosen["idx"]] = (out_e, chosen)

            for e in sorted(group, key=_tx_sort_key):
                if e["idx"] in paired_indices:
                    continue
                if e["direction"] == "unknown":
                    reason = "direction_unknown"
                else:
                    reason = "pair_not_found"
                skip_records.append(
                    {
                        "idx": e["idx"],
                        "id": getattr(e["tx"], "id", None),
                        "reason": reason,
                    }
                )

        skipped_indices = {s["idx"] for s in skip_records}
        return pair_lookup, paired_indices, skipped_indices, skip_records

    def _amount_as_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _build_export_row(tx, amount_override=None):
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
        notes = _build_notes_value(tx)
        item_or_payee = _summarize_item_or_payee(tx)
        amount_value = _amount_as_float(tx.amount) if amount_override is None else amount_override

        return [
            "t" if tx.type == "transfer" else ("e" if tx.type == "expense" else "i"),
            tx.date.strftime("%m/%d/%Y"),
            item_or_payee,
            str(amount_value),
            parent_name,
            cat_name,
            "Bank",
            acc_name,
            notes,
            "",
            "",
            "",
        ]

    try:
        pair_lookup, paired_transfer_indices, skipped_transfer_indices, skipped_transfers = _pair_transfer_transactions()
        exported_count = 0
        written_transfer_indices = set()
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            
            for idx, tx in enumerate(transactions):
                if getattr(tx, "type", None) != "transfer":
                    amount_value = abs(_amount_as_float(getattr(tx, "amount", 0.0)))
                    writer.writerow(_build_export_row(tx, amount_override=amount_value))
                    exported_count += 1
                    continue

                if idx in skipped_transfer_indices or idx in written_transfer_indices:
                    continue
                if idx not in paired_transfer_indices:
                    continue

                out_e, in_e = pair_lookup[idx]
                out_idx = out_e["idx"]
                in_idx = in_e["idx"]
                if out_idx in written_transfer_indices or in_idx in written_transfer_indices:
                    continue

                out_tx = out_e["tx"]
                in_tx = in_e["tx"]
                writer.writerow(_build_export_row(out_tx, amount_override=-abs(_amount_as_float(getattr(out_tx, "amount", 0.0)))))
                writer.writerow(_build_export_row(in_tx, amount_override=abs(_amount_as_float(getattr(in_tx, "amount", 0.0)))))
                written_transfer_indices.add(out_idx)
                written_transfer_indices.add(in_idx)
                exported_count += 2

        msg = f"Exported {exported_count} transactions to {output_path}"
        if skipped_transfers:
            skipped_bits = []
            for s in skipped_transfers:
                label = f"#{s['id']}" if s.get("id") is not None else f"@{s['idx']}"
                skipped_bits.append(f"{label}({s['reason']})")
            msg += f". Skipped {len(skipped_transfers)} unpaired transfers: {', '.join(skipped_bits)}"
        return True, msg
    except Exception as e:
        return False, f"Export failed: {e}"
