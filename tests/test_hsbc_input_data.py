import unittest

from src.parser import BankParser
from src.patterns import extract_pattern_key


class HSBCInputDataTests(unittest.TestCase):
    def setUp(self):
        self.parser = BankParser()
        self.path = "tests/input_data/HSBC_TransHist.csv"
        self.transactions = self.parser.parse("HSBC", self.path)

    def test_parser_reads_transactions(self):
        self.assertGreater(len(self.transactions), 0)

        first = self.transactions[0]
        self.assertIn("date", first)
        self.assertIn("description", first)
        self.assertIn("amount", first)
        self.assertIn("type", first)
        self.assertIn("raw_csv_row", first)

    def test_pattern_key_for_known_problem_descriptions(self):
        trustee_tx = next(t for t in self.transactions if "THE TRUSTEE FOR BCF" in t["description"])
        corfield_tx = next(t for t in self.transactions if "CORFIELD FRESH IGA" in t["description"])

        self.assertEqual(extract_pattern_key(trustee_tx["description"]), "BCF")
        self.assertEqual(extract_pattern_key(corfield_tx["description"]), "CORFIELD FRESH IGA")

    def test_type_uses_source_sign_even_when_amounts_are_negated(self):
        # HSBC config negates amount for normalized storage, but transaction type
        # should still come from original bank direction.
        expense_tx = next(t for t in self.transactions if "CORFIELD FRESH IGA" in t["description"])
        income_tx = next(t for t in self.transactions if "Aurizn Salary" in t["description"])

        self.assertEqual(expense_tx["type"], "expense")
        self.assertEqual(income_tx["type"], "income")


if __name__ == "__main__":
    unittest.main()
