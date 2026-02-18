import pytest
import csv
from types import SimpleNamespace
from sqlalchemy import select
from src.database import Account, Category, Transaction
from src.commands import (
    add_account,
    add_category,
    add_transaction,
    export_to_bluecoins_csv,
    update_account,
    update_transaction_note,
)
from datetime import datetime
from unittest.mock import AsyncMock, patch

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

    date = datetime(2024, 1, 1)
    with patch("src.commands.CategorizerAI") as mock_ai_cls:
        mock_ai = mock_ai_cls.return_value
        mock_ai.suggest_category = AsyncMock(
            return_value=(None, 0.2, "No confident category match.", "expense")
        )

        # If category_id is None, add_transaction triggers AI.
        success, msg, tx = await add_transaction(
            db_session,
            date=date,
            amount=-20.0,
            description="Unknown Stuff",
            account_name="Cash",
        )
    
    assert success
    assert tx.decision_state in ["auto_approved", "needs_review", "force_review"]

@pytest.mark.asyncio
async def test_update_account_renames_and_updates_linked_transactions(db_session):
    await add_account(db_session, "Old Name", "HSBC")
    date = datetime(2024, 1, 1)
    success, _, tx = await add_transaction(
        db_session,
        date=date,
        amount=-10.0,
        description="Coffee",
        account_name="Old Name",
    )
    assert success
    original_account_id = tx.account_id

    success, msg, updated_count = await update_account(
        db_session,
        current_name="Old Name",
        new_name="New Name",
    )

    assert success
    assert "Updated account 'Old Name' to 'New Name'." == msg
    assert updated_count == 1

    tx_res = await db_session.execute(select(Transaction).where(Transaction.id == tx.id))
    updated_tx = tx_res.scalar_one()
    assert updated_tx.account_id == original_account_id

    acc_res = await db_session.execute(select(Account).where(Account.id == original_account_id))
    updated_acc = acc_res.scalar_one()
    assert updated_acc.name == "New Name"


def test_export_to_bluecoins_csv_summarizes_item_and_cleans_notes(tmp_path):
    tx = SimpleNamespace(
        type="expense",
        date=datetime(2024, 1, 2),
        description="VISA DEBIT CORFIELD FRESH IGA 28JAN26 23:30:46 REF12345678",
        amount=-42.10,
        category=SimpleNamespace(parent_name="Food", name="Groceries"),
        category_id=1,
        account=SimpleNamespace(name="HSBC Main"),
    )
    output_path = tmp_path / "bluecoins_export.csv"

    success, _ = export_to_bluecoins_csv([tx], str(output_path))
    assert success

    with output_path.open(newline="") as f:
        rows = list(csv.reader(f))

    row = rows[1]
    assert row[2] == "CORFIELD FRESH IGA"
    assert row[8] == "CORFIELD FRESH IGA"


def test_export_to_bluecoins_csv_prefers_user_note_for_item_or_payee(tmp_path):
    tx = SimpleNamespace(
        type="expense",
        date=datetime(2024, 1, 2),
        description="VISA DEBIT OFFICEWORKS 28JAN26 23:30:46 REF12345678",
        note="Desk organizer and pens",
        amount=-25.0,
        category=SimpleNamespace(parent_name="Shopping", name="Office Supplies"),
        category_id=2,
        account=SimpleNamespace(name="HSBC Main"),
    )
    output_path = tmp_path / "bluecoins_export_with_note.csv"

    success, _ = export_to_bluecoins_csv([tx], str(output_path))
    assert success

    with output_path.open(newline="") as f:
        rows = list(csv.reader(f))

    row = rows[1]
    assert row[2] == "Desk organizer and pens"
    assert row[8] == "Desk organizer and pens | Source: OFFICEWORKS"


@pytest.mark.asyncio
async def test_update_transaction_note(db_session):
    await add_account(db_session, "Cash", "None")
    date = datetime(2024, 1, 1)
    success, _, tx = await add_transaction(
        db_session,
        date=date,
        amount=-10.0,
        description="Coffee",
        account_name="Cash",
    )
    assert success

    success, msg = await update_transaction_note(db_session, tx.id, "Team catch-up coffee")
    assert success
    assert msg == "Transaction note updated."

    tx_res = await db_session.execute(select(Transaction).where(Transaction.id == tx.id))
    updated_tx = tx_res.scalar_one()
    assert updated_tx.note == "Team catch-up coffee"
