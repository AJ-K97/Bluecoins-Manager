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
- **Status**: ✅ Complete (Implementation) / ⬜ Pending Manual Verification

### Phase 8: Cloud Database Migration
- **Goal**: Transition to cloud-hosted Postgres for cross-device access.
- **Objective**: Set up a free-tier cloud DB (e.g., Supabase, Neon) and migrate schema/data.
- **Status**: ✅ Complete

#### Phase 8.1: Historical Data Migration
- **Goal**: Migrate existing historical transactions from local/home DB to Supabase.
- **Objective**: Develop a synchronization or one-time migration script for historical data.
- **Status**: ⏳ Future Task

### Phase 9: Refinement & Verification
- **Goal**: Final testing, documentation, and polish.
- **Status**: ⬜ Not Started
