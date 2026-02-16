import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.bot import handle_chat_message, handle_nl_dispatch
from src.database import Account
from sqlalchemy import select

@pytest.mark.asyncio
async def test_handle_chat_message_add_account_flow(db_session, mock_intent_ai, mock_bot_context):
    update, context = mock_bot_context
    
    # 1. First msg: "Add a new account"
    update.message.text = "Add a new account"
    mock_intent_ai.classify.return_value = {
        "intent": "ADD_ACCOUNT",
        "entities": {},
        "confidence": 0.9
    }
    
    with patch("src.bot.IntentAI", return_value=mock_intent_ai):
        with patch("src.bot.AsyncSessionLocal") as mock_session_factory:
            # Mock the context manager
            mock_session_factory.return_value.__aenter__.return_value = db_session
            
            await handle_chat_message(update, context)
            
            # Should ask for name
            assert context.user_data["nl_action"] == "ADD_ACCOUNT"
            assert context.user_data["nl_state"] == "WAIT_NAME"
            update.message.reply_text.assert_called_with("🏦 *Account Creation:* What's the name of the account?")

            # 2. Second msg: "Work Bank"
            update.message.text = "Work Bank"
            await handle_chat_message(update, context)
            
            assert context.user_data["nl_data"]["name"] == "Work Bank"
            assert context.user_data["nl_state"] == "WAIT_INST"
            
            # 3. Third msg: "HSBC"
            update.message.text = "HSBC"
            await handle_chat_message(update, context)
            
            # Should be saved
            res = await db_session.execute(select(Account).where(Account.name == "Work Bank"))
            acc = res.scalar_one_or_none()
            assert acc is not None
            assert acc.institution == "HSBC"
            assert context.user_data == {} # cleared

@pytest.mark.asyncio
async def test_handle_chat_message_add_transaction_prefilled(db_session, mock_intent_ai, mock_bot_context):
    update, context = mock_bot_context
    
    # Intent: "50 for lunch"
    update.message.text = "50 for lunch"
    mock_intent_ai.classify.return_value = {
        "intent": "ADD_TRANSACTION",
        "entities": {"amount": 50, "description": "lunch"},
        "confidence": 0.95
    }
    
    with patch("src.bot.IntentAI", return_value=mock_intent_ai):
        with patch("src.bot.AsyncSessionLocal") as mock_session_factory:
            mock_session_factory.return_value.__aenter__.return_value = db_session
            
            # Setup an account first
            db_session.add(Account(name="Wallet", institution="Cash"))
            await db_session.commit()
            
            await handle_chat_message(update, context)
            
            assert context.user_data["nl_action"] == "ADD_TRANSACTION"
            assert context.user_data["nl_data"]["amount"] == 50.0
            assert context.user_data["nl_state"] == "WAIT_ACC"
            
            # Check if it replied with account keyboard
            # The reply text contains MarkdownV2 escaped characters in some versions,
            # but let's just check the markup exists.
            args, kwargs = update.message.reply_text.call_args
            assert "Which account" in args[0]
            assert "reply_markup" in kwargs
