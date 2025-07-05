# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Financial CLI Toolkit** - a Python application that converts bank transaction CSV files into standardized Bluecoins format. The current implementation is a single-file prototype that will evolve into a modular CLI toolkit with account management, category management, and optional ML-based categorization.

## Current Architecture

The project is currently in an early prototype stage with a single `main.py` file that:

- Reads bank transaction CSV files using configurable column mappings
- Converts transactions to Bluecoins CSV format
- Handles interactive category assignment with persistent storage
- Supports multiple bank formats (HSBC, Wise) through `banks_config.json`

### Key Components

- **`main.py`** - Main conversion script with CLI interface
- **`banks_config.json`** - Bank-specific column mappings and date formats
- **`category_mapping.json`** - Persistent storage for transaction categorization

## Common Development Commands

### Running the Application

```bash
# Convert bank CSV to Bluecoins format
python3 main.py --bank HSBC --input input.csv --output output.csv --account-type "Bank" --account "HSBC Savings"

# View help
python3 main.py --help
```

### Testing

The project currently has no automated tests. Testing is done manually by:

1. Running with sample CSV files
2. Verifying output format matches Bluecoins requirements
3. Checking category assignment persistence

## Planned Architecture (Per spec.md)

The project will evolve into a modular structure with:

```
project_root/
├── main.py               # CLI entry point with subcommands
├── parser.py             # Bank format parsing logic
├── converter.py          # CSV conversion engine
├── config_manager.py     # JSON config management
├── model/
│   ├── train_model.py    # ML model training
│   ├── predict.py        # ML prediction logic
│   └── model.pkl         # Trained model
├── data/
│   ├── accounts.json     # Account management
│   ├── categories.json   # Category hierarchy
│   └── sample_dataset.csv
```

### Future CLI Commands

```bash
# Account management
python main.py account --add HSBC
python main.py account --delete HSBC

# Category management  
python main.py category --template Bluecoins --add "expense" --parent "Car" --child "Fuel"
python main.py category --template Bluecoins --delete --parent "Car" --child "Fuel"

# File conversion
python main.py convert --input input.csv --output output.csv --bank HSBC --template Bluecoins

# ML model training
python main.py train-model --dataset sample_dataset.csv
```

## Configuration Files

### Bank Configuration (`banks_config.json`)

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

### Category Mapping (`category_mapping.json`)

Stores user-defined transaction categorizations for consistency:

```json
{
  "transaction_description": {
    "parent_category": "Entertainment",
    "category": "Shopping"
  }
}
```

## Development Notes

- The current implementation requires Python 3.x with no external dependencies
- Interactive category assignment pauses execution for user input
- Date parsing uses specific formats defined per bank
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