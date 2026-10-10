"""Deterministic cryptocurrency payment responses.

Wallet addresses are loaded only from wallets.json. Customer text and model
output are never used as wallet data.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from app.services.sales.quick_support import is_delivery_question


_CONFIG_PATH = Path(__file__).with_name("wallets.json")
with _CONFIG_PATH.open("r", encoding="utf-8") as _wallet_file:
    _WALLET_CONFIG = json.load(_wallet_file)

_WALLETS = _WALLET_CONFIG.get("currencies", [])
_REQUIRED_METHODS = {
    "BTC", "ETH", "USDT_TRC20", "USDT_ERC20", "USDT_BEP20",
    "BNB", "SOL", "XRP", "TRX",
}
_WALLETS_BY_KEY = {item["key"]: item for item in _WALLETS}
if set(_WALLETS_BY_KEY) != _REQUIRED_METHODS or any(
    not _WALLETS_BY_KEY[key].get("address", "").strip()
    for key in _REQUIRED_METHODS
):
    raise RuntimeError("wallets.json must contain every supported receiving address")

PAYMENT_ADDRESSES = {key: item["address"] for key, item in _WALLETS_BY_KEY.items()}
SUPPORTED_ASSETS = ("BTC", "ETH", "USDT", "BNB", "SOL", "XRP", "TRX")
SUPPORTED_ASSETS_FA = "BTC • ETH • USDT • BNB • SOL • XRP • TRX"
_SUPPORTED_LIST_FA = f"ارزهای پشتیبانی‌شده: {SUPPORTED_ASSETS_FA}"
_SUPPORTED_LIST_EN = "Supported currencies: BTC • ETH • USDT • BNB • SOL • XRP • TRX"
_SEPARATOR = "━━━━━━━━━━━━━━━"
_TELEGRAM_MESSAGE_LIMIT = 4096

_HEADER_FA = (
    "✅ ما پرداخت با این ارزهای دیجیتال را قبول می‌کنیم:\n"
    "BTC • ETH • USDT • BNB • SOL • XRP • TRX\n"
    "هر ارزی را که راحت‌تری انتخاب کن، آدرسش پایین است 👇"
)
_HEADER_EN = (
    "✅ We accept payment in these cryptocurrencies:\n"
    "BTC • ETH • USDT • BNB • SOL • XRP • TRX\n"
    "Choose whichever is convenient for you; its address is below 👇"
)
_WARNING_FA = (
    "⚠️ قبل از واریز، ارز و شبکه را دوباره بررسی کنید. "
    "بعد از پرداخت، رسید یا TXID را برای ما بفرستید."
)
_WARNING_EN = (
    "⚠️ Check the currency and network before sending. "
    "After payment, send us the receipt or TXID."
)


def _normalize(text: str) -> str:
    text = (text or "").replace("\u200c", " ").casefold()
    return " ".join(text.split())


def _contains_token(text: str, token: str) -> bool:
    token = token.casefold()
    if re.fullmatch(r"[a-z0-9]+", token):
        return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text) is not None
    return token in text


def _has_any(text: str, terms: tuple[str, ...] | list[str]) -> bool:
    return any(_contains_token(text, term) for term in terms)


def _requested_method(text: str) -> str | None:
    normalized = _normalize(text)

    # Network-qualified USDT must be checked before the native chain coin.
    if _has_any(normalized, ("usdt bep20", "usdt on bep20", "تتر bep20", "تتر bnb", "bep20", "bsc")):
        return "USDT_BEP20"
    if _has_any(normalized, ("usdt erc20", "usdt on erc20", "تتر erc20", "erc20")):
        return "USDT_ERC20"
    if _has_any(normalized, ("usdt trc20", "usdt on trc20", "usdt tron", "تتر trc20", "تتر ترون", "trc20")):
        return "USDT_TRC20"

    if _has_any(normalized, ("usdt", "tether", "تتر")):
        return "USDT"
    if _has_any(normalized, ("bitcoin", "btc", "بیت کوین", "بیتکوین", "بیت‌کوین")):
        return "BTC"
    if _has_any(normalized, ("ethereum", "eth", "اتریوم")):
        return "ETH"
    if _has_any(normalized, ("bnb", "بایننس کوین", "binance coin")):
        return "BNB"
    if _has_any(normalized, ("solana", "sol", "سولانا")):
        return "SOL"
    if _has_any(normalized, ("xrp", "ripple", "ریپل")):
        return "XRP"
    if _has_any(normalized, ("tron", "trx", "ترون")):
        return "TRX"
    return None


def get_requested_payment_method(text: str) -> str | None:
    """Return a configured currency/network key for checkout state tracking."""
    return _requested_method(text)


_UNSUPPORTED_CURRENCIES = (
    ("DOGE", ("dogecoin", "doge", "دوج کوین", "دوج‌کوین", "دوج")),
    ("LTC", ("litecoin", "ltc", "لایت کوین", "لایت‌کوین")),
    ("ADA", ("cardano", "ada", "کاردانو")),
    ("USDC", ("usdc", "usd coin")),
    ("TON", ("toncoin", "ton", "تون کوین", "تون‌کوین")),
    ("XMR", ("monero", "xmr", "مونرو")),
)
_PAYMENT_INTENT_TERMS = (
    "پرداخت", "پرداخت کنم", "واریز", "واریز کنم", "پول بدم", "پول بدهم",
    "بدم", "بده", "بفرست", "آدرس کیف پول", "آدرس ولت", "کیف پول",
    "کیفپول", "ولت", "روش پرداخت", "نحوه پرداخت", "رمزارز", "ارز دیجیتال",
    "کریپتو", "wallet", "payment", "pay", "pay with", "crypto", "cryptocurrency",
    "payment method", "wallet address", "address", "آدرس", "send", "send money",
    "money", "transfer", "deposit",
)
_DIRECT_PAYMENT_PHRASES = (
    "روش پرداخت", "نحوه پرداخت", "چطور پرداخت", "چطوری پرداخت", "چطوری پول",
    "آدرس کیف پول", "آدرس ولت", "آدرس پرداخت", "میخوام پرداخت", "می خواهم پرداخت",
    "میخوام واریز", "می خوام واریز", "آدرس رو بده", "آدرس را بده", "آدرس بفرست",
    "how can i pay", "how do i pay", "payment method", "wallet address",
    "send me the address", "where do i send", "i want to pay", "i'd like to pay",
    "i would like to pay", "i want to make a payment", "how to pay",
)


def _unsupported_currency(text: str) -> str | None:
    normalized = _normalize(text)
    for code, aliases in _UNSUPPORTED_CURRENCIES:
        if _has_any(normalized, aliases):
            return code
    return None


def _has_payment_intent(text: str, history: list[dict] | None = None) -> bool:
    normalized = _normalize(text)
    if re.search(r"(?:^|\s)/pay(?:@[a-z0-9_]+)?(?:$|\s)", normalized):
        return True
    if _has_any(normalized, _DIRECT_PAYMENT_PHRASES):
        return True
    if _has_any(normalized, _PAYMENT_INTENT_TERMS):
        return True

    method = _requested_method(normalized)
    unsupported = _unsupported_currency(normalized)
    if method or unsupported:
        # A short coin-only reply is a payment choice only when the bot was
        # already discussing payment; otherwise keep the normal conversation.
        last_assistant = next(
            (m.get("content", "") for m in reversed(history or []) if m.get("role") == "assistant"),
            "",
        )
        previous = _normalize(last_assistant)
        if any(term in previous for term in ("پرداخت", "payment", "pay", "wallet", "روش پرداخت")):
            return True
    return False


def is_payment_only_request(text: str) -> bool:
    """Compatibility helper: explicit payment requests are handled in code."""
    return _has_payment_intent(text)


def _rows_for_method(method: str) -> list[dict]:
    if method == "USDT":
        return [_WALLETS_BY_KEY[key] for key in ("USDT_TRC20", "USDT_ERC20", "USDT_BEP20")]
    return [_WALLETS_BY_KEY[method]] if method in _WALLETS_BY_KEY else []


def _format_wallet(wallet: dict, language: str) -> str:
    currency = wallet["currency"]
    if language == "fa":
        network_label = "شبکه"
    else:
        network_label = "Network"
    address = html.escape(wallet["address"], quote=True)
    name = html.escape(wallet["name"], quote=True)
    network = html.escape(wallet["network"], quote=True)
    return f"<b>{wallet['emoji']} {name}</b>\n{network_label}: {network}\n<code>{address}</code>"


def _build_wallet_message(wallets: list[dict], language: str, include_intro: bool) -> str:
    header = _HEADER_FA if language == "fa" else _HEADER_EN
    warning = _WARNING_FA if language == "fa" else _WARNING_EN
    supported = _SUPPORTED_LIST_FA if language == "fa" else _SUPPORTED_LIST_EN
    blocks = [_format_wallet(wallet, language) for wallet in wallets]
    if include_intro:
        sections = [header, _SEPARATOR, f"\n{_SEPARATOR}\n".join(blocks), _SEPARATOR, warning]
    else:
        call_to_pay = "برای دیدن بقیه ارزها /pay را بزن" if language == "fa" else "Send /pay to see all supported currencies and addresses."
        sections = ["\n".join(blocks), _SEPARATOR, supported, call_to_pay, warning]
    return "\n\n".join(sections)


def _build_full_message(language: str = "fa") -> str:
    return _build_wallet_message(_WALLETS, language, include_intro=True)


PAYMENT_MESSAGE = _build_full_message("fa")
PAYMENT_MESSAGE_EN = _build_full_message("en")


def split_payment_message(message: str, limit: int = _TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Split payment HTML only at line boundaries, below Telegram's limit."""
    chunks: list[str] = []
    current = ""
    for line in message.splitlines():
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [""]


def get_payment_reply(
    text: str,
    language: str,
    purchase_readiness: str | None = None,
    history: list[dict] | None = None,
) -> str | None:
    """Return a deterministic HTML payment response, or None for other topics."""
    del purchase_readiness  # A classifier/model guess never triggers payment.
    if is_delivery_question(text) or not _has_payment_intent(text, history):
        return None

    language = "fa" if language == "fa" else "en"
    unsupported = _unsupported_currency(text)
    if unsupported:
        supported = _SUPPORTED_LIST_FA if language == "fa" else _SUPPORTED_LIST_EN
        if language == "fa":
            return f"این ارز را فعلاً نداریم.\n{supported}\nبرای دیدن آدرس‌ها /pay را بزن"
        return f"We don't support {unsupported} right now.\n{supported}\nSend /pay to see the addresses."

    method = _requested_method(text)
    if method:
        return _build_wallet_message(_rows_for_method(method), language, include_intro=False)

    return PAYMENT_MESSAGE if language == "fa" else PAYMENT_MESSAGE_EN
