
# 🧾 Financial CLI Toolkit — Project Specification

## Project Overview

You're building a **Python CLI toolkit** to process financial transaction data from CSV/Excel files exported by different banks. The tool should:

- Convert files into a standardized output format.
- Map descriptions to categories using a customizable ruleset and optionally ML model.
- Support multiple banks' CSV formats (e.g., HSBC, Wise).
- Allow local JSON-based configuration for `accounts` and `category mappings`.
- Be parameter-based and modular, so users can manage configs from CLI (`--add`, `--delete`, etc.).
- Be easily extendable with ML classification support for future automation.

---

## 🪜 Feature Breakdown

### 1. 💳 Account Management via CLI

**Data is stored in**: `data/accounts.json`

**Command Structure**:
```bash
python main.py account --add HSBC
python main.py account --delete HSBC
```

**Steps**:
- Add subparser group `account`.
- Support `--add` and `--delete` flags under `account`.
- Load/edit/save JSON file that stores accounts as a list:
```json
["HSBC", "Wise", "CommBank"]
```

---

### 2. 🗂 Category Management with Parent/Child Support

**Data stored in**: `data/categories.json`

**Support multiple templates** based on export format:
```json
{
  "Bluecoins": {
    "expense": {
      "Car": ["Fuel", "Maintenance", "Transport"],
      "Entertainment": ["Movies", "Dining"]
    },
    "income": {
      "Salary": ["Company A", "Company B"]
    }
  }
}
```

**Command Structure**:
```bash
python main.py category --template Bluecoins --add "expense" --parent "Car" --child "Fuel"
python main.py category --template Bluecoins --delete --parent "Car" --child "Fuel"
```

**Steps**:
- Add subparser group `category`.
- Accept `--template`, `--add`, `--delete`, `--parent`, `--child`, and `--type` (income/expense).
- Ensure correct nesting of categories.
- Create new templates if not found.

---

### 3. 📁 Parsing Input CSVs Based on Bank Format

**Supported banks**: `HSBC`, `Wise`

**Each bank has different column structure.**

**Steps**:
- Create a mapping for each bank format:
```python
BANK_FORMATS = {
    "HSBC": {"date": "Date", "account": "Account", "description": "Description", "credit": "Credit", "debit": "Debit"},
    "Wise": {"date": "Transaction Date", "account": "Account Name", "description": "Narrative", "credit": "Cr", "debit": "Dr"}
}
```

**Command Usage**:
```bash
python main.py convert --input input.csv --output output.csv --bank HSBC --template Bluecoins
```

- Use `pandas.read_csv` and rename columns accordingly.

---

### 4. 🧠 ML-Based Category Prediction (Optional for Now)

**Dataset Format**:
```
Description,ParentCategory,ChildCategory
"SAN CHURRO COCKBURN", Entertainment, Dining
"7 ELEVEN", Car, Fuel
```

**Steps**:

1. **Preprocess**:
   - Drop rows with missing descriptions or categories.
   - Use TF-IDF on `Description`.

2. **Train Multi-Output Model**:
```python
from sklearn.multioutput import MultiOutputClassifier
from sklearn.ensemble import RandomForestClassifier

clf = MultiOutputClassifier(RandomForestClassifier())
clf.fit(X_train_tfidf, y_train)
```

3. **Handle NaNs**:
   - Drop or fill missing values before training.

4. **Use Model**:
```python
parent_cat, child_cat = clf.predict([vectorizer.transform(["7 ELEVEN"])])
```

---

### 5. 🔄 Convert to Output Template

**Output Columns**:
```
Date, Account, Description, Credit, Debit, ParentCategory, Category
```

**Steps**:
- Parse using bank format mapping.
- Classify via manual mapping or ML.
- Export to output CSV.

---

### 6. 🧰 Suggested Project Structure

```
project_root/
│
├── main.py
├── parser.py
├── converter.py
├── config_manager.py
├── model/
│   ├── train_model.py
│   ├── predict.py
│   └── model.pkl
│
├── data/
│   ├── accounts.json
│   ├── categories.json
│   └── sample_dataset.csv
```

---

## ✅ Summary of Features

- ✅ Add/delete accounts and categories via CLI.
- ✅ Support for nested categories and types (income/expense).
- ✅ Multiple bank format parsing.
- ✅ Optional ML classification from descriptions.
- ✅ Standard output template for budgeting tools.
- ✅ JSON-based local config storage.
- ✅ Modular, extendable architecture.
