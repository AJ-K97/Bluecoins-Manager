# 🧪 Testing Guide

This document explains the testing infrastructure and strategy for the Bluecoins Manager project.

## 🚀 Quick Start

Ensure you have the virtual environment activated and dependencies installed:

```bash
# Install testing dependencies
./venv/bin/pip install pytest pytest-asyncio pytest-mock aiosqlite

# Run all tests
PYTHONPATH=. ./venv/bin/pytest tests/
```

---

## 🏗️ Test Suite Structure

The test suite is located in the `tests/` directory and is organized by component logic:

| File | Purpose | Key Coverage |
|------|---------|--------------|
| `conftest.py` | Shared Fixtures | Mock LLM, Mock Bot, In-memory DB |
| `test_infra.py` | Infrastructure | Fixture health, DB connectivity |
| `test_parsers.py` | Bank Parsing | HSBC & Wise CSV normalization |
| `test_commands.py` | Core Logic | Transaction CRUD, AI decision states |
| `test_bot_conversations.py` | Bot Flow | Multi-step NLP flows, State transitions |

---

## 🛠️ Mocking Strategy

To ensure tests are fast, reliable, and isolated from external services, we use several mocking strategies:

### 1. AI & LLM (`mock_llm`)
We mock the `LocalLLMPipeline`. Instead of calling a real Ollama server, the mock returns predictable responses based on the provided prompt context. This allows us to test categorization logic without needing GPU resources.

### 2. Telegram Bot (`mock_bot_context`)
The Telegram `Update` and `Context` objects are mocked using `unittest.mock`. Asynchronous methods like `reply_text` and `send_message` are replaced with `AsyncMock` to verify bot responses.

### 3. Database (`db_session`)
We use **SQLite in-memory** (`aiosqlite`) for testing. This provides a fresh, clean database for every test session without requiring a local PostgreSQL instance. The schema is automatically created and dropped by the `test_engine` fixture.

---

## 📊 Synthetic Data

We avoid using real financial data in the test suite. Instead, we use `tests/data_gen.py` to generate anonymized, realistic datasets:

- **`synthetic_hsbc.csv`**: Tests 3-column format with amount-sign negation logic.
- **`synthetic_wise.csv`**: Tests multi-column format with explicit `IN`/`OUT` direction.

To regenerate synthetic data:
```bash
python3 tests/data_gen.py
```

---

## 🔍 Writing New Tests

1. **Unit Logic**: Test functions in `src/commands.py` or `src/parser.py`. Use the `db_session` fixture.
2. **Bot Flows**: Use the `mock_bot_context` and `mock_intent_ai` fixtures. Patch `src.bot.IntentAI` and `src.bot.AsyncSessionLocal` to inject your mocks.
3. **Assertions**: Always verify both the database state (via `db_session`) and the user feedback (via `reply_text.assert_called_with`).

---
*Maintained by Antigravity*
