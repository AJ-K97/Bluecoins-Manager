import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from src.database import Base
from src.bot import AsyncSessionLocal
import os
import json
from unittest.mock import AsyncMock, MagicMock

# Use an in-memory SQLite database
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create a test database engine."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest_asyncio.fixture
async def db_session(test_engine):
    """Provide a clean database session for each test."""
    async_session = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()

@pytest.fixture
def mock_llm():
    """Mock the LocalLLMPipeline to avoid calling Ollama."""
    mock = AsyncMock()
    # Default behavior: Categorize everything as 'Food' with 0.9 confidence
    mock.answer.return_value = {
        "answer": "This looks like a food expense.",
        "contexts": [{"content": "Date: 2024-01-01\nDesc: Sushi\nAmount: 50.00"}]
    }
    mock._embed_text.return_value = [0.1] * 768 # Dummy vector
    return mock

@pytest.fixture
def mock_intent_ai():
    """Mock IntentAI for predictable intent detection."""
    mock = AsyncMock()
    mock.classify.return_value = {
        "intent": "ADD_TRANSACTION",
        "entities": {"amount": 50, "description": "Sushi"},
        "confidence": 0.95
    }
    return mock

@pytest.fixture
def mock_bot_context():
    """Mock Telegram Update and Context objects."""
    update = MagicMock()
    update.message.text = "Mock message"
    update.message.reply_text = AsyncMock()
    update.effective_chat.id = 12345
    
    context = MagicMock()
    context.user_data = {}
    context.bot.send_chat_action = AsyncMock()
    context.bot.send_message = AsyncMock()
    return update, context
