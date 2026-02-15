import unittest

from src.policy import AUTO_APPROVE_MIN, REVIEW_MIN, evaluate_decision_policy


class PolicyTests(unittest.TestCase):
    def test_auto_approve_requires_high_confidence_no_conflicts(self):
        res = evaluate_decision_policy(AUTO_APPROVE_MIN, [])
        self.assertEqual(res.state, "auto_approved")
        self.assertTrue(res.can_auto_verify)

    def test_mid_band_goes_to_needs_review(self):
        res = evaluate_decision_policy((AUTO_APPROVE_MIN + REVIEW_MIN) / 2.0, [])
        self.assertEqual(res.state, "needs_review")
        self.assertFalse(res.can_auto_verify)

    def test_low_confidence_forces_review(self):
        res = evaluate_decision_policy(REVIEW_MIN - 0.01, [])
        self.assertEqual(res.state, "force_review")

    def test_conflicts_override_high_confidence(self):
        res = evaluate_decision_policy(0.999, ["type_category_mismatch"])
        self.assertEqual(res.state, "force_review")
        self.assertEqual(res.bucket, "rule_conflict")


if __name__ == "__main__":
    unittest.main()
