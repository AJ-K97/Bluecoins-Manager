import unittest

from src.patterns import extract_pattern_key


class PatternKeyTests(unittest.TestCase):
    def test_extracts_keywords_before_date(self):
        desc = "CORFIELD FRESH IGA 28JAN26 ATMA896 23:30:46 4402 VISA AUD CORFIELD FRESH IGA ATM"
        self.assertEqual(extract_pattern_key(desc), "CORFIELD FRESH IGA")

    def test_removes_legal_prefix_before_date(self):
        desc = "THE TRUSTEE FOR BCF 26JAN26 ATMA896 12:06:01 4402 VISA AUD THE TRUSTEE FOR BCF ATM"
        self.assertEqual(extract_pattern_key(desc), "BCF")

    def test_falls_back_to_first_word_when_no_date(self):
        desc = "TRANSFER RTP 123456 INTERNET BANKING"
        self.assertEqual(extract_pattern_key(desc), "TRANSFER")


if __name__ == "__main__":
    unittest.main()
