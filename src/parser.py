import csv
import json
import os
from datetime import datetime
import re
import pypdf
from src.bank_config import load_banks_payload


def format_pdf_debug_report(debug_data, mode="both", max_lines=None):
    lines = []
    source_path = debug_data.get("file_path", "")
    lines.append(f"PDF Debug Report")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if source_path:
        lines.append(f"Source: {source_path}")
    lines.append("")

    stats = debug_data.get("stats", {})
    lines.append("Stats")
    lines.append(f"- pages: {stats.get('page_count', 0)}")
    lines.append(f"- raw lines: {stats.get('raw_line_count', 0)}")
    cleaned_count = stats.get("cleaned_line_count")
    if cleaned_count is not None:
        lines.append(f"- cleaned lines: {cleaned_count}")
    lines.append("")

    show_raw = mode in {"both", "raw"}
    show_cleaned = mode in {"both", "cleaned"}

    if show_raw:
        pages = debug_data.get("pages", [])
        for page in pages:
            page_idx = page.get("page_index", 0) + 1
            lines.append(f"--- Page {page_idx} Raw Text ---")
            raw_text = page.get("raw_text") or ""
            lines.append(raw_text if raw_text.strip() else "[empty]")
            lines.append("")

    if show_cleaned:
        cleaned_lines = debug_data.get("cleaned_lines", [])
        lines.append("--- Cleaned Lines ---")
        if not cleaned_lines:
            lines.append("[none]")
        else:
            for i, line in enumerate(cleaned_lines, start=1):
                lines.append(f"{i:04d} | {line}")
        lines.append("")
        if not cleaned_lines:
            lines.append("Note: No cleaned lines found. If this is a scanned PDF, OCR may be required.")
            lines.append("")

    report = "\n".join(lines).rstrip() + "\n"
    if max_lines is None or max_lines <= 0:
        return report

    report_lines = report.splitlines()
    if len(report_lines) <= max_lines:
        return report

    truncated = report_lines[:max_lines]
    truncated.append("")
    truncated.append(f"... [truncated {len(report_lines) - max_lines} lines; use --output for full report]")
    return "\n".join(truncated) + "\n"


def format_pdf_blocks_report(blocks_data, max_blocks=None):
    lines = []
    source_path = blocks_data.get("file_path", "")
    bank_name = blocks_data.get("bank_name", "")
    lines.append("PDF Block Debug Report")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if source_path:
        lines.append(f"Source: {source_path}")
    if bank_name:
        lines.append(f"Bank: {bank_name}")
    lines.append(f"Blocks: {len(blocks_data.get('blocks', []))}")
    lines.append("")

    blocks = blocks_data.get("blocks", [])
    if max_blocks is not None and max_blocks > 0:
        blocks = blocks[:max_blocks]

    for i, block in enumerate(blocks, start=1):
        lines.append(f"=== Block {i:03d} ===")
        lines.append(f"Date token: {block.get('date_str', '')}")
        lines.append(f"Amounts line: {block.get('amounts_text', '')}")
        lines.append(f"Description: {block.get('description', '')}")
        parsed = block.get("parsed")
        if parsed:
            lines.append(
                f"Parsed -> date={parsed.get('date')} amount={parsed.get('amount')} type={parsed.get('type')}"
            )
        lines.append("Raw lines:")
        for ln in block.get("block_lines", []):
            lines.append(f"  - {ln}")
        lines.append("")

    total = len(blocks_data.get("blocks", []))
    if max_blocks is not None and max_blocks > 0 and total > max_blocks:
        lines.append(f"... [truncated {total - max_blocks} blocks; increase --max-blocks]")

    return "\n".join(lines).rstrip() + "\n"


class BankParser:
    def __init__(self, config_path="data/banks_config.json"):
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")

        self.config = load_banks_payload(config_path)["banks"]

    def _parse_date(self, date_str, formats, fallback_year=None):
        for fmt in formats:
            try:
                # Handle %b manually if needed? Standard library handles English locale usually.
                parsed = datetime.strptime(date_str, fmt)
                if parsed.year == 1900:
                    parsed = parsed.replace(year=fallback_year or datetime.now().year)
                return parsed
            except ValueError:
                continue
        return None

    def _extract_year_hint(self, text):
        if not text:
            return None
        match = re.search(r"(19|20)\d{2}", text)
        if not match:
            return None
        try:
            return int(match.group(0))
        except ValueError:
            return None

    def _to_amount(self, amount_str):
        if amount_str is None:
            return None
        cleaned = str(amount_str).strip()
        if not cleaned:
            return None
        cleaned = cleaned.replace("$", "").replace(",", "").replace("CR", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _normalize_spaces(self, text):
        return re.sub(r"\s+", " ", (text or "").strip())

    def _infer_type_from_description(self, description, default_to_expense=False):
        desc = (description or "").upper()
        income_hints = [
            "PAYMENT FROM", "TRANSFER FROM", "SALARY", "PAYROLL", "BONUS", "REFUND", "INTEREST", "CREDIT",
        ]
        expense_hints = [
            "PAYMENT TO", "TRANSFER TO", "VISA DEBIT", "DEBIT PURCHASE", "WITHDRAWAL", "FEE", "CHARGE",
        ]

        if any(x in desc for x in income_hints):
            return "income"
        if any(x in desc for x in expense_hints):
            return "expense"
        return "expense" if default_to_expense else "income"

    def _parse_amounts_line(self, amounts_text, description, prefer_debit_when_single=False):
        nums = re.findall(r"\$?([\d,]+\.\d{2})", amounts_text or "")
        if len(nums) < 2:
            return None, None

        vals = [self._to_amount(n) for n in nums]
        vals = [v for v in vals if v is not None]
        if len(vals) < 2:
            return None, None

        # 2 values: [txn_amount, balance]
        if len(vals) == 2:
            txn_amount = abs(vals[0])
            tx_type = self._infer_type_from_description(
                description,
                default_to_expense=prefer_debit_when_single,
            )
            return txn_amount, tx_type

        # 3+ values: [credit, debit, balance] (take the last 3 if noisy line)
        credit, debit, _balance = vals[-3], vals[-2], vals[-1]
        if credit > 0 and debit == 0:
            return abs(credit), "income"
        if debit > 0 and credit == 0:
            return abs(debit), "expense"

        # Ambiguous columns; use description hints.
        inferred = self._infer_type_from_description(description, default_to_expense=prefer_debit_when_single)
        chosen = debit if inferred == "expense" else credit
        return abs(chosen), inferred

    def _parse_pdf_multiline_table(self, file_path, cfg):
        debug_data = self.extract_pdf_debug(file_path, apply_cleaning=True)
        lines = debug_data.get("cleaned_lines", [])
        blocks = self._extract_multiline_blocks(lines, cfg)
        transactions = []
        for block in blocks:
            parsed = self._build_transaction_from_block(block, cfg)
            if parsed:
                transactions.append(parsed)
        return transactions

    def _extract_multiline_blocks(self, lines, cfg):
        tx_start_re = re.compile(
            cfg.get("pdf_tx_start_regex", r"^(?P<date>\d{1,2}\s+[A-Za-z]{3})(?:\s+|$)(?P<rest>.*)$"),
            re.IGNORECASE,
        )
        amount_line_re = re.compile(
            cfg.get("pdf_amount_balance_regex", r"^\$?[\d,]+\.\d{2}(?:\s+\$?[\d,]+\.\d{2}){1,2}$"),
            re.IGNORECASE,
        )
        ignore_patterns = [re.compile(p, re.IGNORECASE) for p in cfg.get("pdf_ignore_line_patterns", [])]
        blocks = []

        current = None

        def finalize_current():
            nonlocal current
            if not current:
                current = None
                return
            if current.get("amounts_text"):
                blocks.append(current)
            current = None

        for raw_line in lines:
            line = (raw_line or "").strip()
            if not line:
                continue
            if any(p.search(line) for p in ignore_patterns):
                continue

            m_start = tx_start_re.match(line)
            if m_start:
                finalize_current()
                date_str = (m_start.group("date") or "").strip()
                rest = (m_start.group("rest") or "").strip()
                current = {
                    "date_str": date_str,
                    "desc_parts": [],
                    "amounts_text": None,
                    "block_lines": [line],
                }
                if rest:
                    # Handle single-line rows with amounts in the same line.
                    inline = re.search(r"(.*?)(\$?[\d,]+\.\d{2}(?:\s+\$?[\d,]+\.\d{2}){1,2})$", rest)
                    if inline:
                        desc_part = (inline.group(1) or "").strip()
                        current["amounts_text"] = (inline.group(2) or "").strip()
                        if desc_part:
                            current["desc_parts"].append(desc_part)
                        finalize_current()
                    else:
                        current["desc_parts"].append(rest)
                continue

            if not current:
                continue

            current["block_lines"].append(line)
            if amount_line_re.match(line):
                current["amounts_text"] = line
                finalize_current()
                continue

            if re.match(r"^Effective Date\s+\d{1,2}/\d{1,2}/\d{4}$", line, re.IGNORECASE):
                # Keep it in block_lines for year hint, but omit from description text.
                continue

            current["desc_parts"].append(line)

        finalize_current()
        return blocks

    def _build_transaction_from_block(self, block, cfg):
        description = self._normalize_spaces(" ".join(block.get("desc_parts", [])))
        if not description:
            return None

        block_text = " ".join(block.get("block_lines", []))
        year_hint = self._extract_year_hint(block_text)
        date_val = self._parse_date(
            block.get("date_str", ""),
            cfg["date_formats"],
            fallback_year=year_hint or datetime.now().year,
        )
        if not date_val:
            return None

        amount, tx_type = self._parse_amounts_line(
            block.get("amounts_text"),
            description,
            prefer_debit_when_single=cfg.get("pdf_prefer_debit_when_single_amount", False),
        )
        if amount is None or tx_type is None:
            return None

        return {
            "date": date_val,
            "description": description,
            "amount": amount,
            "type": tx_type,
            "raw_csv_row": " | ".join(block.get("block_lines", [])),
        }

    def parse(self, bank_name, file_path):
        """
        Parses a bank CSV/PDF file and returns a list of standardized transaction dictionaries.
        """
        if bank_name not in self.config:
            raise ValueError(f"Bank '{bank_name}' not supported. Available: {list(self.config.keys())}")
        
        cfg = self.config[bank_name]
        
        if file_path.lower().endswith('.pdf'):
            return self.parse_pdf(bank_name, file_path, cfg)
        
        transactions = []
        
        try:
            f = open(file_path, "r", encoding="utf-8-sig")
        except PermissionError as e:
            raise ValueError(
                f"Permission denied reading '{file_path}'. "
                "Move/copy the file into this project folder (or uploads/) and retry."
            ) from e
        except OSError as e:
            raise ValueError(f"Unable to open file '{file_path}': {e}") from e

        with f:
            reader = csv.DictReader(f)
            # Normalize header names (strip whitespace)
            if reader.fieldnames:
                reader.fieldnames = [name.strip() for name in reader.fieldnames]
            
            for row in reader:
                # Clean up row keys and values
                clean_row = {
                    k.strip(): v.strip().replace('\xa0', ' ').replace('  ', ' ')
                    for k, v in row.items() if k and v
                }
                
                try:
                    # Date Parsing
                    date_val = self._parse_date(
                        clean_row[cfg["date_column"]],
                        cfg["date_formats"],
                        fallback_year=datetime.now().year,
                    )
                    if not date_val:
                        # Skip invalid dates
                        continue

                    # Description
                    desc = clean_row[cfg["description_column"]]

                    # Amount Parsing
                    amount_str = clean_row[cfg["amount_column"]].replace(",", "")
                    try:
                        raw_amount = float(amount_str)
                        amount = raw_amount
                        if cfg.get("negate_amounts", False):
                            amount = -amount
                    except ValueError:
                        continue # Skip invalid amounts

                    # Type Determination
                    tx_type = "expense" # Default
                    if cfg.get("type_determination") == "amount_sign":
                        # Determine direction from source sign before normalization/negation.
                        if raw_amount > 0:
                            tx_type = "income"
                        else:
                            tx_type = "expense"
                    
                    elif cfg.get("type_determination") == "direction_column":
                        direction = clean_row.get(cfg["direction_column"])
                        if direction == cfg["direction_in_value"]:
                            tx_type = "income"
                        elif direction == cfg["direction_out_value"]:
                            tx_type = "expense"

                    transactions.append({
                        "date": date_val,
                        "description": desc,
                        "amount": amount,
                        "type": tx_type,
                        "raw_csv_row": json.dumps(clean_row, default=str)
                    })
                    
                except KeyError:
                    # Missing required columns in this row
                    continue
        
        return transactions

    def parse_pdf(self, bank_name, file_path, cfg):
        """
        Parses a PDF file using pypdf and regex.
        """
        if cfg.get("pdf_parser") == "multiline_table":
            return self._parse_pdf_multiline_table(file_path, cfg)

        if "pdf_regex" not in cfg:
            raise ValueError(f"Bank '{bank_name}' does not have 'pdf_regex' configured.")
            
        pattern = re.compile(cfg["pdf_regex"], re.IGNORECASE)
        transactions = []
        
        try:
            reader = pypdf.PdfReader(file_path)
            full_text = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    full_text.extend(text.split('\n'))
            
            # Basic Line Parsing
            # Current limitation: Assumes single line transactions or regex captures needed parts
            # Future (Plan 6.2): Add noise cleaning here
            
            # Noise Cleaning (Plan 6.2)
            cleaned_lines = self.clean_noise(full_text)
            
            for line in cleaned_lines:
                line = line.strip()
                if not line:
                    continue
                    
                match = pattern.search(line)
                if match:
                    date_group = cfg.get("pdf_date_group", 1)
                    description_group = cfg.get("pdf_description_group", 2)
                    amount_group = cfg.get("pdf_amount_group", 3)
                    credit_group = cfg.get("pdf_credit_group")
                    debit_group = cfg.get("pdf_debit_group")

                    date_str = (match.group(date_group) or "").strip()
                    desc = (match.group(description_group) or "").strip()
                    if not date_str or not desc:
                        continue

                    # Date
                    year_hint = self._extract_year_hint(line)
                    date_val = self._parse_date(
                        date_str,
                        cfg["date_formats"],
                        fallback_year=year_hint or datetime.now().year,
                    )
                    if not date_val:
                        continue

                    amount = None
                    tx_type = "expense"

                    # Debit/Credit split columns are common in PDF exports.
                    if credit_group or debit_group:
                        credit_raw = (match.group(credit_group) or "").strip() if credit_group else ""
                        debit_raw = (match.group(debit_group) or "").strip() if debit_group else ""
                        credit_amount = self._to_amount(credit_raw)
                        debit_amount = self._to_amount(debit_raw)
                        desc_upper = desc.upper()
                        debit_hint = "DEBIT" in desc_upper
                        credit_hint = "CREDIT" in desc_upper

                        if debit_amount is not None:
                            amount = abs(debit_amount)
                            tx_type = "expense"
                        elif credit_amount is not None:
                            amount = abs(credit_amount)
                            if debit_hint:
                                tx_type = "expense"
                            elif credit_hint:
                                tx_type = "income"
                            elif cfg.get("pdf_prefer_debit_when_single_amount", False):
                                tx_type = "expense"
                            else:
                                tx_type = "income"
                        else:
                            continue
                    else:
                        raw = match.group(amount_group) if amount_group else None
                        raw_amount = self._to_amount(raw)
                        if raw_amount is None:
                            continue
                        amount = raw_amount
                        if cfg.get("negate_amounts", False):
                            amount = -amount
                        tx_type = "income" if amount > 0 else "expense"

                    transactions.append({
                        "date": date_val,
                        "description": desc,
                        "amount": amount,
                        "type": tx_type,
                        "raw_csv_row": line
                    })
                    
            return transactions
            
        except PermissionError as e:
            raise ValueError(
                f"Permission denied reading '{file_path}'. "
                "Move/copy the PDF into this project folder (or uploads/) and retry."
            ) from e
        except Exception as e:
            raise ValueError(f"Failed to parse PDF: {e}")

    def extract_pdf_debug(self, file_path, apply_cleaning=True):
        try:
            reader = pypdf.PdfReader(file_path)
        except PermissionError as e:
            raise ValueError(
                f"Permission denied reading '{file_path}'. "
                "Move/copy the PDF into '/Users/ajith/Documents/Bluecoins-Manager/uploads/' "
                "or grant Terminal/Desktop access and retry."
            ) from e
        except Exception as e:
            raise ValueError(f"Unable to read PDF '{file_path}': {e}") from e

        pages = []
        all_raw_lines = []
        for idx, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            raw_lines = text.split("\n") if text else []
            all_raw_lines.extend(raw_lines)
            pages.append(
                {
                    "page_index": idx,
                    "raw_text": text,
                    "raw_lines": raw_lines,
                }
            )

        debug_data = {
            "file_path": file_path,
            "pages": pages,
            "stats": {
                "page_count": len(pages),
                "raw_line_count": len(all_raw_lines),
                "cleaned_line_count": 0,
            },
        }

        if apply_cleaning:
            cleaned_lines = self.clean_noise(all_raw_lines)
            debug_data["cleaned_lines"] = cleaned_lines
            debug_data["stats"]["cleaned_line_count"] = len(cleaned_lines)

        return debug_data

    def extract_pdf_blocks_debug(self, file_path, bank_name):
        if bank_name not in self.config:
            raise ValueError(f"Bank '{bank_name}' not supported. Available: {list(self.config.keys())}")
        cfg = self.config[bank_name]
        if cfg.get("pdf_parser") != "multiline_table":
            raise ValueError(f"Bank '{bank_name}' is not configured for multiline table parsing.")

        debug_data = self.extract_pdf_debug(file_path, apply_cleaning=True)
        lines = debug_data.get("cleaned_lines", [])
        blocks = self._extract_multiline_blocks(lines, cfg)

        result_blocks = []
        for block in blocks:
            parsed = self._build_transaction_from_block(block, cfg)
            parsed_view = None
            if parsed:
                parsed_view = {
                    "date": parsed["date"].strftime("%Y-%m-%d"),
                    "amount": parsed["amount"],
                    "type": parsed["type"],
                }
            result_blocks.append(
                {
                    "date_str": block.get("date_str", ""),
                    "description": self._normalize_spaces(" ".join(block.get("desc_parts", []))),
                    "amounts_text": block.get("amounts_text", ""),
                    "block_lines": block.get("block_lines", []),
                    "parsed": parsed_view,
                }
            )

        return {
            "file_path": file_path,
            "bank_name": bank_name,
            "blocks": result_blocks,
        }

    def clean_noise(self, lines):
        """
        Removes headers, footers, and common noise.
        """
        cleaned = []
        page_pattern = re.compile(r"Page \d+ of \d+", re.IGNORECASE)
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Filter Page X of Y
            if page_pattern.search(line):
                continue
                
            # Add more filters here as needed based on specific bank formats
            
            cleaned.append(line)
        return cleaned
