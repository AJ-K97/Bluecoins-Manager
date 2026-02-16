# SPEC.md — Project Specification

> **Status**: `FINALIZED`

## Vision
A local-first, privacy-focused financial management toolkit that leverages Local LLMs (RAG) to automate transaction categorization. It bridges the gap between raw bank exports and structured financial data, offering a powerful CLI/TUI for review and management without sending improved financial data to the cloud.

## Goals
1. **Universal Ingestion**: Parse and normalize data from various banks (HSBC, Wise, etc.) into a unified format. Support **CSV** and **PDF** (cleaned of non-transactional noise).
2. **Intelligent Categorization**: Use a Local LLM (Llama 3) with RAG to learn from past decisions and categorize new transactions with high accuracy.
3. **Interactive Review**: Provide a TUI (Text User Interface) and **Telegram Bot** for efficient human-in-the-loop verification.
4. **Entity Management**: CRUD operations for Accounts and Categories via CLI.
5. **Unified Access**: Full feature parity between CLI and Telegram Bot (including single transaction entry).
6. **Deterministic Rules**: Regex-based overrides for instant, zero-cost categorization of recurring transactions.

## Non-Goals (Out of Scope)
- Cloud syncing (Local-first only)
- Mobile App (CLI/Desktop focus)
- Real-time banking APIs (Bank feed integration via Plaid/Yodlee is not currently planned; file-based only)

## Users
Technical users who prefer CLI tools, value privacy, and want "smart" budgeting without manual spreadsheet entry.

## Constraints
- **OS**: Linux/macOS
- **Runtime**: Python 3.10+
- **Database**: PostgreSQL (Local)
- **AI**: Ollama (running locally)
- **PDF Processing**: `pypdf` or similar library

## Success Criteria
- [x] CLI structure implemented (`main.py`)
- [x] Database schema defined (`src/database.py`)
- [x] LLM RAG pipeline active (`src/local_llm.py`)
- [x] Interactive TUI for review (`src/interactive.py`)
- [ ] Comprehensive test coverage for all parsers
- [ ] Refined categorization rules and conflict handling
