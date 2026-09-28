import unittest

from app.services.ai.response_validation import validate_reply


class ResponseValidationTests(unittest.TestCase):
    def test_persian_reply_allows_fixed_technical_names(self):
        self.assertTrue(validate_reply("پلن POWER، ۱۶ GB RAM و ۲۵۰ GB SSD داره.", "fa"))

    def test_persian_reply_rejects_english_sentence(self):
        self.assertFalse(validate_reply("The ELITE plan is a good fit for you.", "fa"))

    def test_english_reply_rejects_persian_copy(self):
        self.assertFalse(validate_reply("برای پرداخت آماده‌ای؟", "en"))

    def test_model_cannot_leak_wallet_address_without_payment_flow(self):
        self.assertFalse(
            validate_reply(
                "Send this wallet address: 0xab96D9Ba2545b5BB6076A649117C5120019062Ba",
                "en",
            )
        )

    def test_deterministic_payment_reply_is_allowed(self):
        self.assertTrue(
            validate_reply(
                "Ethereum (ETH):\n`0xab96D9Ba2545b5BB6076A649117C5120019062Ba`",
                "en",
                payment_allowed=True,
            )
        )


if __name__ == "__main__":
    unittest.main()