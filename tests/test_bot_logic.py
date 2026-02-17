import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, User, Message, Chat
from src.bot import start, accounts_command, categories_command, start_add, receive_details, account_callback

@pytest.fixture
def mock_update():
    update = MagicMock(spec=Update)
    update.effective_chat = MagicMock(spec=Chat)
    update.effective_chat.id = 12345
    update.message = MagicMock(spec=Message)
    update.message.reply_text = AsyncMock()
    update.callback_query = None
    return update

@pytest.fixture
def mock_context():
    context = MagicMock()
    context.args = []
    context.user_data = {}
    context.bot.send_message = AsyncMock()
    return context

@pytest.mark.asyncio
async def test_start_command(mock_update, mock_context):
    await start(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    assert "Welcome to Bluecoins Manager" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_accounts_list_empty(mock_update, mock_context):
    await accounts_command(mock_update, mock_context)
    args, kwargs = mock_update.message.reply_text.call_args
    assert "Account Management" in args[0]
    assert kwargs.get("parse_mode") == "Markdown"
    assert "reply_markup" in kwargs

@pytest.mark.asyncio
async def test_add_transaction_flow_start(mock_update, mock_context):
    res = await start_add(mock_update, mock_context)
    assert res == 0 # INPUT_DETAILS state
    mock_update.message.reply_text.assert_called_once()

@pytest.mark.asyncio
async def test_receive_details_invalid(mock_update, mock_context):
    mock_update.message.text = "InvalidFormat"
    res = await receive_details(mock_update, mock_context)
    assert res == 0 # INPUT_DETAILS (retry)
    assert "Invalid format" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_receive_details_valid(mock_update, mock_context):
    mock_update.message.text = "50.00 Lunch"
    
    # Mock list_accounts to return a dummy account so flow proceeds
    mock_account = MagicMock()
    mock_account.name = "TestBank"
    
    with patch("src.bot.list_accounts", new=AsyncMock(return_value=[mock_account])):
        res = await receive_details(mock_update, mock_context)
        
        assert res == 1 # SELECT_ACCOUNT state
        assert mock_context.user_data["add_amount"] == 50.0
        assert mock_context.user_data["add_desc"] == "Lunch"
        # Verify reply options
        assert "Select Account" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_account_edit_start_sets_pending_state(mock_update, mock_context):
    mock_query = MagicMock()
    mock_query.data = "acc_edit_1"
    mock_query.answer = AsyncMock()
    mock_query.edit_message_text = AsyncMock()
    mock_query.edit_message_reply_markup = AsyncMock()
    mock_update.callback_query = mock_query

    mock_account = MagicMock()
    mock_account.id = 1
    mock_account.name = "HSBC Main"
    mock_account.institution = "HSBC"

    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_account)
    mock_session_cm = MagicMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("src.bot.AsyncSessionLocal", return_value=mock_session_cm):
        await account_callback(mock_update, mock_context)

    state = mock_context.user_data["account_edit_state"]
    assert state["status"] == "wait_new_name"
    assert state["old_name"] == "HSBC Main"
    mock_query.edit_message_text.assert_called_once()
