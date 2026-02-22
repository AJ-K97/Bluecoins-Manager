from datetime import datetime

import pytest

from src.database import Account, Category, Transaction
from src.query_engine import plan_ask_db_query, run_ask_db_query


@pytest.mark.asyncio
async def test_ask_db_top_categories_with_time_and_type(db_session):
    account = Account(name="QA AskDB Account", institution="HSBC")
    food = Category(name="Dining", parent_name="Food", type="expense")
    travel = Category(name="Taxi", parent_name="Transport", type="expense")
    db_session.add_all([account, food, travel])
    await db_session.flush()

    txs = [
        Transaction(
            date=datetime(2026, 2, 1),
            description="Sushi",
            amount=-45.0,
            type="expense",
            account_id=account.id,
            category_id=food.id,
        ),
        Transaction(
            date=datetime(2026, 2, 2),
            description="Uber",
            amount=-20.0,
            type="expense",
            account_id=account.id,
            category_id=travel.id,
        ),
    ]
    db_session.add_all(txs)
    await db_session.commit()

    plan = await plan_ask_db_query(
        db_session,
        "top categories for expenses from QA AskDB Account this month",
        limit=5,
    )
    result = await run_ask_db_query(db_session, plan)

    assert result["kind"] == "by_category"
    assert len(result["rows"]) >= 1


@pytest.mark.asyncio
async def test_ask_db_list_transactions_by_account(db_session):
    account = Account(name="Wise Personal", institution="Wise")
    category = Category(name="Salary", parent_name="Income", type="income")
    db_session.add_all([account, category])
    await db_session.flush()

    db_session.add(
        Transaction(
            date=datetime(2026, 1, 15),
            description="January Salary",
            amount=3000.0,
            type="income",
            account_id=account.id,
            category_id=category.id,
        )
    )
    await db_session.commit()

    plan = await plan_ask_db_query(db_session, "show transactions from Wise Personal", limit=10)
    result = await run_ask_db_query(db_session, plan)

    assert result["kind"] == "transactions"
    assert len(result["rows"]) == 1
    assert result["rows"][0][2] == "January Salary"
