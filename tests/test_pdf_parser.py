import unittest
import os
import json
from datetime import datetime
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.parser import BankParser
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

if __name__ == '__main__':
    unittest.main()
