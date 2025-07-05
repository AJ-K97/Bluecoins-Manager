import argparse
import csv
import json
import os
from datetime import datetime

def load_accounts():
    """Load accounts from data/accounts.json"""
    try:
        with open("data/accounts.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_accounts(accounts):
    """Save accounts to data/accounts.json"""
    with open("data/accounts.json", "w") as f:
        json.dump(accounts, f, indent=4)

def account_command(args):
    """Handle account subcommand"""
    accounts = load_accounts()
    
    if args.add:
        if args.add in accounts:
            print(f"Account '{args.add}' already exists.")
        else:
            accounts.append(args.add)
            save_accounts(accounts)
            print(f"Account '{args.add}' added successfully.")
    
    elif args.delete:
        if args.delete in accounts:
            accounts.remove(args.delete)
            save_accounts(accounts)
            print(f"Account '{args.delete}' deleted successfully.")
        else:
            print(f"Account '{args.delete}' not found.")
    
    elif args.list:
        if accounts:
            print("Available accounts:")
            for account in accounts:
                print(f"  - {account}")
        else:
            print("No accounts configured.")

def convert_command(args):
    """Handle convert subcommand - preserved from original functionality"""
    # Load bank configuration
    try:
        with open("data/banks_config.json", "r") as f:
            config = json.load(f)
    except FileNotFoundError:
        print("Error: data/banks_config.json not found. Please create it with bank mappings.")
        return
    if args.bank not in config["banks"]:
        print(f"Error: Bank '{args.bank}' not found in configuration.")
        return
    bank_config = config["banks"][args.bank]

    # Load existing category mappings
    try:
        with open("data/category_mapping.json", "r") as f:
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
    with open("data/category_mapping.json", "w") as f:
        json.dump(category_mapping, f, indent=4)
    print("Category mappings saved to 'data/category_mapping.json'")

def load_categories():
    """Load categories from data/categories.json"""
    try:
        with open("data/categories.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_categories(categories):
    """Save categories to data/categories.json"""
    with open("data/categories.json", "w") as f:
        json.dump(categories, f, indent=4)

def category_command(args):
    """Handle category subcommand"""
    categories = load_categories()
    
    if args.list:
        if not categories:
            print("No category templates found.")
            return
        
        template = args.template or "Bluecoins"
        if template not in categories:
            print(f"Template '{template}' not found.")
            return
        
        print(f"Categories for template '{template}':")
        for type_name, parent_categories in categories[template].items():
            print(f"  {type_name.upper()}:")
            for parent, children in parent_categories.items():
                print(f"    {parent}:")
                for child in children:
                    print(f"      - {child}")
    
    elif args.add:
        template = args.template or "Bluecoins"
        if template not in categories:
            categories[template] = {"expense": {}, "income": {}}
        
        if args.type not in categories[template]:
            categories[template][args.type] = {}
        
        if args.parent not in categories[template][args.type]:
            categories[template][args.type][args.parent] = []
        
        if args.child in categories[template][args.type][args.parent]:
            print(f"Category '{args.child}' already exists under '{args.parent}'.")
        else:
            categories[template][args.type][args.parent].append(args.child)
            save_categories(categories)
            print(f"Added category '{args.child}' under '{args.parent}' in {args.type} template '{template}'.")
    
    elif args.delete:
        template = args.template or "Bluecoins"
        if template not in categories:
            print(f"Template '{template}' not found.")
            return
        
        if args.type not in categories[template]:
            print(f"Type '{args.type}' not found in template '{template}'.")
            return
        
        if args.parent not in categories[template][args.type]:
            print(f"Parent category '{args.parent}' not found.")
            return
        
        if args.child not in categories[template][args.type][args.parent]:
            print(f"Category '{args.child}' not found under '{args.parent}'.")
            return
        
        categories[template][args.type][args.parent].remove(args.child)
        
        # Clean up empty parent categories
        if not categories[template][args.type][args.parent]:
            del categories[template][args.type][args.parent]
        
        save_categories(categories)
        print(f"Deleted category '{args.child}' from '{args.parent}' in {args.type} template '{template}'.")

def main():
    # Set up main parser
    parser = argparse.ArgumentParser(description="Financial CLI Toolkit")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Account subcommand
    account_parser = subparsers.add_parser("account", help="Manage financial accounts")
    account_group = account_parser.add_mutually_exclusive_group(required=True)
    account_group.add_argument("--add", help="Add a new account")
    account_group.add_argument("--delete", help="Delete an existing account")
    account_group.add_argument("--list", action="store_true", help="List all accounts")

    # Category subcommand
    category_parser = subparsers.add_parser("category", help="Manage transaction categories")
    category_group = category_parser.add_mutually_exclusive_group(required=True)
    category_group.add_argument("--add", action="store_true", help="Add a new category")
    category_group.add_argument("--delete", action="store_true", help="Delete a category")
    category_group.add_argument("--list", action="store_true", help="List all categories")
    category_parser.add_argument("--template", default="Bluecoins", help="Template name (default: Bluecoins)")
    category_parser.add_argument("--type", choices=["expense", "income"], help="Category type (expense or income)")
    category_parser.add_argument("--parent", help="Parent category name")
    category_parser.add_argument("--child", help="Child category name")

    # Convert subcommand
    convert_parser = subparsers.add_parser("convert", help="Convert bank CSV to Bluecoins format")
    convert_parser.add_argument("--bank", required=True, help="Bank name (e.g., HSBC, Wise)")
    convert_parser.add_argument("--input", required=True, help="Input CSV file path")
    convert_parser.add_argument("--output", required=True, help="Output CSV file path")
    convert_parser.add_argument("--account-type", required=True, help="Account type (e.g., Bank, Credit Card)")
    convert_parser.add_argument("--account", required=True, help="Account name (e.g., HSBC Savings)")

    # Parse arguments
    args = parser.parse_args()

    # Ensure data directory exists
    if not os.path.exists("data"):
        os.makedirs("data")

    # Route to appropriate command
    if args.command == "account":
        account_command(args)
    elif args.command == "category":
        category_command(args)
    elif args.command == "convert":
        convert_command(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()