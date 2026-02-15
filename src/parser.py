import csv
import json
import os
from datetime import datetime
import re
import pypdf

class BankParser:
    def __init__(self, config_path="data/banks_config.json"):
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")
            
        with open(config_path, "r") as f:
            self.config = json.load(f)["banks"]

    def _parse_date(self, date_str, formats):
        for fmt in formats:
            try:
                # Handle %b manually if needed? Standard library handles English locale usually.
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None

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
        
        with open(file_path, "r", encoding="utf-8-sig") as f:
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
                    date_val = self._parse_date(clean_row[cfg["date_column"]], cfg["date_formats"])
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
        if "pdf_regex" not in cfg:
            raise ValueError(f"Bank '{bank_name}' does not have 'pdf_regex' configured.")
            
        pattern = re.compile(cfg["pdf_regex"])
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
                    # Expect groups: 1=Date, 2=Description, 3=Amount
                    date_str = match.group(1).strip()
                    desc = match.group(2).strip()
                    amount_str = match.group(3).strip().replace(',', '')
                    
                    # Date
                    date_val = self._parse_date(date_str, cfg["date_formats"])
                    if not date_val:
                        continue
                        
                    # Amount
                    try:
                        amount = float(amount_str)
                        if cfg.get("negate_amounts", False):
                            amount = -amount
                    except ValueError:
                        continue
                        
                    # Type
                    tx_type = "expense"
                    if amount > 0:
                        tx_type = "income"
                    else:
                        tx_type = "expense"
                        
                    transactions.append({
                        "date": date_val,
                        "description": desc,
                        "amount": amount,
                        "type": tx_type,
                        "raw_csv_row": line
                    })
                    
            return transactions
            
        except Exception as e:
            raise ValueError(f"Failed to parse PDF: {e}")

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
