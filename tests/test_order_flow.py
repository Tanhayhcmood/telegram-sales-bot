import unittest
from types import SimpleNamespace

from app.services.ai.prompts import get_system_prompt
from app.services.sales.order_flow import (
    append_support_reference,
    extract_plan,
    get_or_create_support_code,
    get_checkout_followup,
    get_order_status_reply,
    get_payment_next_step,
    get_payment_problem_reply,
    get_receipt_received_reply,
    has_transaction_reference,
    is_order_status_request,
    is_payment_problem_message,
    is_payment_receipt_message,
    update_order_state,
)


class OrderFlowTests(unittest.TestCase):
    def test_receipt_media_is_detected_only_as_a_pending_checkout_event(self):
        self.assertTrue(is_payment_receipt_message("", has_media=True, stage="payment_pending"))
        self.assertFalse(is_payment_receipt_message("", has_media=True, stage="plan_recommended"))
        self.assertTrue(is_payment_receipt_message("پرداخت کردم"))

    def test_receipt_acknowledges_pending_verification_without_claiming_success(self):
        reply = get_receipt_received_reply(
            "fa",
            {"order_id": "ORD-TEST", "stage": "payment_submitted"},
            has_reference=True,
        )

        self.assertIn("در انتظار تأیید پرداخت", reply)
        self.assertIn("به‌تنهایی به معنی تأیید پرداخت نیست", reply)
        self.assertNotIn("سرویس فعال شد", reply)

    def test_support_code_is_stable_per_conversation_and_persisted(self):
        conversation = SimpleNamespace(metadata_={})

        first_code, created = get_or_create_support_code(conversation)
        second_code, created_again = get_or_create_support_code(conversation)

        self.assertRegex(first_code, r"^SUP-[A-F0-9]{10}$")
        self.assertTrue(created)
        self.assertEqual(second_code, first_code)
        self.assertFalse(created_again)
        self.assertEqual(conversation.metadata_["support_code"], first_code)

    def test_support_code_is_unique_between_conversations(self):
        first, _ = get_or_create_support_code(SimpleNamespace(metadata_={}))
        second, _ = get_or_create_support_code(SimpleNamespace(metadata_={}))
        self.assertNotEqual(first, second)

    def test_support_reference_is_localized_and_not_duplicated(self):
        fa = append_support_reference("سلام", "SUP-0123456789", "fa")
        en = append_support_reference("Hello", "SUP-0123456789", "en")

        self.assertIn("کد پیگیری پشتیبانی: SUP-0123456789", fa)
        self.assertIn("Support reference: SUP-0123456789", en)
        self.assertEqual(append_support_reference(fa, "SUP-0123456789", "fa"), fa)

    def test_order_state_keeps_plan_stage_and_support_code(self):
        customer = SimpleNamespace(metadata_={})

        state = update_order_state(
            customer,
            "payment_pending",
            plan="POWER",
            payment_method="ETH",
            support_code="SUP-0123456789",
        )

        self.assertEqual(state["stage"], "payment_pending")
        self.assertEqual(state["plan"], "POWER")
        self.assertEqual(state["support_code"], "SUP-0123456789")
        self.assertEqual(customer.metadata_["order_flow"]["payment_method"], "ETH")

    def test_status_and_followup_are_specific_to_payment_waiting(self):
        state = {"order_id": "ORD-TEST", "stage": "payment_pending", "plan": "POWER"}

        self.assertTrue(is_order_status_request("وضعیت سفارشم چیه؟"))
        self.assertIn("هنوز رسیدی", get_order_status_reply("fa", state))
        self.assertIn("TXID", get_checkout_followup("fa", state))
        self.assertIn("matching network", get_payment_next_step("en", "POWER"))

    def test_payment_problem_never_promises_a_refund_or_confirmation(self):
        state = {"order_id": "ORD-TEST", "stage": "payment_pending"}

        self.assertTrue(is_payment_problem_message("شبکه رو اشتباه انتخاب کردم"))
        reply = get_payment_problem_reply("fa", state)
        self.assertIn("انتقال دیگری انجام نده", reply)
        self.assertIn("نمی‌تونم تأیید یا وعده بازگشت وجه بدم", reply)

    def test_plan_and_transaction_context_are_preserved(self):
        self.assertEqual(
            extract_plan(
                "ETH",
                [{"role": "user", "content": "POWER رو می‌خوام"}],
            ),
            "POWER",
        )
        self.assertTrue(has_transaction_reference("TXID: abcdef0123456789abcdef0123456789"))

    def test_prompt_requires_professional_checkout_ownership(self):
        prompt = get_system_prompt("fa")

        self.assertIn("CHECKOUT BOUNDARY — SALES ONLY", prompt)
        self.assertIn("Never say “paid,” “confirmed,” “completed,” or “activated”", prompt)


if __name__ == "__main__":
    unittest.main()