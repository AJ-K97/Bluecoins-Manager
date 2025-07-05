import argparse
import csv
import json
from datetime import datetime

def main():
    # Set up command-line argument parser
    parser = argparse.ArgumentParser(description="Convert bank CSV to Bluecoins CSV")
    parser.add_argument("--bank", required=True, help="Bank name (e.g., ANZ, Wise)")
    parser.add_argument("--input", required=True, help="Input CSV file path")
    parser.add_argument("--output", required=True, help="Output CSV file path")
    parser.add_argument("--account-type", required=True, help="Account type (e.g., Bank, Credit Card)")
    parser.add_argument("--account", required=True, help="Account name (e.g., ANZ Savings)")
    args = parser.parse_args()

    # Load bank configuration
    try:
        with open("banks_config.json", "r") as f:
            config = json.load(f)
    except FileNotFoundError:
        print("Error: banks_config.json not found. Please create it with bank mappings.")
        return
    if args.bank not in config["banks"]:
        print(f"Error: Bank '{args.bank}' not found in configuration.")
        return
    bank_config = config["banks"][args.bank]

    # Load existing category mappings
    try:
        with open("category_mapping.json", "r") as f:
            category_mapping = json.load(f)
    except FileNotFoundError:
        category_mapping = {}

    # Read the input CSV
    try:
        with open(args.input, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            # Clean up column names by stripping whitespace
            reader.fieldnames = [name.strip() for name in reader.fieldnames]
            rows = []
            for row in reader:
                # Clean up each value in the row by stripping whitespace and replacing non-breaking spaces
                cleaned_row = {
                    key.strip(): value.strip().replace('\xa0', ' ').replace('  ', ' ')
                    for key, value in row.items()
                }
                rows.append(cleaned_row)
    except FileNotFoundError:
        print(f"Error: Input file '{args.input}' not found.")
        return

    # Prepare list for Bluecoins rows
    bluecoins_rows = []

    # Process each transaction
    for row in rows:
        # Extract required fields based on bank config
        try:
            date_str = row[bank_config["date_column"]]
            description = row[bank_config["description_column"]]
            amount_str = row[bank_config["amount_column"]].replace(",", "")
            amount = float(amount_str)
        except KeyError as e:
            # print(f"Error: Missing column {e} in input CSV for transaction: {row}")
            continue
        except ValueError:
            print(f"Error: Invalid amount '{amount_str}' in transaction: {row}")
            continue

        # Determine transaction type
        if bank_config["type_determination"] == "amount_sign":
            type_ = "i" if amount > 0 else "e"
        elif bank_config["type_determination"] == "direction_column":
            try:
                direction = row[bank_config["direction_column"]]
                if direction == bank_config["direction_in_value"]:
                    type_ = "i"
                elif direction == bank_config["direction_out_value"]:
                    type_ = "e"
                else:
                    print(f"Warning: Unknown direction '{direction}' in transaction: {description}")
                    type_ = "e"  # Default to expense
            except KeyError:
                print(f"Error: Direction column missing in transaction: {row}")
                continue
        else:
            print(f"Error: Invalid type_determination for bank '{args.bank}'")
            return

        # Parse and format date to Bluecoins format (M/D/YYYY)
        try:
            date = datetime.strptime(date_str, bank_config["date_format"])
            formatted_date = date.strftime("%m/%d/%Y")
        except ValueError:
            print(f"Error: Invalid date '{date_str}' in transaction: {row}")
            continue

        # Handle categories
        if description in category_mapping:
            parent_category = category_mapping[description]["parent_category"]
            category = category_mapping[description]["category"]
        else:
            print(f"\nTransaction: {description}")
            parent_category = input("Enter Parent Category: ")
            category = input("Enter Category: ")
            category_mapping[description] = {
                "parent_category": parent_category,
                "category": category
            }

        # Create Bluecoins row
        bluecoins_row = {
            "Type": type_,
            "Date": formatted_date,
            "Item or Payee": description,
            "Amount": str(abs(amount)),  # Bluecoins expects positive amounts
            "Parent Category": parent_category,
            "Category": category,
            "Account Type": args.account_type,
            "Account": args.account,
            "Notes": "",
            "Label": "",
            "Status": "",
            "Split": ""
        }
        bluecoins_rows.append(bluecoins_row)

    # Write output CSV
    with open(args.output, "w", newline="") as f:
        fieldnames = [
            "Type", "Date", "Item or Payee", "Amount", "Parent Category",
            "Category", "Account Type", "Account", "Notes", "Label", "Status", "Split"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(bluecoins_rows)
    print(f"Successfully wrote {len(bluecoins_rows)} transactions to '{args.output}'")

    # Save updated category mappings
    with open("category_mapping.json", "w") as f:
        json.dump(category_mapping, f, indent=4)
    print("Category mappings saved to 'category_mapping.json'")

if __name__ == "__main__":
    main()