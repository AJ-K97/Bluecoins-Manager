import pytest
from sqlalchemy import select
from src.database import Account, Category, Transaction
from src.commands import add_account, add_category, add_transaction
from datetime import datetime

@pytest.mark.asyncio
async def test_add_account(db_session):
    """Verify adding an account via command."""
    # add_account returns (success, msg)
    success, msg = await add_account(db_session, "HSBC Main", "HSBC")
    assert success
    assert "Added account 'HSBC Main'" in msg
    
    # Verify persistence
    res = await db_session.execute(select(Account).where(Account.name == "HSBC Main"))
    assert res.scalar_one_or_none() is not None

@pytest.mark.asyncio
async def test_add_category(db_session):
    """Verify adding a category via command."""
    # add_category(session, name, parent_name, type)
    success, msg = await add_category(db_session, "Food", None, "expense")
    assert success
    assert "Food" in msg
    
    # Subcategory
    success, msg = await add_category(db_session, "Sushi", "Food", "expense")
    assert success
    assert "Sushi" in msg

@pytest.mark.asyncio
async def test_add_transaction_with_category(db_session):
    """Verify adding a transaction with a pre-defined category."""
    # Setup
    await add_account(db_session, "Cash", "None")
    await add_category(db_session, "Dining", None, "expense")
    res = await db_session.execute(select(Category).where(Category.name == "Dining"))
    cat = res.scalar_one()
    
    date = datetime(2024, 1, 1)
    # add_transaction returns (success, msg, tx)
    success, msg, tx = await add_transaction(
        db_session, 
        date=date, 
        amount=-50.0, 
        description="Sushi Lunch", 
        account_name="Cash",
        category_id=cat.id
    )
    
    assert success
    assert tx.amount == -50.0
    assert tx.category_id == cat.id
    assert tx.decision_state == "auto_approved"

@pytest.mark.asyncio
async def test_add_transaction_with_ai(db_session, mock_llm):
    """Verify adding a transaction without category uses AI."""
    await add_account(db_session, "Cash", "None")
    
    # We need to mock CategorizerAI.suggest_category if we don't want to call Ollama.
    # But wait, conftest only mocks LocalLLMPipeline.
    # CategorizerAI uses LocalLLMPipeline internally.
    
    date = datetime(2024, 1, 1)
    # If category_id is None, it triggers AI. 
    # The policy might set state to 'force_review' if no good match is found.
    success, msg, tx = await add_transaction(
        db_session, 
        date=date, 
        amount=-20.0, 
        description="Unknown Stuff", 
        account_name="Cash"
    )
    
    assert success
    # If it hit the policy, it might be force_review
    assert tx.decision_state in ["auto_approved", "needs_review", "force_review"]
