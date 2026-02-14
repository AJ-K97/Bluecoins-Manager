import unittest
from datetime import datetime

from src.database import Account, Category, Transaction
from src.local_llm import LocalLLMPipeline, _cosine_similarity


class TestLocalLLMPipeline(unittest.TestCase):
    def test_cosine_similarity_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        score = _cosine_similarity(v, v)
        self.assertAlmostEqual(score, 1.0, places=9)

    def test_cosine_similarity_mismatched_length_returns_zero(self):
        score = _cosine_similarity([1.0, 2.0], [1.0])
        self.assertEqual(score, 0.0)

    def test_transaction_chunk_contains_expected_fields(self):
        pipeline = LocalLLMPipeline()
        account = Account(id=1, name="Main", institution="Main")
        category = Category(id=5, name="Groceries", parent_name="Food", type="expense")
        tx = Transaction(
            id=42,
            date=datetime(2026, 2, 10, 14, 30, 0),
            description="ALDI AUSTRALIA",
            amount=56.7,
            type="expense",
            account=account,
            category=category,
            is_verified=True,
        )

        content, metadata = pipeline._transaction_to_chunk(tx)

        self.assertIn("Transaction #42", content)
        self.assertIn("Description: ALDI AUSTRALIA", content)
        self.assertIn("Category: Food > Groceries", content)
        self.assertEqual(metadata["transaction_id"], 42)
        self.assertEqual(metadata["account"], "Main")
        self.assertEqual(metadata["category_name"], "Groceries")
        self.assertIs(metadata["is_verified"], True)

if __name__ == "__main__":
    unittest.main()
