# 🗺️ Product Roadmap

## Milestone 1: Core Foundation (MVP)

### Phase 1: Project Scaffold & Basic CLI
- **Goal**: Set up CLI structure and data storage
- **Status**: ✅ Complete

### Phase 2: Category Management System
- **Goal**: Implement flexible parent-child category structure
- **Status**: ✅ Complete

### Phase 3: Bank Format Handling
- **Goal**: Abstract out format mapping for banks
- **Status**: ✅ Complete

### Phase 4: Single Transaction Entry
- **Goal**: Core logic for manual entry and CLI exposure
- **Status**: ✅ Complete

### Phase 5: Database Migrations
- **Goal**: Database stability with Alembic
- **Status**: ✅ Complete

### Phase 6: Advanced Ingestion
- **Goal**: Support PDF bank statements and advanced parsing
- **Status**: ✅ Complete

## Milestone 2: Intelligent Assistant

### Phase 7: Telegram Bot Command Center
- **Goal**: Full CLI parity, interactive review queue, and AI chat.
- **Key Features**:
    - **Interactive Review**: Approve/Edit transactions via inline buttons.
    - **Chat**: Ask "Why?" for categorizations or "How much spent on X?".
    - **Commands**: Manage Accounts/Categories directly from chat.
- **Status**: ✅ Complete

### Phase 8: Cloud Database Migration
- **Goal**: Transition to cloud-hosted Postgres for cross-device access.
- **Objective**: Set up a free-tier cloud DB (e.g., Supabase, Neon) and migrate schema/data.
- **Status**: ✅ Complete

#### Phase 8.1: Historical Data Migration
- **Goal**: Migrate existing historical transactions from local/home DB to Supabase.
- **Objective**: Develop a synchronization or one-time migration script for historical data.
- **Status**: ⏳ Future Task

### Phase 9: Bot UX & Discoverability
- **Goal**: Improve bot usability with menus, help commands, and better formatting.
- **Key Features**:
    - **Command Menu**: Register bot commands with Telegram for easy access via the '/' button.
    - **Help Command**: Implement `/help` with detailed usage guides.
    - **Aesthetics**: Use rich Markdown, emojis, and consistent formatting for all bot responses.
- **Status**: ✅ Complete

### Phase 10: Advanced Resource Management
- **Goal**: Full CRUD management of AI rulebooks, categories, and transactions via bot.
- **Key Features**:
    - **Rulebook Management**: List, add, and delete AI Fine-tune examples and Knowledge chunks.
    - **Resource CRUD**: Commands to edit existing transactions and categories.
    - **Interactive Forms**: Use conversational flows to update database records.
- **Status**: ✅ Complete

### Phase 11: Conversational Intelligence (Intent Handling)
- **Goal**: Transition from commands to natural language for all configuration tasks.
- **Key Features**:
    - **Intent Classification**: Use LLM to detect if the user wants to add, list, or modify resources.
    - **Dynamic Action Dispatching**: Map "I want to add X account" to the internal add-account logic.
    - **Parameter Extraction**: Automatically extract names, amounts, and IDs from chat messages.
- **Status**: ✅ Complete

### Phase 12: Refinement & Verification
**Status**: ✅ Complete
- Implement comprehensive unit testing for ALL features.
- Generate synthetic "real-world" test data for logic verification.
- Mock Ollama/Telegram for isolated testing.
