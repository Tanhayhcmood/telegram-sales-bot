import unittest

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