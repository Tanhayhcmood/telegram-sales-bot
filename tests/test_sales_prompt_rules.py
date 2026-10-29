import unittest

from app.services.ai.prompts import get_system_prompt


class SalesPromptRulesTests(unittest.TestCase):
    def test_sara_identity_and_no_repeat_greeting_rule(self):
        prompt = get_system_prompt("fa", is_first_reply=False)

        self.assertIn("You are Sara", prompt)
        self.assertIn("answer naturally and honestly", prompt)
        self.assertIn("Do not greet again", prompt)

    def test_customer_context_skips_discovery(self):
        prompt = get_system_prompt("fa", customer_provided_context=True)

        self.assertIn("Do not ask what they need the server for", prompt)
        self.assertIn("Recommend the closest plan directly", prompt)

    def test_language_policy_has_only_persian_and_english_modes(self):
        prompt = get_system_prompt("nl")

        self.assertIn("every other language → reply only in clear, standard English", prompt)
        self.assertIn("selected response mode is English", prompt)
        self.assertNotIn("selected response mode is Dutch", prompt)

    def test_free_server_policy_forbids_inventing_free_private_servers(self):
        prompt = get_system_prompt("fa")

        self.assertIn("Free server offers are announced only in the channel", prompt)
        self.assertIn("never claim or imply that a private server is free", prompt)
        self.assertIn("fixed-style reply", prompt)
        self.assertNotIn("show all four plans for this question", prompt)
        self.assertIn("ULTRA is quote-only", prompt)

    def test_payment_policy_requires_explicit_address_or_checkout_choice(self):
        prompt = get_system_prompt("en")

        self.assertIn("A price, plan, or specification question never starts checkout", prompt)
        self.assertIn("A general payment-method question gets supported methods only", prompt)
        self.assertIn("Send only the matching configured address", prompt)
        self.assertIn("do not send addresses yet", prompt)
        self.assertIn("A price question is informational", prompt)

    def test_persian_prompt_keeps_price_and_specs_separate_from_wallets(self):
        prompt = get_system_prompt("fa")

        self.assertIn("قیمت‌پرسیدن، پرسیدن مشخصات یا نام‌بردن از یک پلن به معنی آمادگی خرید نیست", prompt)
        self.assertIn("آدرس فقط بعد از درخواست صریح آدرس", prompt)
        self.assertIn("قیمت‌پرسیدن", prompt)


if __name__ == "__main__":
    unittest.main()