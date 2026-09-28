"""Deterministic crypto payment responses.

Wallet addresses are financial destination data. Keep them in this module and
never ask the language model to generate, copy, or transform them.
"""

from __future__ import annotations

from app.services.sales.quick_support import is_delivery_question


PAYMENT_ADDRESSES = {
    "USDT_BEP20": "0xab96D9Ba2545b5BB6076A649117C5120019062Ba",
    "USDT_ERC20": "0xab96D9Ba2545b5BB6076A649117C5120019062Ba",
    "USDT_TRC20": "TEaoA6zo6oytwpEUe6P3EmuoXB128dReiJ",
    "BTC": "bc1qe4u06ttrj9c37lmlkv7rks6h7tyttwe2sfwffe",
    "ETH": "0xab96D9Ba2545b5BB6076A649117C5120019062Ba",
    "BNB": "0xab96D9Ba2545b5BB6076A649117C5120019062Ba",
    "TRX": "TEaoA6zo6oytwpEUe6P3EmuoXB128dReiJ",
}

_PAYMENT_METHODS_EN = (
    ("USDT_BEP20", "USDT (BEP20 - BNB Smart Chain)"),
    ("USDT_ERC20", "USDT (ERC20 - Ethereum)"),
    ("USDT_TRC20", "USDT (TRC20 - Tron)"),
    ("BTC", "Bitcoin (BTC)"),
    ("ETH", "Ethereum (ETH)"),
    ("BNB", "BNB (BNB Smart Chain)"),
    ("TRX", "Tron (TRX)"),
)
_PAYMENT_METHODS_FA = (
    ("USDT_BEP20", "تتر (BEP20 - زنجیره BNB)"),
    ("USDT_ERC20", "تتر (ERC20 - زنجیره اتریوم)"),
    ("USDT_TRC20", "تتر (TRC20 - شبکه ترون)"),
    ("BTC", "بیت‌کوین (BTC)"),
    ("ETH", "اتریوم (ETH)"),
    ("BNB", "BNB (زنجیره BNB)"),
    ("TRX", "ترون (TRX)"),
)

_PAYMENT_HEADER = (
    "برای پرداخت، یکی از روش‌های زیر رو انتخاب کن و مبلغ رو به همون آدرس ارسال کن 👇"
)
_PAYMENT_WARNING = (
    "⚠️ توجه: هر کدوم رو انتخاب کردی، فقط همون نوع ارز رو به همون شبکه بفرست. "
    "ارسال اشتباه شبکه باعث از دست رفتن دائمی وجه می‌شه."
)
_PAYMENT_FOOTER = (
    "بعد از واریز، اسکرین‌شات تراکنش رو همینجا بفرست تا سرویس فعال بشه ✅"
)
_PAYMENT_HEADER_EN = (
    "For payment, choose one of the methods below and send the amount to the matching address 👇"
)
_PAYMENT_WARNING_EN = (
    "⚠️ Important: send only the same coin to the matching network. "
    "Sending on the wrong network can permanently lose your funds."
)
_PAYMENT_FOOTER_EN = (
    "After payment, send a screenshot of the transaction here so we can activate your service ✅"
)
_PAYMENT_METHOD_QUESTION = (
    "باشه، با کدوم رمزارز راحت‌تری؟ ما تتر (چند شبکه)، بیت‌کوین، اتریوم، BNB و ترون رو پشتیبانی می‌کنیم."
)
_PAYMENT_METHOD_QUESTION_EN = (
    "Sure — which cryptocurrency would you prefer? We support USDT (multiple networks), Bitcoin, Ethereum, BNB, and Tron."
)
_USDT_NETWORK_QUESTION = "برای تتر کدوم شبکه رو ترجیح می‌دی: BEP20، ERC20 یا TRC20؟"
_USDT_NETWORK_QUESTION_EN = "Which USDT network would you prefer: BEP20, ERC20, or TRC20?"


def _format_method(key: str, label: str) -> str:
    return f"{label}:\n`{PAYMENT_ADDRESSES[key]}`"


def _build_full_payment_message(language: str = "fa") -> str:
    payment_methods = _PAYMENT_METHODS_EN if language == "en" else _PAYMENT_METHODS_FA
    methods = "\n\n".join(
        _format_method(key, label) for key, label in payment_methods
    )
    if language == "en":
        header, warning, footer = (
            _PAYMENT_HEADER_EN,
            _PAYMENT_WARNING_EN,
            _PAYMENT_FOOTER_EN,
        )
    else:
        header, warning, footer = _PAYMENT_HEADER, _PAYMENT_WARNING, _PAYMENT_FOOTER
    return f"{header}\n\n{methods}\n\n{warning}\n{footer}"


PAYMENT_MESSAGE = _build_full_payment_message()
PAYMENT_MESSAGE_EN = _build_full_payment_message("en")


def _normalize(text: str) -> str:
    return " ".join(
        (text or "")
        .replace("\u200c", "")
        .casefold()
        .split()
    )


def _has_any(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


def _requested_method(text: str) -> str | None:
    normalized = _normalize(text)

    # Network-qualified USDT must win over the native coin with the same chain.
    if _has_any(
        normalized,
        "usdt bep20",
        "usdt on bep20",
        "تتر bep20",
        "تتر bnb",
        "bep20",
    ):
        return "USDT_BEP20"
    if _has_any(
        normalized,
        "usdt erc20",
        "usdt on erc20",
        "تتر erc20",
        "erc20",
    ):
        return "USDT_ERC20"
    if _has_any(
        normalized,
        "usdt trc20",
        "usdt on trc20",
        "usdt tron",
        "تتر trc20",
        "تتر ترون",
        "trc20",
    ):
        return "USDT_TRC20"

    if _has_any(normalized, "bitcoin", "btc", "بیت کوین", "بیتکوین"):
        return "BTC"
    if _has_any(normalized, "ethereum", "eth", "اتریوم"):
        return "ETH"
    if _has_any(normalized, "bnb", "بایننس کوین"):
        return "BNB"
    if _has_any(normalized, "tron", "trx", "ترون"):
        return "TRX"
    return None


def _has_usdt(text: str) -> bool:
    return _has_any(_normalize(text), "usdt", "تتر")


def _is_payment_request(text: str, purchase_readiness: str | None) -> bool:
    # Classifier readiness is intentionally ignored. A plan preference or a
    # model guess must never be enough to reveal a payment address.
    del purchase_readiness
    normalized = _normalize(text)

    if _wants_all_payment_methods(text):
        return True

    direct_phrases = (
        "چطور پرداخت",
        "روش پرداخت",
        "نحوه پرداخت",
        "پرداخت کنم",
        "پرداخت میکنم",
        "میخوام بخرم",
        "میخوام سفارش بدم",
        "میخوام واریز",
        "میخوام بپردازم",
        "همینو میخوام",
        "همین پلن رو میخوام",
        "سفارش میدم",
        "میخرم",
        "شماره کارت",
        "آدرس کیف پول",
        "کیف پول بده",
        "ولت",
        "آدرس بده",
        "آدرس رو بده",
        "آدرس را بده",
        "آدرس بفرست",
        "آدرس رو بفرست",
        "واریز کنم",
        "ready to pay",
        "i want to buy",
        "i would like to buy",
        "i will pay",
        "i want this plan",
        "i want the plan",
        "i want to order",
        "i'll buy",
        "ill buy",
        "i will buy",
        "place my order",
        "i'm ready to pay",
        "im ready to pay",
        "let me pay",
        "how can i pay",
        "how do i pay",
        "payment method",
        "wallet address",
        "send me the address",
        "where do i send",
    )
    if _has_any(normalized, *direct_phrases):
        return True

    has_coin = _requested_method(normalized) is not None
    return has_coin and _has_any(
        normalized,
        "آدرس",
        "بده",
        "بفرست",
        "فقط",
        "address",
        "send",
    )


_NON_PAYMENT_QUESTION_HINTS = (
    "مشخصات",
    "چند هسته",
    "هسته",
    "رم",
    "حافظه",
    "فضا",
    "ssd",
    "cpu",
    "ram",
    "windows",
    "لینوکس",
    "اوبونتو",
    "گیم",
    "بازی",
    "ترید",
    "سرعت",
    "عملکرد",
    "what cpu",
    "how much ram",
    "how many cores",
    "spec",
    "specs",
    "performance",
    "windows",
    "linux",
    "ubuntu",
    "trading",
    "game",
    "delivery",
    "activate",
    "activation",
    "when will",
    "how long",
)


def is_payment_only_request(text: str) -> bool:
    """Return whether an explicit payment request contains no other question.

    Payment-only messages can be answered by the deterministic payment router.
    Mixed messages must continue through the normal response path so the model
    can answer the customer's product or technical question first.
    """
    normalized = _normalize(text)
    if is_delivery_question(text) or not _is_payment_request(text, None):
        return False
    if "?" in text or "؟" in text:
        return not any(hint in normalized for hint in _NON_PAYMENT_QUESTION_HINTS)
    return not any(hint in normalized for hint in _NON_PAYMENT_QUESTION_HINTS)


def _is_short_payment_selection(text: str) -> bool:
    """Only treat a short coin/network choice as an answer to our payment question."""
    normalized = _normalize(text)
    if not normalized or is_delivery_question(normalized):
        return False

    method = _requested_method(normalized)
    word_count = len(normalized.split())
    if method is not None:
        return word_count <= 6 or _has_any(
            normalized,
            "میخوام",
            "می‌خوام",
            "می خواهم",
            "i want",
            "i prefer",
            "با ",
            "فقط ",
        )
    return _has_usdt(normalized) and word_count <= 4


def _payment_method_was_requested(
    history: list[dict] | None,
    text: str,
) -> bool:
    if not history:
        return False
    if not _is_short_payment_selection(text):
        return False
    last_assistant = next(
        (
            message.get("content", "")
            for message in reversed(history)
            if message.get("role") == "assistant"
        ),
        "",
    )
    normalized = _normalize(last_assistant)
    return _has_any(
        normalized,
        "کدوم رمزارز",
        "کدام رمزارز",
        "which cryptocurrency",
        "which crypto",
        "which usdt network",
    )


def _wants_all_payment_methods(text: str) -> bool:
    normalized = _normalize(text)
    return _has_any(
        normalized,
        "همه روش",
        "همه آدرس",
        "چه رمزارزهایی",
        "چه ارزهایی",
        "کلا چه",
        "all payment methods",
        "all payment options",
        "all addresses",
        "which cryptocurrencies",
        "what cryptocurrencies",
        "what coins",
        "supported cryptocurrencies",
    )


def _format_single_method(key: str, language: str) -> str:
    methods = _PAYMENT_METHODS_EN if language == "en" else _PAYMENT_METHODS_FA
    return _format_method(key, dict(methods)[key])


def get_payment_reply(
    text: str,
    language: str,
    purchase_readiness: str | None = None,
    history: list[dict] | None = None,
) -> str | None:
    """Return a fixed payment response, or None for normal conversation flow."""
    # Only the Persian and English payment templates are translated and
    # verified. For every other detected language, let the language-aware
    # conversation model respond instead of sending English text.
    if language not in {"fa", "en"}:
        return None

    # "How long after payment will delivery take?" is a support question, not
    # a request to choose a coin. It must never reopen the payment flow.
    explicit_payment_request = (
        False if is_delivery_question(text) else _is_payment_request(text, purchase_readiness)
    )
    method = _requested_method(text)
    method_followup = _payment_method_was_requested(history, text)

    if not explicit_payment_request and not method_followup:
        return None

    if method:
        return _format_single_method(method, language)

    if _has_usdt(text):
        return _USDT_NETWORK_QUESTION if language == "fa" else _USDT_NETWORK_QUESTION_EN

    if _wants_all_payment_methods(text):
        return PAYMENT_MESSAGE if language == "fa" else PAYMENT_MESSAGE_EN

    return _PAYMENT_METHOD_QUESTION if language == "fa" else _PAYMENT_METHOD_QUESTION_EN