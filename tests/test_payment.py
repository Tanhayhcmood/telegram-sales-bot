import unittest

from app.services.sales.payment import (
    PAYMENT_ADDRESSES,
    PAYMENT_MESSAGE,
    PAYMENT_MESSAGE_EN,
    get_payment_reply,
    is_payment_only_request,
)
from app.services.sales.quick_support import get_quick_support_reply


class PaymentTests(unittest.TestCase):
    def test_full_message_uses_exact_configured_addresses(self):
        for address in PAYMENT_ADDRESSES.values():
            self.assertIn(f"`{address}`", PAYMENT_MESSAGE)

        self.assertEqual(
            PAYMENT_MESSAGE.count("`0xab96D9Ba2545b5BB6076A649117C5120019062Ba`"),
            4,
        )
        self.assertEqual(
            PAYMENT_MESSAGE.count("`TEaoA6zo6oytwpEUe6P3EmuoXB128dReiJ`"),
            2,
        )
        self.assertIn("`bc1qe4u06ttrj9c37lmlkv7rks6h7tyttwe2sfwffe`", PAYMENT_MESSAGE)

    def test_payment_question_asks_for_coin_without_addresses(self):
        reply = get_payment_reply("چطور پرداخت کنم؟", "fa")

        self.assertIn("کدوم رمزارز", reply)
        self.assertNotIn("0xab96D9Ba2545b5BB6076A649117C5120019062Ba", reply)
        self.assertNotIn("TEaoA6zo6oytwpEUe6P3EmuoXB128dReiJ", reply)

    def test_specific_tron_request_returns_only_tron(self):
        reply = get_payment_reply("فقط ترون بده", "fa")

        self.assertEqual(
            reply,
            "ترون (TRX):\n`TEaoA6zo6oytwpEUe6P3EmuoXB128dReiJ`",
        )
        self.assertNotIn("USDT", reply)

    def test_card_question_returns_crypto_payment_methods(self):
        reply = get_payment_reply("شماره کارت ندارید؟", "fa")

        self.assertIn("کدوم رمزارز", reply)
        self.assertNotIn("`", reply)

    def test_explicit_purchase_intent_asks_for_coin(self):
        reply = get_payment_reply("آماده‌ام، می‌خوام سفارش بدم", "fa", "ready_to_buy")

        self.assertIn("کدوم رمزارز", reply)
        self.assertNotIn("0xab96D9Ba2545b5BB6076A649117C5120019062Ba", reply)

    def test_ambiguous_payment_keywords_do_not_start_payment_flow(self):
        for question in ("پرداخت", "کریپتو", "کیف پول", "payment", "wallet"):
            with self.subTest(question=question):
                self.assertIsNone(get_payment_reply(question, "fa"))

    def test_clear_plan_purchase_intent_asks_for_a_coin(self):
        reply = get_payment_reply("I want this plan", "en")

        self.assertIn("which cryptocurrency", reply)
        self.assertNotIn("`", reply)

    def test_mixed_technical_and_payment_question_is_not_payment_only(self):
        self.assertFalse(is_payment_only_request("What CPU does POWER have and how can I pay?"))
        self.assertTrue(is_payment_only_request("How can I pay for POWER?"))

    def test_plan_purchase_intent_asks_for_coin_without_revealing_address(self):
        reply = get_payment_reply("POWER خوبه، همینو میخوام", "fa", "ready_to_buy")

        self.assertIn("کدوم رمزارز", reply)
        self.assertNotIn("0xab96D9Ba2545b5BB6076A649117C5120019062Ba", reply)

    def test_all_methods_request_returns_the_full_fixed_message(self):
        reply = get_payment_reply("همه روش‌های پرداخت رو نشونم بده", "fa")

        self.assertEqual(reply, PAYMENT_MESSAGE)

    def test_english_payment_reply_stays_in_english(self):
        reply = get_payment_reply(
            "send my Ethereum payment address",
            "en",
        )

        self.assertEqual(
            reply,
            "Ethereum (ETH):\n`0xab96D9Ba2545b5BB6076A649117C5120019062Ba`",
        )
        self.assertNotIn("برای", reply)

    def test_english_full_payment_message_has_no_persian_copy(self):
        reply = get_payment_reply("What cryptocurrencies do you support?", "en")

        self.assertEqual(reply, PAYMENT_MESSAGE_EN)
        self.assertIn("For payment", reply)
        self.assertNotIn("برای پرداخت", reply)

    def test_coin_followup_after_payment_question_returns_only_that_address(self):
        reply = get_payment_reply(
            "Ethereum",
            "en",
            history=[
                {
                    "role": "assistant",
                    "content": "Sure — which cryptocurrency would you prefer?",
                }
            ],
        )

        self.assertEqual(
            reply,
            "Ethereum (ETH):\n`0xab96D9Ba2545b5BB6076A649117C5120019062Ba`",
        )

    def test_delivery_question_does_not_reopen_payment_flow(self):
        question = "چقدر وقت بعد از پرداخت سرور رو تحویل میدی؟"

        self.assertIsNone(get_payment_reply(question, "fa"))
        reply = get_quick_support_reply(question, "fa")

        self.assertIsNotNone(reply)
        self.assertIn("اسکرین‌شات تراکنش", reply)
        self.assertNotIn("کدوم رمزارز", reply)

    def test_unrelated_followup_after_payment_question_is_not_a_coin_choice(self):
        reply = get_payment_reply(
            "چه زمانی فعال میشه؟",
            "fa",
            history=[
                {
                    "role": "assistant",
                    "content": "برای پرداخت با کدوم رمزارز راحت‌تری؟",
                }
            ],
        )

        self.assertIsNone(reply)


if __name__ == "__main__":
    unittest.main()