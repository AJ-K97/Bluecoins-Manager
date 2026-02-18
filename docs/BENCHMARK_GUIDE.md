# Benchmark Guide

This guide explains how to build, label, and score a transaction categorization benchmark dataset.

## Goal

Use benchmark rows as a repeatable test set for model quality and memory quality.

Outputs are normalized scores between `0` and `100`:
- `overall_score`: exact-match category/type accuracy on labeled rows.
- `expense_score`, `income_score`, `transfer_score`: per-type normalized accuracy.
- `memory_score`: accuracy on rows where memory signals exist.
- `memory_coverage`: how much of the benchmark had memory support.

## Commands Overview

```bash
python3 main.py benchmark import-csv --input /path/to/benchmark.csv --source-name batch-2026-02
# For bank-formatted files (Wise/HSBC/ANZ) or PDFs:
python3 main.py benchmark import-csv --input /path/to/file.pdf --bank ANZ --source-name anz-pdf
python3 main.py benchmark list --limit 50
python3 main.py benchmark review --source-file batch-2026-02 --unlabeled-only
python3 main.py benchmark learn-aliases --source-file batch-2026-02
python3 main.py benchmark score --model llama3.1:8b --source-file batch-2026-02 --show-errors 20
python3 main.py benchmark runs --limit 20
```

## 1) Import CSV into the benchmark dataset

```bash
python3 main.py benchmark import-csv --input /path/to/benchmark.csv --source-name my-batch
```

For PDF statements (and bank-formatted CSVs), pass `--bank`:

```bash
python3 main.py benchmark import-csv --input /path/to/statement.pdf --bank ANZ --source-name anz-statement
python3 main.py benchmark import-csv --input /path/to/Wise_transaction-history.csv --bank Wise --source-name wise-history
```

Behavior:
- Adds one benchmark row per CSV row.
- Auto-labels rows when category columns resolve unambiguously.
- Leaves unresolved rows as pending for manual review.
- If no explicit `description` column exists (common in Wise exports), importer derives description from fields such as `Target name`, `Source name`, `Reference`, and `Note`.

## 2) Inspect current rows

```bash
# Show first 100 rows
python3 main.py benchmark list --limit 100

# Show only rows that still need labels
python3 main.py benchmark list --unlabeled-only

# Filter by import source
python3 main.py benchmark list --source-file my-batch
```

Each row prints:
- benchmark row id
- source file + source row number
- type hint
- current expected label (or `UNLABELED`)
- description

## 3) Interactive one-by-one labeling (recommended)

```bash
python3 main.py benchmark review --source-file my-batch --unlabeled-only
```

Interactive actions per row:
- `Pick Category (tree)`
- `Mark as Transfer`
- `Clear Current Label`
- `Skip / Next`
- `Previous`
- `Quit Review`

### Search/filter while selecting category

When choosing a sub-category, the picker is fuzzy-search enabled.
Type to filter quickly by parent/category text (for example: `transport fuel`).

## 4) Label one row by command (non-interactive)

```bash
# Set parent/sub-category
python3 main.py benchmark label --id 42 --parent Transportation --category Fuel --type expense

# Mark as transfer
python3 main.py benchmark label --id 43 --set-transfer
```

## 5) Score the benchmark

```bash
python3 main.py benchmark score --model llama3.1:8b --show-errors 15

# Evaluate only one source batch
python3 main.py benchmark score --source-file my-batch
```

Scoring details:
- A non-transfer row is correct only when both predicted `type` and `category_id` match expected.
- A transfer row is correct when predicted `type` is `transfer`.
- Row-level predictions are persisted on benchmark rows (`last_predicted_*`).
- A run summary is persisted in benchmark run history.

## 6) Review score history

```bash
python3 main.py benchmark runs --limit 20
```

Use this to track score drift over time and compare models/prompt changes.

## 7) Learn merchant aliases from benchmark labels

Use this to strengthen merchant-key normalization from your curated benchmark labels.

```bash
python3 main.py benchmark learn-aliases --source-file my-batch
```

Options:
- `--limit N`: process only first N labeled rows
- `--include-transfer`: include transfer-labeled rows (default skips them)

## CSV Format

### Required column
- `description`

### Optional recognized columns
- `amount`
- `date` (`YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY`, `YYYY/MM/DD`)
- `type` (`expense`, `income`, `transfer`)
- `id` / `external_id` / `tx_id` / `reference`
- `parent_category`
- `category`
- `expected_type`

Header aliases are supported (e.g. `desc`, `transaction_type`, `sub_category`).

## Memory Score Definition

A row is considered memory-supported if at least one is present:
- pattern-key memory (`ai_memory`)
- exact verified precedent transaction
- category understanding profile

Then:
- `memory_score = (memory-supported correct / memory-supported total) * 100`
- `memory_coverage = (memory-supported total / evaluated total) * 100`

## Suggested Workflow

1. Import CSV batch.
2. Run `benchmark review --unlabeled-only` and finish labels.
3. Run `benchmark score` and inspect top errors.
4. Improve rules/memory/category understanding.
5. Re-run score and compare via `benchmark runs`.

## Optional Cleanup

If you want to clear benchmark data only:

```bash
python3 main.py db reset --tables category_benchmark_runs category_benchmark_items
```
