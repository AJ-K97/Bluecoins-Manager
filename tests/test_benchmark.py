import csv
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.benchmark import (
    clear_benchmark_item_label,
    import_benchmark_csv,
    list_benchmark_items,
    score_benchmark_dataset,
    set_benchmark_item_label,
    set_benchmark_item_label_category_id,
)
from src.database import Category, CategoryBenchmarkItem, CategoryBenchmarkRun


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

    ok, _msg, stats = await import_benchmark_csv(db_session, str(csv_path))
    assert ok is True
    assert stats["added"] == 2
    assert stats["labeled"] == 2

    rows = (await db_session.execute(select(CategoryBenchmarkItem).order_by(CategoryBenchmarkItem.id.asc()))).scalars().all()
    assert len(rows) == 2
    assert rows[0].expected_type == "expense"
    assert rows[1].expected_type == "income"


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
