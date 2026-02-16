# Research Phase 6: Advanced Ingestion (PDF)

## Capability Analysis
- **Goal**: Ingest PDF bank statements.
- **Library**: `pypdf` (lightweight, standard).
- **Current State**: `BankParser` handles CSVs only.

## Integration Strategy
- **Dependency**: Add `pypdf` to `requirements.txt`.
- **Architecture**:
    - `src/parser.py` should route based on file extension.
    - If `.pdf`: Use `PDFParser` (new class).
    - If `.csv`: Use existing `BankParser` logic.

## Text Extraction & Noise Cleaning
PDFs often contain headers/footers ("Page 1 of 3", "Statement Date...").
- **Header/Footer Removal**:
    - *Simple*: Regex for common patterns (dates, page numbers).
    - *Advanced*: Analyze all pages, identify lines that repeat identically on >80% of pages.
- **Transaction Extraction**:
    - PDF text extraction returns raw strings.
    - Need regex to find transaction lines (Date + Description + Amount).
    - *Challenge*: Multi-line descriptions.
    - *Soluton*: Regex `^\d{2}/\d{2}/\d{4} ...` to identify start of entry. Merge subsequent lines until next date found.

## Plan Breakdown
1. **Plan 6.1: Core PDF Support**
    - Add `pypdf`.
    - Implement `extract_text_from_pdf`.
    - Create `PDFTransactionParser` (Regex-based).
2. **Plan 6.2: Noise Cleaning & Auto-detect**
    - Implement `NoiseCleaner` (header/footer stripper).
    - Update `BankParser` to switch strategies automatically.
