import unittest

from app.services.ai.response_validation import _has_unexpected_language


class PersianSalesPlanValidationTests(unittest.TestCase):
    def test_plan_terms_are_allowed_but_english_switch_is_rejected(self):
        self.assertFalse(
            _has_unexpected_language("ENTRY LEVEL CORE MONTH DISCOUNT", "fa")
        )
        self.assertTrue(
            _has_unexpected_language(
                "ENTRY LEVEL is the best option for your server and includes support.",
                "fa",
            )
        )
