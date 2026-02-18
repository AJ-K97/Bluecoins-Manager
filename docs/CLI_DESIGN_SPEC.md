# CLI Design Spec (Interactive)

This spec defines a consistent visual and interaction baseline for the interactive terminal UX.

## Goals
- Improve readability and hierarchy without changing business behavior.
- Keep the UI fast and keyboard-first.
- Use predictable output blocks so users can scan quickly.

## Visual System
- Palette:
  - Primary: blue (`#1d4ed8`)
  - Surface/muted: slate (`#e2e8f0`, `#94a3b8`)
  - Success: green (`#22c55e`)
  - Warning: amber (`#f59e0b`)
  - Error/low confidence: red (`#f87171`)
- Text roles:
  - `title`: screen identity
  - `meta`: progress/status summary
  - `table_header`: column labels
  - `row_even` / `row_odd`: scan-friendly rows
  - `selected_row`: active focus
  - `details_title` / `details_text`: expanded context
  - `footer` / `hotkey`: action legend

## Layout Contract
- Header:
  - App + screen name.
  - Current progress (`verified/total`, pending, progress bar).
- Body:
  - Fixed-column table for transaction list.
  - Stable field order: status, type, date, description, amount, confidence, category.
- Details pane:
  - Selected transaction metadata and AI rationale.
  - One-line truncation for long values to avoid noisy wraps.
- Footer:
  - Keybindings rendered as highlighted tokens + short action labels.

## Interaction Rules
- All actions remain keyboard accessible.
- Keep existing key bindings unless there is a migration plan.
- No destructive action should execute without user confirmation in parent flow.

## Content Rules
- Use concise labels (`OK`, `AI`, `IN`, `OUT`, `XFR`).
- Always show confidence as a percent with color bands:
  - high: >= 85
  - medium: >= 60 and < 85
  - low: < 60
- Truncate long fields with ellipsis to preserve alignment.

## Baseline Implemented
- `src/tui.py` transaction review screen is now the baseline implementation for this spec.
