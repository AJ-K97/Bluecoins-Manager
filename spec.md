# 📄 Financial CLI Toolkit - Specification Document

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

   - Add or delete financial institutions (e.g., HSBC, ING).
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

- Define `BANK_FORMATS` dictionary for ING and HSBC.
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

### Sprint 6: Final Testing & Documentation

**Goal:** Test, refine UX, and add documentation

**Tasks:**

- Add sample CSVs for HSBC & ING.
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

