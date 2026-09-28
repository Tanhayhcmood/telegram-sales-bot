import unittest
from types import SimpleNamespace

from app.services.ai.prompts import get_system_prompt
from app.services.sales.order_flow import (
    extract_plan,
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

    def test_order_state_keeps_plan_and_stage_in_existing_metadata(self):
        customer = SimpleNamespace(metadata_={})

        state = update_order_state(customer, "payment_pending", plan="POWER", payment_method="ETH")

        self.assertEqual(state["stage"], "payment_pending")
        self.assertEqual(state["plan"], "POWER")
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

        self.assertIn("CHECKOUT OWNERSHIP — GUIDE THE CUSTOMER ALL THE WAY", prompt)
        self.assertIn("Never say “paid,” “confirmed,” “completed,” or “activated”", prompt)


if __name__ == "__main__":
    unittest.main()