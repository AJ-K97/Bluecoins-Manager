import pytest
from datetime import datetime
from sqlalchemy import select
from src.database import Transaction, AIMemory, Account, LLMFineTuneExample

@pytest.mark.asyncio
async def test_ai_memory_persistence_after_transaction_delete(db_session):
    """
    Verifies that deleting a transaction does not delete its linked AI memory
    (soft-detachment/ondelete=SET NULL).
    """
    # 1. Setup - Create Account, Transaction, and AI Memory
    acc = Account(name="Test Account", institution="Test Bank")
    db_session.add(acc)
    await db_session.flush()
    
    tx = Transaction(
        date=datetime.now(),
        description="Shell Oil",
        amount=50.0,
        type="expense",
        account_id=acc.id,
        is_verified=True
    )
    db_session.add(tx)
    await db_session.flush()
    
    memory = AIMemory(
        transaction_id=tx.id,
        pattern_key="SHELL",
        ai_reasoning="Matches known gas station pattern"
    )
    db_session.add(memory)
    
    finetune = LLMFineTuneExample(
        source_transaction_id=tx.id,
        prompt="Categorize Shell Oil",
        response="Gas"
    )
    db_session.add(finetune)
    await db_session.commit()
    
    # Verify they are linked
    assert memory.transaction_id == tx.id
    assert finetune.source_transaction_id == tx.id
    
    # 2. Action - Delete the Transaction
    await db_session.delete(tx)
    await db_session.commit()
    
    # 3. Verification - Related data should still exist but with NULLed IDs
    stmt_mem = select(AIMemory).where(AIMemory.pattern_key == "SHELL")
    result_mem = await db_session.execute(stmt_mem)
    persisted_mem = result_mem.scalar_one_or_none()
    
    assert persisted_mem is not None, "AI Memory should NOT have been deleted"
    assert persisted_mem.transaction_id is None, "AI Memory transaction_id should be NULL"
    
    stmt_ft = select(LLMFineTuneExample).where(LLMFineTuneExample.prompt == "Categorize Shell Oil")
    result_ft = await db_session.execute(stmt_ft)
    persisted_ft = result_ft.scalar_one_or_none()
    
    assert persisted_ft is not None, "Fine-tune example should NOT have been deleted"
    assert persisted_ft.source_transaction_id is None, "Fine-tune source_transaction_id should be NULL"
