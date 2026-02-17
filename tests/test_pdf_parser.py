import unittest
import os
import json
from datetime import datetime
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.parser import BankParser, format_pdf_debug_report, format_pdf_blocks_report
from pypdf import PdfWriter
import pypdf

class TestPDFParser(unittest.TestCase):
    def setUp(self):
        # Create a mock PDF
        self.writer = PdfWriter()
        self.writer.add_blank_page(width=72, height=72)
        # We can't easily write text with pypdf without complex operations or external fonts.
        # Instead, we will mock the PdfReader in the test logic or try to write a real PDF if possible.
        # Writing text with pypdf is hard.
        # Easier strategy: Mock os.path.exists and pypdf.PdfReader
        pass

    def test_regex_parsing(self):
        # Manually invoke parse_pdf with mocked dependencies
        parser = BankParser()
        
        # Inject config for test
        parser.config["TestBank"] = {
            "date_column": "Date",
            "description_column": "Description",
            "amount_column": "Amount",
            "date_formats": ["%d/%m/%Y"],
            "pdf_regex": r"^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?\d+\.\d{2})$",
            "type_determination": "amount_sign"
        }
        
        file_path = "test_statement.pdf"
        
        # Mock class for PdfReader
        class MockPage:
            def extract_text(self):
                return "01/01/2025 Test Transaction 50.00\n02/01/2025 Salary 1000.00\nInvalid Line"
        
        class MockReader:
            def __init__(self, f):
                self.pages = [MockPage()]

        # Patch pypdf.PdfReader
        original_reader = pypdf.PdfReader
        pypdf.PdfReader = MockReader
        
        try:
            # We need to pass the file path to parse_pdf, but since we mocked Reader, 
            # it won't actually try to open the file if we call parse_pdf directly?
            # Actually parse_pdf calls PdfReader(file_path).
            # So the file doesn't need to exist if strict=False is not used or if we mocked it well.
            # However, implementation might require file path to end with .pdf check in `parse` method.
            
            transactions = parser.parse_pdf("TestBank", file_path, parser.config["TestBank"])
            
            self.assertEqual(len(transactions), 2)
            self.assertEqual(transactions[0]["description"], "Test Transaction")
            self.assertEqual(transactions[0]["amount"], 50.00)
            self.assertEqual(transactions[0]["type"], "income") 
            
            self.assertEqual(transactions[1]["description"], "Salary")
            self.assertEqual(transactions[1]["amount"], 1000.00)
            
        finally:
            pypdf.PdfReader = original_reader

    def test_anz_style_credit_debit_pdf(self):
        parser = BankParser()
        parser.config["ANZ"] = {
            "date_formats": ["%d %b", "%d/%m/%Y"],
            "pdf_regex": r"^(\d{1,2}\s+[A-Za-z]{3})\s+(.+?)\s+(\$?[\d,]+\.\d{2})?\s*(\$?[\d,]+\.\d{2})?\s+\$?[\d,]+\.\d{2}$",
            "pdf_date_group": 1,
            "pdf_description_group": 2,
            "pdf_credit_group": 3,
            "pdf_debit_group": 4,
        }

        class MockPage:
            def extract_text(self):
                return (
                    "29 Jan VISA DEBIT PURCHASE CARD 8208 WOOLWORTHS/NICHOLSON RD & CANNINGVALE "
                    "Effective Date 27/01/2026 18.60 4171.59\n"
                    "30 Jan PAYROLL CREDIT COMPANY PTY LTD Effective Date 30/01/2026 2500.00 6671.59"
                )

        class MockReader:
            def __init__(self, f):
                self.pages = [MockPage()]

        original_reader = pypdf.PdfReader
        pypdf.PdfReader = MockReader
        try:
            txs = parser.parse_pdf("ANZ", "anz_statement.pdf", parser.config["ANZ"])
            self.assertEqual(len(txs), 2)

            self.assertEqual(txs[0]["type"], "expense")
            self.assertEqual(txs[0]["amount"], 18.60)
            self.assertEqual(txs[0]["date"].year, 2026)

            self.assertEqual(txs[1]["type"], "income")
            self.assertEqual(txs[1]["amount"], 2500.00)
            self.assertEqual(txs[1]["date"].year, 2026)
        finally:
            pypdf.PdfReader = original_reader

    def test_extract_pdf_debug_structure(self):
        parser = BankParser()

        class MockPage:
            def extract_text(self):
                return "Page 1 title\n01/01/2026 Coffee -5.00"

        class MockReader:
            def __init__(self, f):
                self.pages = [MockPage()]

        original_reader = pypdf.PdfReader
        pypdf.PdfReader = MockReader
        try:
            debug_data = parser.extract_pdf_debug("dummy.pdf", apply_cleaning=True)
            self.assertIn("pages", debug_data)
            self.assertIn("stats", debug_data)
            self.assertIn("cleaned_lines", debug_data)
            self.assertEqual(debug_data["stats"]["page_count"], 1)
            self.assertEqual(debug_data["pages"][0]["page_index"], 0)
            self.assertIn("raw_text", debug_data["pages"][0])
            self.assertIn("raw_lines", debug_data["pages"][0])
        finally:
            pypdf.PdfReader = original_reader

    def test_extract_pdf_debug_handles_none_page_text(self):
        parser = BankParser()

        class MockPage:
            def extract_text(self):
                return None

        class MockReader:
            def __init__(self, f):
                self.pages = [MockPage()]

        original_reader = pypdf.PdfReader
        pypdf.PdfReader = MockReader
        try:
            debug_data = parser.extract_pdf_debug("dummy.pdf", apply_cleaning=True)
            self.assertEqual(debug_data["stats"]["raw_line_count"], 0)
            self.assertEqual(debug_data["stats"]["cleaned_line_count"], 0)
            report = format_pdf_debug_report(debug_data, mode="both", max_lines=None)
            self.assertIn("--- Page 1 Raw Text ---", report)
            self.assertIn("[empty]", report)
            self.assertIn("No cleaned lines found", report)
        finally:
            pypdf.PdfReader = original_reader

    def test_extract_pdf_debug_applies_noise_cleaning(self):
        parser = BankParser()

        class MockPage:
            def extract_text(self):
                return "Page 1 of 3\n29 Jan Example 10.00"

        class MockReader:
            def __init__(self, f):
                self.pages = [MockPage()]

        original_reader = pypdf.PdfReader
        pypdf.PdfReader = MockReader
        try:
            debug_data = parser.extract_pdf_debug("dummy.pdf", apply_cleaning=True)
            self.assertEqual(debug_data["stats"]["raw_line_count"], 2)
            self.assertEqual(debug_data["stats"]["cleaned_line_count"], 1)
            self.assertEqual(debug_data["cleaned_lines"][0], "29 Jan Example 10.00")
        finally:
            pypdf.PdfReader = original_reader

    def test_extract_pdf_debug_permission_error(self):
        parser = BankParser()

        class MockReader:
            def __init__(self, f):
                raise PermissionError("denied")

        original_reader = pypdf.PdfReader
        pypdf.PdfReader = MockReader
        try:
            with self.assertRaises(ValueError) as ctx:
                parser.extract_pdf_debug("dummy.pdf", apply_cleaning=True)
            msg = str(ctx.exception)
            self.assertIn("Permission denied reading", msg)
            self.assertIn("uploads", msg)
        finally:
            pypdf.PdfReader = original_reader

    def test_format_pdf_debug_report_modes(self):
        debug_data = {
            "file_path": "dummy.pdf",
            "pages": [{"page_index": 0, "raw_text": "line1", "raw_lines": ["line1"]}],
            "cleaned_lines": ["line1"],
            "stats": {"page_count": 1, "raw_line_count": 1, "cleaned_line_count": 1},
        }
        raw_report = format_pdf_debug_report(debug_data, mode="raw", max_lines=None)
        cleaned_report = format_pdf_debug_report(debug_data, mode="cleaned", max_lines=None)
        both_report = format_pdf_debug_report(debug_data, mode="both", max_lines=None)

        self.assertIn("--- Page 1 Raw Text ---", raw_report)
        self.assertNotIn("--- Cleaned Lines ---", raw_report)
        self.assertIn("--- Cleaned Lines ---", cleaned_report)
        self.assertNotIn("--- Page 1 Raw Text ---", cleaned_report)
        self.assertIn("--- Page 1 Raw Text ---", both_report)
        self.assertIn("--- Cleaned Lines ---", both_report)

    def test_multiline_table_parser_anz_style(self):
        parser = BankParser()
        parser.config["ANZ_TABLE"] = {
            "pdf_parser": "multiline_table",
            "date_formats": ["%d %b", "%d/%m/%Y"],
            "pdf_tx_start_regex": r"^(?P<date>\d{1,2}\s+[A-Za-z]{3})(?:\s+|$)(?P<rest>.*)$",
            "pdf_amount_balance_regex": r"^\$?[\d,]+\.\d{2}(?:\s+\$?[\d,]+\.\d{2}){1,2}$",
            "pdf_ignore_line_patterns": [r"^Date Description Credit Debit Balance$"],
        }

        class MockPage:
            def extract_text(self):
                return (
                    "Date Description Credit Debit Balance\n"
                    "22 Jan TRANSFER FROM SOMANGILI SIVAKU JOINT BANK\n"
                    "TRANSFE\n"
                    "$100.00 $4,425.91\n"
                    "20 Jan PAYMENT FROM MISS ADITHYA SUNIL $100.00 $4,325.91\n"
                    "06 Jan PAYMENT FROM MISS ADITHYA SUNIL $50.00 $4,311.50\n"
                    "02 Jan TRANSFER FROM SOMANGILI SIVAKU JOINT BANK\n"
                    "TRANSFE\n"
                    "$100.00 $4,261.50"
                )

        class MockReader:
            def __init__(self, f):
                self.pages = [MockPage()]

        original_reader = pypdf.PdfReader
        pypdf.PdfReader = MockReader
        try:
            txs = parser.parse_pdf("ANZ_TABLE", "anz_table.pdf", parser.config["ANZ_TABLE"])
            self.assertEqual(len(txs), 4)
            # Ensure multi-line rows are merged and amount/date are accurate.
            self.assertEqual(txs[0]["date"].day, 22)
            self.assertEqual(txs[0]["amount"], 100.0)
            self.assertIn("TRANSFER FROM SOMANGILI", txs[0]["description"])

            self.assertEqual(txs[2]["date"].day, 6)
            self.assertEqual(txs[2]["amount"], 50.0)
            self.assertEqual(txs[2]["type"], "income")
            self.assertIn("PAYMENT FROM MISS ADITHYA SUNIL", txs[2]["description"])
        finally:
            pypdf.PdfReader = original_reader

    def test_extract_pdf_blocks_debug_and_report(self):
        parser = BankParser()
        parser.config["ANZ_BLOCKS"] = {
            "pdf_parser": "multiline_table",
            "date_formats": ["%d %b", "%d/%m/%Y"],
            "pdf_tx_start_regex": r"^(?P<date>\d{1,2}\s+[A-Za-z]{3})(?:\s+|$)(?P<rest>.*)$",
            "pdf_amount_balance_regex": r"^\$?[\d,]+\.\d{2}(?:\s+\$?[\d,]+\.\d{2}){1,2}$",
            "pdf_ignore_line_patterns": [],
        }

        class MockPage:
            def extract_text(self):
                return (
                    "06 Jan PAYMENT FROM MISS ADITHYA SUNIL $50.00 $4,311.50\n"
                    "02 Jan TRANSFER FROM SOMANGILI SIVAKU JOINT BANK\n"
                    "TRANSFE\n"
                    "$100.00 $4,261.50"
                )

        class MockReader:
            def __init__(self, f):
                self.pages = [MockPage()]

        original_reader = pypdf.PdfReader
        pypdf.PdfReader = MockReader
        try:
            blocks_data = parser.extract_pdf_blocks_debug("dummy.pdf", "ANZ_BLOCKS")
            self.assertEqual(len(blocks_data["blocks"]), 2)
            self.assertEqual(blocks_data["blocks"][0]["parsed"]["amount"], 50.0)

            report = format_pdf_blocks_report(blocks_data, max_blocks=None)
            self.assertIn("PDF Block Debug Report", report)
            self.assertIn("=== Block 001 ===", report)
            self.assertIn("PAYMENT FROM MISS ADITHYA SUNIL", report)
        finally:
            pypdf.PdfReader = original_reader

if __name__ == '__main__':
    unittest.main()
