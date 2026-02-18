import csv
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.benchmark import (
    clear_benchmark_item_label,
    import_benchmark_csv,
    learn_aliases_from_benchmark,
    list_benchmark_items,
    score_benchmark_dataset,
    set_benchmark_item_label,
    set_benchmark_item_label_category_id,
)
from src.database import Category, CategoryBenchmarkItem, CategoryBenchmarkRun, MerchantKeywordAlias


@pytest.mark.asyncio
async def test_import_benchmark_csv_populates_dataset(db_session, tmp_path):
    fuel = Category(name="Fuel", parent_name="Transportation", type="expense")
    salary = Category(name="Salary", parent_name="Employer", type="income")
    db_session.add_all([fuel, salary])
    await db_session.commit()

    csv_path = tmp_path / "benchmark.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["description", "amount", "type", "parent_category", "category"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "description": "UNITED SERVICE STATION",
                "amount": "-42.10",
                "type": "expense",
                "parent_category": "Transportation",
                "category": "Fuel",
            }
        )
        writer.writerow(
            {
                "description": "ACME PAYROLL",
                "amount": "3200",
                "type": "income",
                "parent_category": "Employer",
                "category": "Salary",
            }
        )

    ok, _msg, stats = await import_benchmark_csv(
        db_session,
        str(csv_path),
        source_name="unit-import-basic",
    )
    assert ok is True
    assert stats["added"] == 2
    assert stats["labeled"] == 2

    rows = (
        await db_session.execute(
            select(CategoryBenchmarkItem)
            .where(CategoryBenchmarkItem.source_file == "unit-import-basic")
            .order_by(CategoryBenchmarkItem.id.asc())
        )
    ).scalars().all()
    assert len(rows) == 2
    assert rows[0].expected_type == "expense"
    assert rows[1].expected_type == "income"


@pytest.mark.asyncio
async def test_import_benchmark_csv_uses_wise_fields_when_description_missing(db_session, tmp_path):
    csv_path = tmp_path / "wise_like.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "ID",
                "Direction",
                "Created on",
                "Target name",
                "Source amount (after fees)",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "ID": "TX-1",
                "Direction": "OUT",
                "Created on": "2026-01-24 12:40:19",
                "Target name": "Tucker Fresh",
                "Source amount (after fees)": "5.99",
            }
        )

    ok, _msg, stats = await import_benchmark_csv(db_session, str(csv_path))
    assert ok is True
    assert stats["added"] == 1

    row = (
        await db_session.execute(select(CategoryBenchmarkItem).where(CategoryBenchmarkItem.external_id == "TX-1"))
    ).scalar_one()
    assert row.description == "Tucker Fresh"
    assert row.tx_type == "expense"
    assert row.amount == 5.99


@pytest.mark.asyncio
async def test_import_benchmark_pdf_requires_bank(db_session, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_text("not a real pdf")

    ok, msg, stats = await import_benchmark_csv(db_session, str(pdf_path))
    assert ok is False
    assert "requires --bank" in msg
    assert stats is None


@pytest.mark.asyncio
async def test_import_benchmark_pdf_with_bank_uses_bank_parser(db_session, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_text("not a real pdf")

    with patch("src.benchmark.BankParser") as mock_parser_cls:
        mock_parser = mock_parser_cls.return_value
        mock_parser.parse.return_value = [
            {
                "date": datetime(2026, 2, 1),
                "description": "UNITED ANKETELL NTH",
                "amount": 7.5,
                "type": "expense",
                "raw_csv_row": "raw",
            }
        ]
        ok, _msg, stats = await import_benchmark_csv(
            db_session,
            str(pdf_path),
            source_name="anz-pdf",
            bank_name="ANZ",
        )

    assert ok is True
    assert stats["added"] == 1
    row = (
        await db_session.execute(
            select(CategoryBenchmarkItem).where(CategoryBenchmarkItem.source_file == "anz-pdf")
        )
    ).scalars().first()
    assert row is not None
    assert row.source_file == "anz-pdf"
    assert row.description == "UNITED ANKETELL NTH"
    assert row.tx_type == "expense"


@pytest.mark.asyncio
async def test_learn_aliases_from_benchmark_uses_labeled_non_transfer_rows_by_default(db_session):
    db_session.add_all(
        [
            CategoryBenchmarkItem(
                description="SUPER CHEAP AUTO ROCKINGHAM",
                source_file="alias-learn-unit",
                expected_type="expense",
                expected_parent_name="Transportation",
                expected_category_name="Maintenance",
            ),
            CategoryBenchmarkItem(
                description="TRANSFER RTP SOMEBANK INTERNET BANKING",
                source_file="alias-learn-unit",
                expected_type="transfer",
                expected_parent_name="(Transfer)",
                expected_category_name="(Transfer)",
            ),
        ]
    )
    await db_session.commit()

    ok, _msg, stats = await learn_aliases_from_benchmark(
        db_session,
        source_file="alias-learn-unit",
    )
    assert ok is True
    assert stats["seen"] == 1
    assert stats["learned_updates"] == 1

    aliases = (
        await db_session.execute(
            select(MerchantKeywordAlias).order_by(MerchantKeywordAlias.id.asc())
        )
    ).scalars().all()
    assert len(aliases) == 1
    assert "SUPER CHEAP AUTO" in aliases[0].canonical_keyword


@pytest.mark.asyncio
async def test_set_benchmark_item_label_assigns_parent_and_sub_category(db_session):
    grocery = Category(name="Grocery", parent_name="Household", type="expense")
    db_session.add(grocery)
    await db_session.flush()

    item = CategoryBenchmarkItem(
        description="WOOLWORTHS NICHOLSON RD",
        amount=-85.25,
        tx_type="expense",
        date=datetime(2026, 2, 1),
    )
    db_session.add(item)
    await db_session.commit()

    ok, msg = await set_benchmark_item_label(
        db_session,
        item_id=item.id,
        parent_name="Household",
        category_name="Grocery",
        tx_type="expense",
    )
    assert ok is True
    assert "labeled" in msg.lower()

    refreshed = (
        await db_session.execute(select(CategoryBenchmarkItem).where(CategoryBenchmarkItem.id == item.id))
    ).scalar_one()
    assert refreshed.expected_parent_name == "Household"
    assert refreshed.expected_category_name == "Grocery"
    assert refreshed.expected_type == "expense"


@pytest.mark.asyncio
async def test_list_benchmark_items_unlabeled_only_includes_pending_non_transfer_rows(db_session):
    transfer_item = CategoryBenchmarkItem(
        description="TRANSFER TO SAVINGS",
        expected_type="transfer",
        expected_parent_name="(Transfer)",
        expected_category_name="(Transfer)",
    )
    pending_item = CategoryBenchmarkItem(
        description="PAYMENT TO SOMEONE",
        expected_type="expense",
        expected_parent_name="Bills",
        expected_category_name="Utilities",
        expected_category_id=None,
    )
    unlabeled_item = CategoryBenchmarkItem(description="UNKNOWN MERCHANT")

    db_session.add_all([transfer_item, pending_item, unlabeled_item])
    await db_session.commit()

    rows = await list_benchmark_items(db_session, limit=None, unlabeled_only=True)
    ids = {r.id for r in rows}
    assert pending_item.id in ids
    assert unlabeled_item.id in ids
    assert transfer_item.id not in ids


@pytest.mark.asyncio
async def test_set_label_by_category_id_and_clear_label(db_session):
    food = Category(name="Food", parent_name="Entertainment", type="expense")
    db_session.add(food)
    await db_session.flush()

    item = CategoryBenchmarkItem(description="SUSHI DINNER", tx_type="expense")
    db_session.add(item)
    await db_session.commit()

    ok, _msg = await set_benchmark_item_label_category_id(db_session, item_id=item.id, category_id=food.id)
    assert ok is True

    refreshed = (
        await db_session.execute(select(CategoryBenchmarkItem).where(CategoryBenchmarkItem.id == item.id))
    ).scalar_one()
    assert refreshed.expected_category_id == food.id
    assert refreshed.expected_type == "expense"

    ok, _msg = await clear_benchmark_item_label(db_session, item_id=item.id)
    assert ok is True
    refreshed = (
        await db_session.execute(select(CategoryBenchmarkItem).where(CategoryBenchmarkItem.id == item.id))
    ).scalar_one()
    assert refreshed.expected_category_id is None
    assert refreshed.expected_type is None


@pytest.mark.asyncio
async def test_score_benchmark_dataset_writes_normalized_scores_and_run_history(db_session):
    food = Category(name="Food", parent_name="Entertainment", type="expense")
    db_session.add(food)
    await db_session.flush()

    item = CategoryBenchmarkItem(
        source_file="unit_score.csv",
        description="HUNGRY JACKS",
        amount=-12.40,
        tx_type="expense",
        expected_category_id=food.id,
        expected_parent_name="Entertainment",
        expected_category_name="Food",
        expected_type="expense",
        label_source="manual_label",
    )
    db_session.add(item)
    await db_session.commit()

    with patch("src.benchmark.CategorizerAI") as mock_ai_cls, patch(
        "src.benchmark._has_memory_support", new=AsyncMock(return_value=True)
    ):
        mock_ai = mock_ai_cls.return_value
        mock_ai.suggest_category = AsyncMock(
            return_value=(food.id, 0.93, "Merchant is a food chain.", "expense")
        )
        progress_events = []

        async def _progress(update):
            progress_events.append(update)

        ok, _msg, summary = await score_benchmark_dataset(
            db_session,
            model="test-model",
            source_file="unit_score.csv",
            progress_callback=_progress,
        )

    assert ok is True
    assert summary["overall_score"] == 100.0
    assert summary["memory_score"] == 100.0
    assert summary["memory_coverage"] == 100.0

    run = (
        await db_session.execute(select(CategoryBenchmarkRun).order_by(CategoryBenchmarkRun.id.desc()))
    ).scalars().first()
    assert run is not None
    assert run.model == "test-model"
    assert run.overall_score == 100.0
    assert run.memory_score == 100.0
    assert len(progress_events) == 1
    assert progress_events[0]["processed"] == 1
    assert progress_events[0]["total"] == 1


@pytest.mark.asyncio
async def test_score_benchmark_dataset_accepts_multiple_source_filters(db_session):
    food = Category(name="Food", parent_name="Entertainment", type="expense")
    db_session.add(food)
    await db_session.flush()

    db_session.add_all(
        [
            CategoryBenchmarkItem(
                source_file="batch-a",
                description="HUNGRY JACKS",
                expected_category_id=food.id,
                expected_parent_name="Entertainment",
                expected_category_name="Food",
                expected_type="expense",
                label_source="manual_label",
            ),
            CategoryBenchmarkItem(
                source_file="batch-b",
                description="HUNGRY JACKS 2",
                expected_category_id=food.id,
                expected_parent_name="Entertainment",
                expected_category_name="Food",
                expected_type="expense",
                label_source="manual_label",
            ),
            CategoryBenchmarkItem(
                source_file="batch-c",
                description="HUNGRY JACKS 3",
                expected_category_id=food.id,
                expected_parent_name="Entertainment",
                expected_category_name="Food",
                expected_type="expense",
                label_source="manual_label",
            ),
        ]
    )
    await db_session.commit()

    with patch("src.benchmark.CategorizerAI") as mock_ai_cls, patch(
        "src.benchmark._has_memory_support", new=AsyncMock(return_value=False)
    ):
        mock_ai = mock_ai_cls.return_value
        mock_ai.suggest_category = AsyncMock(
            return_value=(food.id, 0.91, "Food merchant.", "expense")
        )
        ok, _msg, summary = await score_benchmark_dataset(
            db_session,
            model="test-model",
            source_file=["batch-a", "batch-b"],
        )

    assert ok is True
    assert summary["total"] == 2
    assert summary["correct"] == 2
