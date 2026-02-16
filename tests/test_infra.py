import pytest
from sqlalchemy import select
from src.database import Account

@pytest.mark.asyncio
async def test_db_session_fixture(db_session):
    """Verify that the db_session fixture works and is connected to a test db."""
    # Add a dummy account
    new_acc = Account(name="Test Infrastructure", institution="Pytest")
    db_session.add(new_acc)
    await db_session.flush()
    
    # Query it back
    res = await db_session.execute(select(Account).where(Account.name == "Test Infrastructure"))
    acc = res.scalar_one_or_none()
    
    assert acc is not None
    assert acc.institution == "Pytest"

@pytest.mark.asyncio
async def test_mock_llm_fixture(mock_llm):
    """Verify that the mock_llm fixture provides the expected response."""
    res = await mock_llm.answer(None, "hello")
    assert "food expense" in res["answer"]
    assert len(res["contexts"]) > 0

@pytest.mark.asyncio
async def test_mock_intent_ai_fixture(mock_intent_ai):
    """Verify that the mock_intent_ai fixture provides the expected response."""
    res = await mock_intent_ai.classify("Sushi")
    assert res["intent"] == "ADD_TRANSACTION"
    assert res["entities"]["amount"] == 50
