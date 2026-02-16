import csv
import os
from datetime import datetime, timedelta
import random

def generate_hsbc_csv(file_path, num_rows=10):
    """
    HSBC Rows: Transaction Date, Description, Amount
    Format: DD/MM/YYYY
    """
    header = ["Transaction Date", "Description", "Amount"]
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for i in range(num_rows):
            date = (datetime(2024, 1, 1) + timedelta(days=i)).strftime("%d/%m/%Y")
            desc = random.choice(["SHELL OIL", "UBER TRIP", "AMAZON MKTP", "HSBC INTEREST", "REFUND NIKE"])
            amount = round(random.uniform(-100, 100), 2)
            writer.writerow([date, desc, str(amount)])
    print(f"Generated HSBC data: {file_path}")

def generate_wise_csv(file_path, num_rows=10):
    """
    Wise Rows: Created on, Target name, Source amount (after fees), Direction
    """
    header = ["Created on", "Target name", "Source amount (after fees)", "Direction", "Currency"]
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for i in range(num_rows):
            date = (datetime(2024, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
            desc = random.choice(["Lunch with friends", "Rent Payment", "Salary", "Netflix Subscription"])
            amount = abs(round(random.uniform(5, 2000), 2))
            direction = "IN" if random.random() > 0.8 else "OUT"
            writer.writerow([date, desc, str(amount), direction, "EUR"])
    print(f"Generated Wise data: {file_path}")

if __name__ == "__main__":
    generate_hsbc_csv("tests/input_data/synthetic_hsbc.csv")
    generate_wise_csv("tests/input_data/synthetic_wise.csv")
