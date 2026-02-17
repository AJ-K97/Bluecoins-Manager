import pytest
from sqlalchemy import select

from src.commands import add_account, add_category, add_transaction
from src.database import Category


@pytest.mark.asyncio
async def test_manual_add(db_session):
    success, msg = await add_account(db_session, "TestAccount", "TestBank")
    assert success
    assert "Added account 'TestAccount'" in msg

    success, msg = await add_category(db_session, "ManualAdd", "TestParent", "expense")
    assert success
    res = await db_session.execute(select(Category).where(Category.name == "ManualAdd"))
    cat = res.scalar_one()

    success, msg, tx = await add_transaction(
        db_session,
        date="2025-01-01",
        amount=123.45,
        description="Test Manual Entry via Script",
        account_name="TestAccount",
        category_id=cat.id,
    )

    assert success
    assert tx.id is not None
    assert tx.amount == 123.45
    assert tx.description == "Test Manual Entry via Script"
