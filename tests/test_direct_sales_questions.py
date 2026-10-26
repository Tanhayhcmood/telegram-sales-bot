import unittest

from app.services.ai.response_validation import validate_reply
from app.services.sales.direct_questions import (
    get_discount_reply,
    get_direct_sales_reply,
)


class DirectSalesQuestionsTests(unittest.TestCase):
    HISTORY_AFTER_ENTRY = [
        {"role": "user", "content": "شخصی و ارزونه"},
        {
            "role": "assistant",
            "content": "ENTRY برای شروع مناسبه؛ ۴ هسته و ۸ گیگ رم با ۱۱ دلار در ماه.",
        },
    ]

    def test_next_plan_does_not_restart_discovery(self):
        reply = get_direct_sales_reply(
            "پلن بعدی چیه؟",
            self.HISTORY_AFTER_ENTRY,
            "fa",
        )

        self.assertIn("POWER", reply)
        self.assertNotIn("برای چه کاری", reply)

    def test_direct_price_and_comparison_questions_are_answered(self):
        for question in ("قیمتش چنده؟", "گرون‌تره؟", "فرقش با قبلی چیه؟"):
            with self.subTest(question=question):
                reply = get_direct_sales_reply(
                    question,
                    self.HISTORY_AFTER_ENTRY,
                    "fa",
                )
                self.assertIsNotNone(reply)
                self.assertNotIn("برای چه کاری", reply)

    def test_plan_order_is_preserved_when_previous_reply_mentions_two_plans(self):
        reply = get_direct_sales_reply(
            "فرقش با قبلی چیه؟",
            [
                {
                    "role": "assistant",
                    "content": "پلن بعدی POWER هست؛ می‌خوای همین رو ثبت کنم یا ENTRY برات کافیه؟",
                }
            ],
            "fa",
        )

        self.assertIn("POWER نسبت به ENTRY", reply)

    def test_price_question_is_answered_directly_without_specs_or_payment_copy(self):
        from app.services.sales.payment import get_payment_reply

        reply = get_direct_sales_reply("قیمت ULTRA چنده؟", [], "fa")

        self.assertTrue(reply.startswith("قیمت ULTRA"))
        self.assertNotIn("هسته", reply)
        self.assertNotIn("SSD", reply)
        self.assertIsNone(get_payment_reply("قیمت ULTRA چنده؟", "fa"))

    def test_ultra_has_no_higher_plan(self):
        reply = get_direct_sales_reply(
            "بالاتر از این چی دارید؟",
            [{"role": "assistant", "content": "ULTRA بالاترین گزینه است."}],
            "fa",
        )

        self.assertIn("بالاترین پلنه", reply)
        self.assertNotIn("برای چه کاری", reply)

    def test_history_keeps_previous_turns_for_follow_up(self):
        reply = get_direct_sales_reply(
            "پلن بعدیش چیه؟",
            [
                {"role": "user", "content": "برای گیم میخوام"},
                {"role": "assistant", "content": "برای گیم، ENTRY مناسب شروعه."},
            ],
            "fa",
        )

        self.assertIn("POWER", reply)
        self.assertNotIn("برای چه کاری", reply)

    def test_use_case_hint_gets_a_plan_without_discovery_question(self):
        for message in ("برای گیم میخوام", "برای استفاده شخصی و سبک", "برای بات"):
            with self.subTest(message=message):
                reply = get_direct_sales_reply(message, [], "fa")
                self.assertIsNotNone(reply)
                self.assertNotIn("برای چه کاری", reply)

    def test_requested_ram_gets_a_direct_power_recommendation(self):
        reply = get_direct_sales_reply("۸ گیگ رم میخوام", [], "fa")

        self.assertIn("POWER", reply)
        self.assertIn("۱۶ گیگ رم", reply)
        self.assertNotIn("برای چه کاری", reply)

    def test_free_server_question_returns_channel_policy_and_all_paid_vps_specs(self):
        reply = get_direct_sales_reply("سرور شخصی هم رایگان هست؟", [], "fa")

        self.assertTrue(validate_reply(reply, "fa"))
        self.assertIn("سرورهای رایگان فقط از طریق کانال", reply)
        self.assertIn("سرورهای شخصی رایگان نیستند", reply)
        for plan in ("ENTRY LEVEL", "POWER", "ELITE", "ULTRA"):
            with self.subTest(plan=plan):
                self.assertIn(plan, reply)
        for detail in ("۱۲۰ گیگ SSD", "۸ گیگ رم", "۱ گیگابیت", "۱۶ گیگ رم", "۲۵۰ گیگ SSD", "۳۲ گیگ رم", "۵۰۰ گیگ SSD", "۶۴ گیگ رم", "۱ ترابایت SSD", "۵ گیگابیت", "۱۱ دلار", "۲۰ دلار", "۳۱ دلار", "قیمت با استعلام"):
            with self.subTest(detail=detail):
                self.assertIn(detail, reply)

    def test_free_server_question_is_deterministic_in_english_too(self):
        reply = get_direct_sales_reply("Do you offer a free private server?", [], "en")

        self.assertTrue(validate_reply(reply, "en"))
        self.assertIn("Free server offers are announced only in our channel", reply)
        self.assertIn("We do not provide private servers for free", reply)
        for plan in ("ENTRY LEVEL", "POWER", "ELITE", "ULTRA"):
            with self.subTest(plan=plan):
                self.assertIn(plan, reply)
        self.assertIn("$11/month", reply)
        self.assertIn("$20/month", reply)
        self.assertIn("$31/month", reply)
        self.assertIn("current price by quote", reply)

    def test_free_setup_question_is_not_mistaken_for_a_free_server_offer(self):
        reply = get_direct_sales_reply("Is setup free for this VPS?", [], "en")

        self.assertIsNone(reply)

    def test_english_discount_question_uses_the_current_plan(self):
        reply = get_discount_reply(
            "How many dollars would you get off?",
            [{"role": "assistant", "content": "POWER is a good fit for you."}],
            "en",
        )

        self.assertEqual(
            reply,
            "POWER is currently 30% off — from $28/month down to $20/month, so you save $8.",
        )
        self.assertNotIn("تخفیف", reply)


if __name__ == "__main__":
    unittest.main()