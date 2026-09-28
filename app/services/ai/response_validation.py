"""Safety checks applied to model-generated customer replies before sending."""

from __future__ import annotations

import re

from app.services.sales.payment import PAYMENT_ADDRESSES


_ALLOWED_PRODUCT_WORDS = {
    "vps",
    "vps24h",
    "power",
    "elite",
    "ultra",
    "ram",
    "cpu",
    "ssd",
    "nvme",
    "ddos",
    "gbps",
    "gb",
    "tb",
    "usd",
    "btc",
    "eth",
    "bnb",
    "trx",
    "usdt",
    "bep20",
    "erc20",
    "trc20",
}


def _has_unexpected_language(reply: str, language: str) -> bool:
    if language == "en":
        return bool(re.search(r"[\u0600-\u06ff\u0400-\u04ff]", reply))

    if language != "fa":
        return False

    if re.search(r"[\u0400-\u04ff]", reply):
        return True

    latin_words = re.findall(r"[A-Za-z][A-Za-z0-9'-]*", reply)
    if not latin_words:
        return False

    persian_letters = len(re.findall(r"[\u0600-\u06ff]", reply))
    disallowed_latin = [
        word for word in latin_words
        if word.casefold().strip("'") not in _ALLOWED_PRODUCT_WORDS
    ]
    # A Persian answer may naturally contain product names and technical
    # abbreviations. A mostly-Latin answer with multiple ordinary English
    # words is still a language switch and should not be sent.
    if persian_letters == 0:
        return len(disallowed_latin) >= 2
    return len(disallowed_latin) >= 4 and len(disallowed_latin) > persian_letters


def _contains_payment_address(reply: str) -> bool:
    return any(address in (reply or "") for address in PAYMENT_ADDRESSES.values())


def validate_reply(reply: str, language: str, payment_allowed: bool = False) -> bool:
    """Return whether a reply is safe to send for this response mode."""
    if not (reply or "").strip():
        return False
    if _has_unexpected_language(reply, language):
        return False
    if not payment_allowed and _contains_payment_address(reply):
        return False
    return True