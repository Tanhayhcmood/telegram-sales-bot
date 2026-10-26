import unittest

from app.services.sales.payment import (
    PAYMENT_ADDRESSES,
    PAYMENT_MESSAGE,
    SUPPORTED_ASSETS_FA,
    get_payment_reply,
    get_requested_payment_method,
    is_payment_only_request,
    split_payment_message,
)


class PaymentTests(unittest.TestCase):
    def test_full_persian_message_has_exact_required_header_and_all_seven_assets(self):
        self.assertTrue(PAYMENT_MESSAGE.startswith(
            "✅ ما پرداخت با این ارزهای دیجیتال را قبول می‌کنیم:\n"
            "BTC • ETH • USDT • BNB • SOL • XRP • TRX\n"
            "هر ارزی را که راحت‌تری انتخاب کن، آدرسش پایین است 👇"
        ))
        for asset in ("Bitcoin (BTC)", "Ethereum (ETH)", "Tether (USDT)", "BNB", "Solana (SOL)", "XRP", "TRON (TRX)"):
            self.assertIn(asset, PAYMENT_MESSAGE)
        self.assertEqual(len(PAYMENT_ADDRESSES), 9)
        self.assertEqual(PAYMENT_MESSAGE.count("<code>"), 9)
        for address in PAYMENT_ADDRESSES.values():
            self.assertIn(f"<code>{address}</code>", PAYMENT_MESSAGE)

    def test_payment_questions_and_purchase_intent_do_not_reveal_addresses_early(self):
        for text in ("روش پرداخت چیه؟", "میخوام پرداخت کنم", "چطوری پول بدم؟", "آدرس کیف پول؟"):
            with self.subTest(text=text):
                reply = get_payment_reply(text, "fa")
                self.assertIsNotNone(reply)
                self.assertNotIn("<code>", reply)
                for address in PAYMENT_ADDRESSES.values():
                    self.assertNotIn(address, reply)

    def test_price_questions_never_enter_checkout_or_send_wallets(self):
        for text, language in (
            ("قیمت ULTRA چنده؟", "fa"),
            ("قیمت پلن Ultra چند است؟", "fa"),
            ("How much is the ULTRA plan?", "en"),
            ("What is the price of ULTRA?", "en"),
        ):
            with self.subTest(text=text):
                self.assertIsNone(get_payment_reply(text, language))
                self.assertFalse(is_payment_only_request(text))

    def test_generic_payment_words_do_not_trigger_checkout(self):
        for text in ("پرداخت", "کریپتو", "wallet", "payment", "address", "send"):
            with self.subTest(text=text):
                self.assertIsNone(get_payment_reply(text, "fa"))
                self.assertFalse(is_payment_only_request(text))

    def test_ambiguous_persian_want_to_give_does_not_start_checkout(self):
        for text in ("میخوام بدم", "می‌خوام بدم"):
            with self.subTest(text=text):
                self.assertIsNone(get_payment_reply(text, "fa"))
                self.assertFalse(is_payment_only_request(text))

    def test_purchase_without_a_currency_asks_for_selection_not_an_address(self):
        reply = get_payment_reply("I want to buy this plan", "en")
        self.assertIsNotNone(reply)
        self.assertNotIn("<code>", reply)
        for address in PAYMENT_ADDRESSES.values():
            self.assertNotIn(address, reply)

    def test_method_question_reports_supported_options_without_addresses(self):
        reply = get_payment_reply("What payment methods do you accept?", "en")
        self.assertIn("BTC", reply)
        self.assertIn("Which currency and network", reply)
        self.assertNotIn("<code>", reply)

    def test_mixed_price_and_payment_question_is_not_payment_only(self):
        text = "How much is ULTRA, and what payment methods do you accept?"
        self.assertIsNotNone(get_payment_reply(text, "en"))
        self.assertFalse(is_payment_only_request(text))

    def test_coin_reply_after_checkout_selection_sends_only_selected_address(self):
        reply = get_payment_reply(
            "Ethereum",
            "en",
            history=[{"role": "assistant", "content": "Which currency and network would you like to use?"}],
        )
        self.assertIsNotNone(reply)
        self.assertIn(PAYMENT_ADDRESSES["ETH"], reply)
        self.assertEqual(reply.count("<code>"), 1)

    def test_pay_command_returns_full_fixed_list(self):
        self.assertEqual(get_payment_reply("/pay", "fa"), PAYMENT_MESSAGE)
        self.assertEqual(get_payment_reply("/pay@SalesBot", "fa"), PAYMENT_MESSAGE)

    def test_usdt_purchase_intent_asks_for_network_before_sending_an_address(self):
        reply = get_payment_reply("USDT می‌خوام بدم", "fa")
        self.assertIn("TRC20", reply)
        self.assertIn("ERC20", reply)
        self.assertIn("BEP20", reply)
        self.assertNotIn("<code>", reply)

    def test_specific_usdt_network_selection_sends_only_that_address(self):
        reply = get_payment_reply("USDT TRC20 می‌خوام بدم", "fa")
        self.assertIn("TRC20 (Tron)", reply)
        self.assertEqual(reply.count("<code>"), 1)
        self.assertNotIn("ERC20 (Ethereum)", reply)
        self.assertNotIn("BEP20 (BNB Smart Chain)", reply)

    def test_network_qualified_usdt_returns_only_that_network(self):
        reply = get_payment_reply("USDT TRC20 payment address", "en")
        self.assertIn("TRC20 (Tron)", reply)
        self.assertEqual(reply.count("<code>"), 1)
        self.assertNotIn("ERC20 (Ethereum)", reply)
        self.assertIn("/pay", reply)

    def test_specific_coin_returns_its_address_and_pay_instruction(self):
        reply = get_payment_reply("آدرس ETH برای پرداخت", "fa")
        self.assertIn(PAYMENT_ADDRESSES["ETH"], reply)
        self.assertEqual(reply.count("<code>"), 1)
        self.assertIn("/pay", reply)
        self.assertNotIn("Bitcoin (BTC)", reply)

    def test_supported_coin_and_network_names_are_recognized(self):
        expected = {
            "Bitcoin payment address": "BTC",
            "Ethereum payment address": "ETH",
            "USDT TRC20 address": "USDT_TRC20",
            "USDT ERC20 address": "USDT_ERC20",
            "USDT BEP20 address": "USDT_BEP20",
            "BNB payment": "BNB",
            "Solana payment": "SOL",
            "XRP payment": "XRP",
            "TRON payment": "TRX",
        }
        for message, method in expected.items():
            with self.subTest(message=message):
                self.assertEqual(get_requested_payment_method(message), method)

    def test_unsupported_doge_is_rejected_with_supported_list(self):
        reply = get_payment_reply("با دوج می‌تونم بدم؟", "fa")
        self.assertIn("این ارز را فعلاً نداریم", reply)
        self.assertIn(SUPPORTED_ASSETS_FA, reply)
        self.assertNotIn("<code>", reply)

    def test_unsupported_english_dogecoin_is_rejected(self):
        reply = get_payment_reply("Can I pay with Dogecoin?", "en")
        self.assertIn("We don't support DOGE right now", reply)
        self.assertIn("BTC • ETH • USDT • BNB • SOL • XRP • TRX", reply)

    def test_explicit_payment_intent_is_handled_in_code_but_ambiguous_topics_are_not(self):
        for text in ("روش پرداخت چیه؟", "میخوام پرداخت کنم", "/pay", "USDT می‌خوام بدم"):
            self.assertTrue(is_payment_only_request(text))
        for text in ("پرداخت", "کریپتو", "wallet", "payment", "سلام، مشخصات سرور چیه؟"):
            self.assertFalse(is_payment_only_request(text))

    def test_delivery_question_is_not_replaced_by_wallet_list(self):
        self.assertIsNone(get_payment_reply("چقدر بعد از پرداخت سرور تحویل میدی؟", "fa"))

    def test_english_payment_options_stay_in_english_without_addresses(self):
        reply = get_payment_reply("What payment methods do you accept?", "en")
        self.assertIn("✅ We accept payment in these cryptocurrencies:", reply)
        self.assertNotIn("<code>", reply)
        self.assertNotIn("✅ ما پرداخت", reply)

    def test_message_splitter_keeps_every_chunk_under_telegram_limit(self):
        long_message = "\n".join([PAYMENT_MESSAGE] * 6)
        chunks = split_payment_message(long_message, limit=4096)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 4096 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
