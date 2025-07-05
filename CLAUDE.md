# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Financial CLI Toolkit** - a Python application that converts bank transaction CSV files into standardized Bluecoins format. The current implementation is a single-file prototype that will evolve into a modular CLI toolkit with account management, category management, and optional ML-based categorization.

## Current Architecture

The project has been refactored into a modular CLI toolkit with subcommands:

- **Account Management** - Add, delete, and list financial institutions
- **Category Management** - Hierarchical categories with template support
- **File Conversion** - Convert bank CSV files to Bluecoins format
- **Interactive Categorization** - Learn and persist transaction categories

### Key Components

- **`main.py`** - Modular CLI with subcommands (account, category, convert)
- **`data/banks_config.json`** - Bank-specific column mappings and date formats
- **`data/accounts.json`** - List of configured financial institutions
- **`data/categories.json`** - Hierarchical category templates
- **`data/category_mapping.json`** - Persistent transaction categorization mappings

## Common Development Commands

### Running the Application

```bash
# View all available commands
python3 main.py --help

# Account management
python3 main.py account --list
python3 main.py account --add "CommBank"
python3 main.py account --delete "CommBank"

# Category management
python3 main.py category --list
python3 main.py category --add --type expense --parent "Technology" --child "Software"
python3 main.py category --delete --type expense --parent "Technology" --child "Software"

# Convert bank CSV to Bluecoins format
python3 main.py convert --bank HSBC --input input.csv --output output.csv --account-type "Bank" --account "HSBC Savings"
```

### Testing

The project currently has no automated tests. Testing is done manually by:

1. Running with sample CSV files
2. Verifying output format matches Bluecoins requirements
3. Checking category assignment persistence

## Current Implementation Status

✅ **COMPLETED SPRINTS:**
- **Sprint 1**: CLI structure with account management subcommands
- **Sprint 2**: Category management with hierarchical templates
- **Sprint 3**: Bank format handling and input parsing
- **Sprint 4**: File conversion engine with subcommand interface

❌ **REMAINING WORK:**
- **Sprint 5**: ML-based auto-categorization (optional)
- **Sprint 6**: Final testing and documentation

### Next Phase - ML Integration (Optional)

The remaining work involves adding ML capabilities:

```
model/
├── train_model.py        # ML model training
├── predict.py           # ML prediction logic
└── model.pkl            # Trained model
```

### Future ML Commands

```bash
# Train model from existing category mappings
python main.py train-model --dataset data/category_mapping.json

# Use ML for auto-categorization during conversion
python main.py convert --bank HSBC --input input.csv --output output.csv --use-ml
```

## Configuration Files

### Bank Configuration (`data/banks_config.json`)

Defines column mappings and parsing rules for each bank:

```json
{
  "banks": {
    "HSBC": {
      "date_column": "Transaction Date",
      "date_format": "%d %b %Y",
      "description_column": "Description",
      "amount_column": "Amount",
      "type_determination": "amount_sign"
    }
  }
}
```

### Account Management (`data/accounts.json`)

Simple list of configured financial institutions:

```json
["HSBC", "Wise", "CommBank"]
```

### Category Templates (`data/categories.json`)

Hierarchical category structure with template support:

```json
{
  "Bluecoins": {
    "expense": {
      "Transportation": ["Car Insurance", "Fuel", "Maintenance"],
      "Entertainment": ["App/Subscription", "Shopping", "Food"]
    },
    "income": {
      "Employer": ["Salary", "Bonus", "Benefits"]
    }
  }
}
```

### Transaction Mappings (`data/category_mapping.json`)

Persistent storage for learned transaction categorizations:

```json
{
  "transaction_description": {
    "parent_category": "Entertainment",
    "category": "Shopping"
  }
}
```

## Development Notes

- Python 3.x required with no external dependencies (yet)
- All configuration stored in `data/` directory for organization
- Interactive category assignment pauses execution for user input during conversion
- Modular CLI design allows easy extension of subcommands
- Date parsing uses bank-specific formats defined in configuration
- Amount handling converts to absolute values for Bluecoins compatibility
- CSV files are expected to be UTF-8 encoded with BOM support

## Key Patterns

- **Bank Format Abstraction**: Each bank has configurable column mappings rather than hardcoded parsing
- **Interactive Category Learning**: Unknown transactions prompt for categorization, building a persistent mapping
- **Flexible Amount Handling**: Supports both signed amounts and separate direction columns
- **Clean Data Processing**: Handles whitespace, non-breaking spaces, and formatting inconsistencies

## Future ML Integration

The planned ML component will:

- Train multi-output classifiers for parent/child category prediction
- Use TF-IDF vectorization on transaction descriptions
- Handle missing values and provide fallback to manual categorization
- Save trained models to `model/model.pkl` for reuse