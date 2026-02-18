import csv
import inspect
import json
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from src.ai import CategorizerAI
from src.parser import BankParser
from src.database import (
    AICategoryUnderstanding,
    AIMemory,
    Category,
    CategoryBenchmarkItem,
    CategoryBenchmarkRun,
    Transaction,
)
from src.keyword_resolver import KeywordResolver


def _normalize_header(name: str) -> str:
    text = (name or "").strip().lower()
    text = text.replace("(", " ").replace(")", " ")
    for ch in ["-", "/", ".", "#"]:
        text = text.replace(ch, " ")
    text = "_".join(x for x in text.split() if x)
    return text


def _pick_field(field_map, *aliases):
    for a in aliases:
        key = _normalize_header(a)
        if key in field_map:
            return field_map[key]
    return None


def _row_value_by_aliases(row, field_map, *aliases):
    col = _pick_field(field_map, *aliases)
    if not col:
        return ""
    return str(row.get(col) or "").strip()


def _normalize_tx_type(value: Optional[str]) -> Optional[str]:
    tx_type = (value or "").strip().lower()
    if tx_type in {"expense", "income", "transfer"}:
        return tx_type
    return None


def _parse_date(value: Optional[str]):
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"]:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _parse_amount(value: Optional[str]):
    text = (value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _derive_description_from_row(row, field_map, explicit_col: Optional[str] = None) -> str:
    if explicit_col:
        text = str(row.get(explicit_col) or "").strip()
        if text:
            return text

    # Wise and bank-export friendly fallback priority.
    candidates = [
        _row_value_by_aliases(row, field_map, "target_name"),
        _row_value_by_aliases(row, field_map, "source_name"),
        _row_value_by_aliases(row, field_map, "item_or_payee"),
        _row_value_by_aliases(row, field_map, "item"),
        _row_value_by_aliases(row, field_map, "payee"),
        _row_value_by_aliases(row, field_map, "merchant"),
        _row_value_by_aliases(row, field_map, "reference"),
        _row_value_by_aliases(row, field_map, "note"),
        _row_value_by_aliases(row, field_map, "category"),
        _row_value_by_aliases(row, field_map, "created_by"),
    ]
    for c in candidates:
        if c:
            return c
    return ""


async def _resolve_category(session, parent_name: str, category_name: str, tx_type: Optional[str] = None):
    stmt = select(Category).where(
        Category.parent_name == parent_name,
        Category.name == category_name,
    )
    if tx_type in {"expense", "income"}:
        stmt = stmt.where(Category.type == tx_type)

    res = await session.execute(stmt.order_by(Category.id.asc()))
    rows = res.scalars().all()
    if not rows:
        return None, 0
    if len(rows) == 1:
        return rows[0], 1

    if tx_type in {"expense", "income"}:
        # When duplicate rows exist for same parent/name/type, pick deterministically.
        return rows[0], len(rows)

    # Without explicit type, ambiguity only matters if multiple types exist.
    distinct_types = {str(r.type or "").lower() for r in rows}
    if len(distinct_types) == 1:
        return rows[0], len(rows)
    return None, len(rows)


async def import_benchmark_csv(
    session,
    csv_path: str,
    source_name: Optional[str] = None,
    bank_name: Optional[str] = None,
):
    if not os.path.exists(csv_path):
        return False, f"File not found: {csv_path}", None

    source_file = (source_name or os.path.basename(csv_path) or "benchmark.csv").strip()
    ext = os.path.splitext(csv_path)[1].lower()

    # If bank is provided, parse via bank-specific parser (supports CSV and PDF).
    if bank_name:
        parser = BankParser()
        try:
            parsed_rows = parser.parse(bank_name, csv_path)
        except Exception as e:
            return False, f"Failed to parse {csv_path} with bank '{bank_name}': {e}", None

        added = 0
        skipped = 0
        for i, tx in enumerate(parsed_rows, start=1):
            desc = str(tx.get("description") or "").strip()
            if not desc:
                skipped += 1
                continue

            session.add(
                CategoryBenchmarkItem(
                    source_file=source_file,
                    source_row_number=i,
                    external_id=None,
                    description=desc,
                    amount=tx.get("amount"),
                    tx_type=_normalize_tx_type(tx.get("type")),
                    date=tx.get("date"),
                    raw_row_json=json.dumps(tx, default=str, ensure_ascii=True),
                    expected_category_id=None,
                    expected_parent_name=None,
                    expected_category_name=None,
                    expected_type=None,
                    label_source="bank_parser",
                )
            )
            added += 1

        await session.commit()
        stats = {
            "added": added,
            "skipped": skipped,
            "labeled": 0,
            "source_file": source_file,
            "bank_name": bank_name,
        }
        msg = (
            f"Imported benchmark rows from '{csv_path}' using bank parser '{bank_name}'. "
            f"added={added} skipped={skipped} labeled=0"
        )
        return True, msg, stats

    if ext == ".pdf":
        return (
            False,
            "PDF import requires --bank (e.g. --bank ANZ).",
            None,
        )

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return False, "CSV header not found.", None

        field_map = {_normalize_header(name): name for name in reader.fieldnames}
        description_col = _pick_field(field_map, "description", "desc", "item_or_payee", "item", "payee", "merchant")

        amount_col = _pick_field(
            field_map,
            "amount",
            "amt",
            "source_amount_after_fees",
            "target_amount_after_fees",
        )
        date_col = _pick_field(field_map, "date", "transaction_date", "created_on", "finished_on")
        tx_type_col = _pick_field(field_map, "type", "tx_type", "transaction_type")
        direction_col = _pick_field(field_map, "direction")
        external_id_col = _pick_field(field_map, "id", "external_id", "tx_id", "reference")
        parent_col = _pick_field(field_map, "parent_category", "parent", "expected_parent")
        category_col = _pick_field(field_map, "category", "sub_category", "subcategory", "expected_category")
        expected_type_col = _pick_field(field_map, "expected_type", "label_type")

        added = 0
        skipped = 0
        labeled = 0

        for row_index, row in enumerate(reader, start=2):
            description = _derive_description_from_row(row, field_map, explicit_col=description_col)
            if not description:
                skipped += 1
                continue

            amount = _parse_amount(row.get(amount_col)) if amount_col else None
            tx_type = _normalize_tx_type(row.get(tx_type_col)) if tx_type_col else None
            if tx_type is None and direction_col:
                direction = str(row.get(direction_col) or "").strip().upper()
                if direction == "IN":
                    tx_type = "income"
                elif direction == "OUT":
                    tx_type = "expense"
            date_value = _parse_date(row.get(date_col)) if date_col else None
            external_id = (row.get(external_id_col) or "").strip() if external_id_col else None

            expected_parent_name = (row.get(parent_col) or "").strip() if parent_col else None
            expected_category_name = (row.get(category_col) or "").strip() if category_col else None
            expected_type = _normalize_tx_type(row.get(expected_type_col)) if expected_type_col else None
            label_source = None
            expected_category_id = None

            if expected_type == "transfer":
                label_source = "csv_import"
                labeled += 1
                expected_parent_name = expected_parent_name or "(Transfer)"
                expected_category_name = expected_category_name or "(Transfer)"
            elif expected_parent_name and expected_category_name:
                wanted_type = expected_type or tx_type
                cat, count = await _resolve_category(
                    session,
                    expected_parent_name,
                    expected_category_name,
                    wanted_type,
                )
                if cat:
                    expected_category_id = cat.id
                    expected_type = cat.type
                    label_source = "csv_import"
                    labeled += 1
                elif count == 0:
                    # Keep names for readability; row can be labeled later.
                    label_source = "csv_pending"
                else:
                    label_source = "csv_pending_ambiguous"

            session.add(
                CategoryBenchmarkItem(
                    source_file=source_file,
                    source_row_number=row_index,
                    external_id=external_id or None,
                    description=description,
                    amount=amount,
                    tx_type=tx_type,
                    date=date_value,
                    raw_row_json=json.dumps(row, ensure_ascii=True),
                    expected_category_id=expected_category_id,
                    expected_parent_name=expected_parent_name or None,
                    expected_category_name=expected_category_name or None,
                    expected_type=expected_type,
                    label_source=label_source,
                )
            )
            added += 1

    await session.commit()
    stats = {"added": added, "skipped": skipped, "labeled": labeled, "source_file": source_file}
    msg = (
        f"Imported benchmark rows from '{csv_path}'. "
        f"added={added} skipped={skipped} labeled={labeled}"
    )
    return True, msg, stats


async def list_benchmark_items(
    session,
    limit: Optional[int] = 100,
    unlabeled_only: bool = False,
    source_file: Optional[str] = None,
):
    stmt = select(CategoryBenchmarkItem).options(selectinload(CategoryBenchmarkItem.expected_category)).order_by(
        CategoryBenchmarkItem.id.asc()
    )
    if source_file:
        stmt = stmt.where(CategoryBenchmarkItem.source_file == source_file)
    if unlabeled_only:
        stmt = stmt.where(
            or_(
                CategoryBenchmarkItem.expected_type.is_(None),
                and_(
                    CategoryBenchmarkItem.expected_type != "transfer",
                    CategoryBenchmarkItem.expected_category_id.is_(None),
                ),
            )
        )
    if limit:
        stmt = stmt.limit(max(1, int(limit)))

    res = await session.execute(stmt)
    return res.scalars().all()


async def set_benchmark_item_label(
    session,
    item_id: int,
    parent_name: Optional[str] = None,
    category_name: Optional[str] = None,
    tx_type: Optional[str] = None,
    set_transfer: bool = False,
):
    res = await session.execute(select(CategoryBenchmarkItem).where(CategoryBenchmarkItem.id == int(item_id)))
    item = res.scalar_one_or_none()
    if not item:
        return False, "Benchmark item not found."

    if set_transfer:
        item.expected_category_id = None
        item.expected_parent_name = "(Transfer)"
        item.expected_category_name = "(Transfer)"
        item.expected_type = "transfer"
        item.label_source = "manual_label"
        session.add(item)
        await session.commit()
        return True, f"Benchmark item #{item.id} labeled as transfer."

    parent = (parent_name or "").strip()
    category = (category_name or "").strip()
    expected_type = _normalize_tx_type(tx_type)
    if expected_type == "transfer":
        return False, "Use --set-transfer for transfer labels."
    if not parent or not category:
        return False, "parent_name and category_name are required."

    cat, count = await _resolve_category(session, parent, category, expected_type)
    if not cat and count > 1:
        return False, (
            f"Category '{parent} > {category}' is ambiguous across types. "
            f"Provide --type expense or --type income."
        )
    if not cat:
        return False, f"Category '{parent} > {category}' not found."

    item.expected_category_id = cat.id
    item.expected_parent_name = cat.parent_name
    item.expected_category_name = cat.name
    item.expected_type = cat.type
    item.label_source = "manual_label"
    session.add(item)
    await session.commit()
    return True, f"Benchmark item #{item.id} labeled as {cat.parent_name} > {cat.name} [{cat.type}]."


async def set_benchmark_item_label_category_id(session, item_id: int, category_id: int):
    item_res = await session.execute(select(CategoryBenchmarkItem).where(CategoryBenchmarkItem.id == int(item_id)))
    item = item_res.scalar_one_or_none()
    if not item:
        return False, "Benchmark item not found."

    cat_res = await session.execute(select(Category).where(Category.id == int(category_id)))
    cat = cat_res.scalar_one_or_none()
    if not cat:
        return False, "Category not found."

    item.expected_category_id = cat.id
    item.expected_parent_name = cat.parent_name
    item.expected_category_name = cat.name
    item.expected_type = cat.type
    item.label_source = "manual_label"
    session.add(item)
    await session.commit()
    return True, f"Benchmark item #{item.id} labeled as {cat.parent_name} > {cat.name} [{cat.type}]."


async def clear_benchmark_item_label(session, item_id: int):
    res = await session.execute(select(CategoryBenchmarkItem).where(CategoryBenchmarkItem.id == int(item_id)))
    item = res.scalar_one_or_none()
    if not item:
        return False, "Benchmark item not found."

    item.expected_category_id = None
    item.expected_parent_name = None
    item.expected_category_name = None
    item.expected_type = None
    item.label_source = "manual_clear"
    session.add(item)
    await session.commit()
    return True, f"Cleared label for benchmark item #{item.id}."


async def _has_memory_support(session, resolver: KeywordResolver, description: str, expected_category_id: Optional[int]):
    resolved = await resolver.resolve(description, session)
    keyword = (resolved.keyword or "").strip()

    has_pattern_memory = False
    if keyword and keyword != "UNKNOWN":
        pattern_count = await session.scalar(
            select(func.count()).select_from(AIMemory).where(AIMemory.pattern_key == keyword)
        )
        has_pattern_memory = int(pattern_count or 0) > 0

    has_exact_verified_precedent = False
    desc = (description or "").strip()
    if desc:
        exact_count = await session.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(
                Transaction.description.ilike(desc),
                Transaction.is_verified.is_(True),
            )
        )
        has_exact_verified_precedent = int(exact_count or 0) > 0

    has_category_profile = False
    if expected_category_id:
        profile_count = await session.scalar(
            select(func.count())
            .select_from(AICategoryUnderstanding)
            .where(AICategoryUnderstanding.category_id == expected_category_id)
        )
        has_category_profile = int(profile_count or 0) > 0

    return bool(has_pattern_memory or has_exact_verified_precedent or has_category_profile)


async def score_benchmark_dataset(
    session,
    model: str = "llama3.1:8b",
    limit: Optional[int] = None,
    source_file: Optional[str] = None,
    progress_callback=None,
):
    source_filters = []
    if source_file:
        if isinstance(source_file, str):
            source_filters = [x.strip() for x in source_file.split(",") if x.strip()]
        elif isinstance(source_file, (list, tuple, set)):
            for raw in source_file:
                for token in str(raw or "").split(","):
                    token = token.strip()
                    if token:
                        source_filters.append(token)
    source_filters = list(dict.fromkeys(source_filters))

    stmt = (
        select(CategoryBenchmarkItem)
        .options(selectinload(CategoryBenchmarkItem.expected_category))
        .where(
            or_(
                CategoryBenchmarkItem.expected_category_id.is_not(None),
                CategoryBenchmarkItem.expected_type == "transfer",
            )
        )
        .order_by(CategoryBenchmarkItem.id.asc())
    )
    if source_filters:
        stmt = stmt.where(CategoryBenchmarkItem.source_file.in_(source_filters))
    if limit:
        stmt = stmt.limit(max(1, int(limit)))

    res = await session.execute(stmt)
    items = res.scalars().all()
    if not items:
        return False, "No labeled benchmark rows found.", None

    ai = CategorizerAI(model=model)
    resolver = KeywordResolver()

    total = 0
    correct = 0
    memory_total = 0
    memory_correct = 0

    by_type = {
        "expense": {"total": 0, "correct": 0},
        "income": {"total": 0, "correct": 0},
        "transfer": {"total": 0, "correct": 0},
    }
    error_examples = []

    evaluated_at = datetime.utcnow()

    for item in items:
        expected_type = (item.expected_type or "").strip().lower()
        if expected_type not in {"expense", "income", "transfer"} and item.expected_category:
            expected_type = (item.expected_category.type or "").strip().lower()

        if expected_type not in {"expense", "income", "transfer"}:
            continue

        expected_cat_id = item.expected_category_id
        expected_label = (
            f"{item.expected_parent_name} > {item.expected_category_name}"
            if item.expected_parent_name and item.expected_category_name
            else "(Transfer)"
        )

        candidate_expected_type = expected_type if expected_type in {"expense", "income"} else None
        predicted_cat_id, predicted_conf, predicted_reason, predicted_type = await ai.suggest_category(
            item.description,
            session,
            expected_type=candidate_expected_type,
            amount_hint=item.amount,
        )

        is_correct = False
        if expected_type == "transfer":
            is_correct = predicted_type == "transfer"
        else:
            is_correct = (
                predicted_type == expected_type and
                expected_cat_id is not None and
                predicted_cat_id == expected_cat_id
            )

        has_memory = await _has_memory_support(session, resolver, item.description, expected_cat_id)

        total += 1
        by_type[expected_type]["total"] += 1
        if is_correct:
            correct += 1
            by_type[expected_type]["correct"] += 1

        if has_memory:
            memory_total += 1
            if is_correct:
                memory_correct += 1

        item.last_predicted_category_id = predicted_cat_id
        item.last_predicted_type = predicted_type
        item.last_predicted_confidence = predicted_conf
        item.last_predicted_reasoning = predicted_reason
        item.last_evaluated_at = evaluated_at
        session.add(item)

        if not is_correct and len(error_examples) < 50:
            error_examples.append(
                {
                    "id": item.id,
                    "description": item.description,
                    "expected": {
                        "type": expected_type,
                        "category_id": expected_cat_id,
                        "label": expected_label,
                    },
                    "predicted": {
                        "type": predicted_type,
                        "category_id": predicted_cat_id,
                        "confidence": float(predicted_conf or 0.0),
                        "reasoning": predicted_reason,
                    },
                }
            )

        if progress_callback:
            payload = {
                "processed": total,
                "total": len(items),
                "item_id": item.id,
                "description": item.description,
                "expected_type": expected_type,
                "predicted_type": predicted_type,
                "is_correct": is_correct,
            }
            try:
                callback_result = progress_callback(payload)
                if inspect.isawaitable(callback_result):
                    await callback_result
            except Exception:
                pass

    if total == 0:
        return False, "No valid labeled benchmark rows found.", None

    overall_score = round((correct / total) * 100.0, 2)
    memory_score = round((memory_correct / memory_total) * 100.0, 2) if memory_total else 0.0
    memory_coverage = round((memory_total / total) * 100.0, 2)

    by_type_scores = {}
    for t, stats in by_type.items():
        t_total = stats["total"]
        t_correct = stats["correct"]
        by_type_scores[t] = round((t_correct / t_total) * 100.0, 2) if t_total else None

    details = {
        "model": model,
        "evaluated_at": evaluated_at.isoformat(),
        "overall": {
            "total": total,
            "correct": correct,
            "score": overall_score,
        },
        "memory": {
            "covered": memory_total,
            "coverage_score": memory_coverage,
            "correct": memory_correct,
            "score": memory_score,
        },
        "by_type": {
            "expense": {"total": by_type["expense"]["total"], "score": by_type_scores["expense"]},
            "income": {"total": by_type["income"]["total"], "score": by_type_scores["income"]},
            "transfer": {"total": by_type["transfer"]["total"], "score": by_type_scores["transfer"]},
        },
        "errors": error_examples,
    }

    run = CategoryBenchmarkRun(
        model=model,
        total_items=total,
        evaluated_items=total,
        overall_score=overall_score,
        memory_score=memory_score,
        memory_coverage=memory_coverage,
        details_json=json.dumps(details, ensure_ascii=True),
    )
    session.add(run)
    await session.commit()

    summary = {
        "run_id": run.id,
        "model": model,
        "total": total,
        "correct": correct,
        "overall_score": overall_score,
        "memory_score": memory_score,
        "memory_coverage": memory_coverage,
        "by_type": by_type_scores,
        "errors": error_examples,
    }
    return True, "Benchmark scoring completed.", summary


async def list_benchmark_runs(session, limit: int = 20):
    stmt = select(CategoryBenchmarkRun).order_by(CategoryBenchmarkRun.created_at.desc())
    if limit:
        stmt = stmt.limit(max(1, int(limit)))
    res = await session.execute(stmt)
    return res.scalars().all()


async def learn_aliases_from_benchmark(
    session,
    source_file: Optional[str] = None,
    limit: Optional[int] = None,
    include_transfer: bool = False,
):
    resolver = KeywordResolver()
    stmt = (
        select(CategoryBenchmarkItem)
        .where(
            CategoryBenchmarkItem.description.is_not(None),
            CategoryBenchmarkItem.description != "",
            CategoryBenchmarkItem.expected_type.is_not(None),
        )
        .order_by(CategoryBenchmarkItem.id.asc())
    )
    if source_file:
        stmt = stmt.where(CategoryBenchmarkItem.source_file == source_file)
    if limit:
        stmt = stmt.limit(max(1, int(limit)))

    res = await session.execute(stmt)
    rows = res.scalars().all()
    if not rows:
        return False, "No labeled benchmark rows found for alias learning.", None

    seen = 0
    learned = 0
    for row in rows:
        expected_type = (row.expected_type or "").strip().lower()
        if expected_type not in {"expense", "income"} and not include_transfer:
            continue
        seen += 1
        ok = await resolver.learn_from_verified(session, row.description, transaction_id=None)
        if ok:
            learned += 1

    await session.commit()
    stats = {"seen": seen, "learned_updates": learned, "source_file": source_file}
    return True, f"Benchmark alias learning complete. seen={seen} learned_updates={learned}", stats
