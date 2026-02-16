# 📄 Financial CLI Toolkit - Specification Document [FINALIZED]

## 🎯 Objective

Develop a Python-based Command-Line Interface (CLI) toolkit that converts bank transaction data from various input formats (CSV/Excel) into a standard template used for budgeting or financial tracking. The toolkit allows managing categories and accounts, and optionally classifies transactions using machine learning.

---

## 🏗️ Functional Specifications

### Input

- CSV/Excel files exported from different banks (initially ING and HSBC).

### Output

- Standardized CSV format containing:
  - Date
  - Account
  - Description
  - Credit
  - Debit
  - Parent Category
  - Category

### Features

1. **Account Management**

   - Add or delete financial institutions (e.g., HSBC, Wise).
   - Stored in `data/accounts.json`.

2. **Category Management**

   - Support parent-child categories.
   - Category type: `expense` or `income`.
   - Allow multiple templates for different output standards (e.g., Bluecoins).
   - Stored in `data/categories.json`.

3. **Bank Format Parsing**

   - Support different column mappings for each bank.
   - Configurable for future extension.

4. **Transaction Conversion**

   - Read input CSV based on bank.
   - Apply account and category mappings.
   - Output to standard format CSV.

5. **ML-Based Auto-Categorization (Optional)**

   - Train on historical labeled dataset.
   - Predict `ParentCategory` and `Category` based on `Description`.

6. **CLI Interface**

   - Modular subcommands (`account`, `category`, `convert`, `train-model`).
   - Parameter-based input.

---

## 🚀 Sprints Overview

### Sprint 1: Project Scaffold & Basic CLI

**Goal:** Set up CLI structure and data storage

**Tasks:**

- Create `main.py` with argparse structure.
- Implement `account` subcommand with `--add` and `--delete`.
- Implement persistent storage in `data/accounts.json`.

---

### Sprint 2: Category Management System

**Goal:** Implement flexible parent-child category structure with templates

**Tasks:**

- Implement `category` subcommand.
- Add `--template`, `--add`, `--delete`, `--type`, `--parent`, `--child` options.
- Store in `data/categories.json`.

---

### Sprint 3: Bank Format Handling & Input Parsing

**Goal:** Abstract out format mapping for different banks

**Tasks:**

- Define `BANK_FORMATS` dictionary for Wise and HSBC.
- Implement parser that normalizes input CSV columns.
- Validate parser with sample data.

---

### Sprint 4: File Conversion Engine

**Goal:** Convert input into standardized template using CLI

**Tasks:**

- Implement `convert` subcommand.
- Load config for account and categories.
- Apply mappings and export to output CSV.

---

### Sprint 5: Machine Learning Integration (Optional)

**Goal:** Enable automated categorization using ML

**Tasks:**

- Create `train_model.py` to train multi-output classifier.
- Preprocess data: handle missing values, TF-IDF vectorization.
- Save model to disk (`model/model.pkl`).
- Load model during conversion if mapping fails.

---

### Sprint 7: Telegram Bot Command Center

**Goal:** Transform Telegram Bot into a full Command Center

**Core Features:**

1.  **Review Queue Management**
    - List pending transactions requiring user confirmation.
    - **Smart Category Selection**:
        - Display top 3-5 AI suggested categories as numbered options (e.g., "1. Food, 2. Groceries, 3. Custom").
        - User replies with just "1" to select.
        - Fallback to fuzzy text search if "Custom" is selected.
    - Inline buttons to `Approve`, `Edit Amount`, or `Skip`.
    - Batch approval for high-confidence predictions.

2.  **Conversational Intelligence (RAG-Enabled)**
    - **Architecture**: Leverages existing `LocalLLMPipeline` (Vector Store + Ollama).
    - **Interactive Coaching**:
        - When correcting a category, bot asks: "Why did you change this? I thought it was X."
        - User replies: "Because Vendor Y is actually for Z."
        - Bot saves this reasoning to `AIMemory` and `LLMSkill` for future reference.
    - **Re-indexing**: `/reindex` command to update vector store with latest transaction data.
    - **'Ask' Feature**:
        - Natural Language Queries: "How much did I spend on Coffee last month?" -> RAG retrieves relevant transaction chunks -> LLM summarizes.
        - Explainability: "Why is this 'Entertainment'?" -> Retrieving `AIMemory` reasoning.

3.  **CLI Parity**
    - Manage Accounts: `/account list`, `/account add` (wizard style).
    - Manage Categories: `/category list`, `/category add`.
    - Manual Element: `/add <amount> <desc>` -> Triggers AI suggestion flow with numbered options.

---

### Sprint 8: Final Testing & Documentation

**Goal:** Test, refine UX, and add documentation

**Tasks:**

- Add sample CSVs for HSBC & Wise.
- Write `README.md` for usage guide.
- Add CLI help messages and examples.
- Final code cleanup and modular refactor if needed.

---

## 📂 Suggested Project Structure

```
project_root/
├── main.py
├── parser.py
├── converter.py
├── config_manager.py
├── model/
│   ├── train_model.py
│   ├── predict.py
│   └── model.pkl
├── data/
│   ├── accounts.json
│   ├── categories.json
│   └── sample_dataset.csv
```

---

## 📌 Notes

- ML model training is optional but designed for future scalability.
- JSON configuration ensures portability and user control.
- CLI-first design for future GUI or API extension.

---

## ✅ Deliverables

- Functional CLI tool
- `README.md`
- JSON-based config files
- ML model and training dataset (if used)

