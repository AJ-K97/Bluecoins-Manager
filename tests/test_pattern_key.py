import unittest

from src.patterns import extract_pattern_key, extract_pattern_key_result


class PatternKeyTests(unittest.TestCase):
    def test_extracts_keywords_before_date(self):
        desc = "CORFIELD FRESH IGA 28JAN26 ATMA896 23:30:46 4402 VISA AUD CORFIELD FRESH IGA ATM"
        result = extract_pattern_key_result(desc)
        self.assertEqual(result.keyword, "CORFIELD FRESH IGA")
        self.assertGreaterEqual(result.confidence, 0.8)

    def test_removes_legal_prefix_before_date(self):
        desc = "THE TRUSTEE FOR BCF 26JAN26 ATMA896 12:06:01 4402 VISA AUD THE TRUSTEE FOR BCF ATM"
        result = extract_pattern_key_result(desc)
        self.assertEqual(result.keyword, "BCF")
        self.assertEqual(result.source, "rule")

    def test_extracts_payee_from_payment_from(self):
        desc = "PAYMENT FROM MISS ADITHYA SUNIL"
        result = extract_pattern_key_result(desc)
        self.assertEqual(result.keyword, "MISS ADITHYA SUNIL")
        self.assertGreaterEqual(result.confidence, 0.8)

    def test_extracts_merchant_from_slash_format(self):
        desc = "VISA DEBIT PURCHASE CARD 8208 WOOLWORTHS/ NICHOLSON RD & CANNINGVALE"
        result = extract_pattern_key_result(desc)
        self.assertEqual(result.keyword, "WOOLWORTHS")
        self.assertEqual(result.source, "rule")

    def test_backwards_compat_keyword_function(self):
        desc = "TRANSFER RTP 123456 INTERNET BANKING"
        key = extract_pattern_key(desc)
        self.assertIsInstance(key, str)
        self.assertTrue(len(key) > 0)


if __name__ == "__main__":
    unittest.main()
