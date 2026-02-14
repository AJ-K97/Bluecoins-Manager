import csv
import json
import os
from datetime import datetime

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
        Parses a bank CSV file and returns a list of standardized transaction dictionaries.
        """
        if bank_name not in self.config:
            raise ValueError(f"Bank '{bank_name}' not supported. Available: {list(self.config.keys())}")
        
        cfg = self.config[bank_name]
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
                        amount = float(amount_str)
                        if cfg.get("negate_amounts", False):
                            amount = -amount
                    except ValueError:
                        continue # Skip invalid amounts

                    # Type Determination
                    tx_type = "expense" # Default
                    if cfg.get("type_determination") == "amount_sign":
                        # Positive usually means credit (income), negative debit (expense)
                        # But wait, config says "amount_sign".
                        # HSBC often has negative for expense.
                        if amount > 0:
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
