from datetime import datetime

import pytest

from src.database import AIMemory, Account, Category, Transaction
from src.graph_webapp import build_keyword_category_graph


@pytest.mark.asyncio
async def test_graph_groups_keyword_category_pairs(db_session):
    account = Account(name="Graph Account 1", institution="Test")
    category = Category(name="Fuel", parent_name="Car", type="expense")
    db_session.add_all([account, category])
    await db_session.flush()

    tx1 = Transaction(
        date=datetime(2026, 1, 3),
        description="Shell service station",
        amount=80.0,
        type="expense",
        account_id=account.id,
        category_id=category.id,
        confidence_score=0.9,
        is_verified=True,
    )
    tx2 = Transaction(
        date=datetime(2026, 1, 5),
        description="Shell motorway",
        amount=95.0,
        type="expense",
        account_id=account.id,
        category_id=category.id,
        confidence_score=0.7,
        is_verified=False,
    )
    db_session.add_all([tx1, tx2])
    await db_session.flush()

    db_session.add_all(
        [
            AIMemory(
                transaction_id=tx1.id,
                pattern_key="SHELL",
                ai_reasoning="Fuel station merchant keyword",
            ),
            AIMemory(
                transaction_id=tx2.id,
                pattern_key="SHELL",
                ai_reasoning="Fuel station merchant keyword",
            ),
        ]
    )
    await db_session.flush()

    payload = await build_keyword_category_graph(db_session, limit=100)
    shell_edges = [edge for edge in payload["edges"] if edge["keyword"] == "SHELL"]

    assert len(shell_edges) == 1
    edge = shell_edges[0]
    assert edge["keyword"] == "SHELL"
    assert edge["category_label"].startswith("Car > Fuel")
    assert edge["count"] == 2
    assert edge["reason"] == "Fuel station merchant keyword"
    assert edge["weight"] > 0


@pytest.mark.asyncio
async def test_graph_verified_only_filter(db_session):
    account = Account(name="Graph Account 2", institution="Test")
    category = Category(name="Cafe", parent_name="Food", type="expense")
    db_session.add_all([account, category])
    await db_session.flush()

    verified_tx = Transaction(
        date=datetime(2026, 1, 6),
        description="Cafe verified",
        amount=10.0,
        type="expense",
        account_id=account.id,
        category_id=category.id,
        confidence_score=0.8,
        is_verified=True,
    )
    unverified_tx = Transaction(
        date=datetime(2026, 1, 7),
        description="Cafe not verified",
        amount=12.0,
        type="expense",
        account_id=account.id,
        category_id=category.id,
        confidence_score=0.8,
        is_verified=False,
    )
    db_session.add_all([verified_tx, unverified_tx])
    await db_session.flush()

    db_session.add_all(
        [
            AIMemory(transaction_id=verified_tx.id, pattern_key="CAFE", ai_reasoning="Cafe keyword"),
            AIMemory(transaction_id=unverified_tx.id, pattern_key="CAFE", ai_reasoning="Cafe keyword"),
        ]
    )
    await db_session.flush()

    all_rows = await build_keyword_category_graph(db_session, verified_only=False, limit=100)
    verified_rows = await build_keyword_category_graph(db_session, verified_only=True, limit=100)
    all_edges = [edge for edge in all_rows["edges"] if edge["keyword"] == "CAFE"]
    verified_edges = [edge for edge in verified_rows["edges"] if edge["keyword"] == "CAFE"]

    assert all_edges[0]["count"] == 2
    assert verified_edges[0]["count"] == 1
    assert verified_edges[0]["verified_ratio"] == 1.0


@pytest.mark.asyncio
async def test_graph_uncategorized_toggle(db_session):
    account = Account(name="Graph Account 3", institution="Test")
    db_session.add(account)
    await db_session.flush()

    tx = Transaction(
        date=datetime(2026, 1, 8),
        description="Unknown merchant",
        amount=20.0,
        type="expense",
        account_id=account.id,
        category_id=None,
        confidence_score=0.4,
        is_verified=False,
    )
    db_session.add(tx)
    await db_session.flush()

    db_session.add(
        AIMemory(
            transaction_id=tx.id,
            pattern_key="UNKNOWN",
            ai_reasoning="No category yet",
            ai_suggested_category_id=None,
        )
    )
    await db_session.flush()

    hidden = await build_keyword_category_graph(
        db_session,
        include_uncategorized=False,
        limit=100,
    )
    shown = await build_keyword_category_graph(
        db_session,
        include_uncategorized=True,
        limit=100,
    )

    hidden_unknown = [edge for edge in hidden["edges"] if edge["keyword"] == "UNKNOWN"]
    shown_unknown = [edge for edge in shown["edges"] if edge["keyword"] == "UNKNOWN"]

    assert len(hidden_unknown) == 0
    assert len(shown_unknown) == 1
    assert shown_unknown[0]["target"] == "category::uncategorized"


@pytest.mark.asyncio
async def test_graph_filters_by_account_type_and_date(db_session):
    account_a = Account(name="Filter Account A", institution="Test")
    account_b = Account(name="Filter Account B", institution="Test")
    category = Category(name="Fuel", parent_name="Car", type="expense")
    db_session.add_all([account_a, account_b, category])
    await db_session.flush()

    tx_a = Transaction(
        date=datetime(2026, 1, 10),
        description="Shell A",
        amount=55.0,
        type="expense",
        account_id=account_a.id,
        category_id=category.id,
        confidence_score=0.8,
        is_verified=True,
    )
    tx_b = Transaction(
        date=datetime(2026, 2, 10),
        description="Shell B",
        amount=65.0,
        type="expense",
        account_id=account_b.id,
        category_id=category.id,
        confidence_score=0.8,
        is_verified=True,
    )
    db_session.add_all([tx_a, tx_b])
    await db_session.flush()

    db_session.add_all(
        [
            AIMemory(transaction_id=tx_a.id, pattern_key="SHELL", ai_reasoning="Fuel"),
            AIMemory(transaction_id=tx_b.id, pattern_key="SHELL", ai_reasoning="Fuel"),
        ]
    )
    await db_session.flush()

    payload = await build_keyword_category_graph(
        db_session,
        account_id=account_b.id,
        tx_type="expense",
        start_date=datetime(2026, 2, 1).date(),
        end_date=datetime(2026, 2, 28).date(),
        limit=100,
    )
    shell_edges = [edge for edge in payload["edges"] if edge.get("edge_type") == "keyword_category" and edge["keyword"] == "SHELL"]
    assert len(shell_edges) == 1
    assert shell_edges[0]["count"] == 1
