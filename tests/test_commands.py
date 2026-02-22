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
    undo_last_operation,
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

    assert rows[0] == [
        "(1)Type",
        "(2)Date",
        "(3)Item or Payee",
        "(4)Amount",
        "(5)Parent Category",
        "(6)Category",
        "(7)Account Type",
        "(8)Account",
        "(9)Notes",
        "(10) Label",
        "(11) Status",
        "(12) Split",
    ]
    row = rows[1]
    assert row[0] == "e"
    assert row[2] == "CORFIELD FRESH IGA"
    assert row[3] == "42.1"
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


def test_export_to_bluecoins_csv_item_or_payee_uses_merchant_only(tmp_path):
    tx = SimpleNamespace(
        type="expense",
        date=datetime(2024, 2, 10),
        description="PURCHASE CARD 8208 LIVINGSTON ORIENTAL CANNING",
        amount=-18.40,
        category=SimpleNamespace(parent_name="Food", name="Groceries"),
        category_id=3,
        account=SimpleNamespace(name="HSBC Main"),
    )
    output_path = tmp_path / "bluecoins_export_merchant_only.csv"

    success, _ = export_to_bluecoins_csv([tx], str(output_path))
    assert success

    with output_path.open(newline="") as f:
        rows = list(csv.reader(f))

    row = rows[1]
    assert row[2] == "LIVINGSTON ORIENTAL CANNING"


def _make_transfer_tx(
    tx_id,
    date,
    amount,
    description,
    account_name,
    raw_csv_row=None,
    account_id=None,
):
    return SimpleNamespace(
        id=tx_id,
        type="transfer",
        date=date,
        description=description,
        amount=amount,
        category=None,
        category_id=None,
        account=SimpleNamespace(name=account_name),
        account_id=account_id,
        raw_csv_row=raw_csv_row,
    )


def test_export_to_bluecoins_csv_exports_only_paired_transfers(tmp_path):
    output_path = tmp_path / "bluecoins_export_paired_transfers.csv"
    txs = [
        _make_transfer_tx(
            tx_id=102,
            date=datetime(2024, 1, 10, 9, 15),
            amount=100.0,
            description="TRANSFER FROM CHECKING",
            account_name="Savings",
            raw_csv_row='{"Direction":"IN","Amount":"100.00"}',
            account_id=2,
        ),
        _make_transfer_tx(
            tx_id=101,
            date=datetime(2024, 1, 10, 9, 0),
            amount=-100.0,
            description="TRANSFER TO SAVINGS",
            account_name="Checking",
            raw_csv_row='{"Direction":"OUT","Amount":"-100.00"}',
            account_id=1,
        ),
    ]

    success, msg = export_to_bluecoins_csv(txs, str(output_path))
    assert success
    assert msg.startswith("Exported 2 transactions to ")
    assert "Skipped" not in msg

    with output_path.open(newline="") as f:
        rows = list(csv.reader(f))

    assert len(rows) == 3


@pytest.mark.asyncio
async def test_undo_last_review_action_restores_transaction_note(db_session):
    await add_account(db_session, "Undo Test", "Test Bank")
    success, _msg, tx = await add_transaction(
        db_session,
        date=datetime(2024, 1, 2),
        amount=-22.0,
        description="Undo note change",
        account_name="Undo Test",
    )
    assert success
    assert tx.note is None

    ok, _ = await update_transaction_note(db_session, tx.id, "Temporary note")
    assert ok

    refreshed = await db_session.execute(select(Transaction).where(Transaction.id == tx.id))
    updated_tx = refreshed.scalar_one()
    assert updated_tx.note == "Temporary note"

    ok, msg = await undo_last_operation(db_session)
    assert ok
    assert "Undo complete" in msg

    restored = await db_session.execute(select(Transaction).where(Transaction.id == tx.id))
    restored_tx = restored.scalar_one()
    assert restored_tx.note is None


def test_export_to_bluecoins_csv_skips_unpaired_transfer_and_reports_id(tmp_path):
    output_path = tmp_path / "bluecoins_export_unpaired_transfer.csv"
    txs = [
        _make_transfer_tx(
            tx_id=201,
            date=datetime(2024, 1, 10, 9, 0),
            amount=-100.0,
            description="TRANSFER TO SAVINGS",
            account_name="Checking",
            raw_csv_row='{"Direction":"OUT","Amount":"-100.00"}',
            account_id=1,
        ),
    ]

    success, msg = export_to_bluecoins_csv(txs, str(output_path))
    assert success
    assert msg.startswith("Exported 0 transactions to ")
    assert "Skipped 1 unpaired transfers" in msg
    assert "#201(pair_not_found)" in msg

    with output_path.open(newline="") as f:
        rows = list(csv.reader(f))

    assert len(rows) == 1


def test_export_to_bluecoins_csv_skips_transfer_with_unknown_direction(tmp_path):
    output_path = tmp_path / "bluecoins_export_unknown_direction.csv"
    txs = [
        _make_transfer_tx(
            tx_id=301,
            date=datetime(2024, 1, 10, 9, 0),
            amount=100.0,
            description="Transfer movement",
            account_name="Checking",
            raw_csv_row='{"Reference":"ABC123"}',
            account_id=1,
        ),
    ]

    success, msg = export_to_bluecoins_csv(txs, str(output_path))
    assert success
    assert "Skipped 1 unpaired transfers" in msg
    assert "#301(direction_unknown)" in msg

    with output_path.open(newline="") as f:
        rows = list(csv.reader(f))

    assert len(rows) == 1


def test_export_to_bluecoins_csv_pairs_deterministically_with_collisions(tmp_path):
    output_path = tmp_path / "bluecoins_export_collision_pairing.csv"
    txs = [
        _make_transfer_tx(
            tx_id=1,
            date=datetime(2024, 3, 1, 8, 0),
            amount=-250.0,
            description="TRANSFER TO SAVINGS",
            account_name="A",
            raw_csv_row='{"Direction":"OUT","Amount":"-250.00"}',
            account_id=10,
        ),
        _make_transfer_tx(
            tx_id=2,
            date=datetime(2024, 3, 1, 8, 5),
            amount=-250.0,
            description="TRANSFER TO SAVINGS",
            account_name="B",
            raw_csv_row='{"Direction":"OUT","Amount":"-250.00"}',
            account_id=20,
        ),
        _make_transfer_tx(
            tx_id=3,
            date=datetime(2024, 3, 1, 8, 10),
            amount=250.0,
            description="TRANSFER FROM SAVINGS",
            account_name="A",
            raw_csv_row='{"Direction":"IN","Amount":"250.00"}',
            account_id=10,
        ),
        _make_transfer_tx(
            tx_id=4,
            date=datetime(2024, 3, 1, 8, 15),
            amount=250.0,
            description="TRANSFER FROM SAVINGS",
            account_name="C",
            raw_csv_row='{"Direction":"IN","Amount":"250.00"}',
            account_id=30,
        ),
        _make_transfer_tx(
            tx_id=5,
            date=datetime(2024, 3, 1, 8, 20),
            amount=-250.0,
            description="TRANSFER TO SAVINGS",
            account_name="D",
            raw_csv_row='{"Direction":"OUT","Amount":"-250.00"}',
            account_id=40,
        ),
    ]

    success, msg = export_to_bluecoins_csv(txs, str(output_path))
    assert success
    assert "Exported 4 transactions to " in msg
    assert "Skipped 1 unpaired transfers" in msg
    assert "#5(pair_not_found)" in msg

    with output_path.open(newline="") as f:
        rows = list(csv.reader(f))

    # header + 4 transfer rows
    assert len(rows) == 5

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
