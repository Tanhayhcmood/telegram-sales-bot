import unittest

from app.services.ai.prompts import get_system_prompt


class SalesPromptRulesTests(unittest.TestCase):
    def test_sara_identity_and_no_repeat_greeting_rule(self):
        prompt = get_system_prompt("fa", is_first_reply=False)

        self.assertIn("You are Sara", prompt)
        self.assertIn("answer naturally in", prompt)
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

    def test_payment_policy_defers_wallet_answers_to_deterministic_code(self):
        prompt = get_system_prompt("en")

        self.assertIn("Never send a wallet address just because the customer likes a plan", prompt)
        self.assertIn("do not answer payment questions yourself", prompt)
        self.assertIn("application is sending the fixed payment list now", prompt)
        self.assertNotIn("ask which cryptocurrency they prefer", prompt)

    def test_persian_prompt_never_writes_wallet_or_payment_details(self):
        prompt = get_system_prompt("fa")

        self.assertIn("درباره آدرس کیف پول و روش پرداخت خودت جواب نده", prompt)
        self.assertIn("الان لیست پرداخت را می‌فرستم", prompt)


if __name__ == "__main__":
    unittest.main()