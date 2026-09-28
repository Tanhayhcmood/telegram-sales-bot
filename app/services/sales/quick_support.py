"""Fast, deterministic replies for common post-purchase support questions."""

from __future__ import annotations

import re


def _normalize(text: str) -> str:
    return " ".join(
        (text or "")
        .replace("\u200c", " ")
        .casefold()
        .split()
    )


def is_delivery_question(text: str) -> bool:
    """Detect delivery/activation timing without treating it as a payment request."""
    normalized = _normalize(text)
    timing_terms = (
        "چقدر",
        "چه مدت",
        "چند وقت",
        "چند ساعت",
        "چه زمانی",
        "زمان",
        "وقت",
        "how long",
        "when",
        "how soon",
    )
    delivery_terms = (
        "تحویل",
        "فعال",
        "راه اندازی",
        "راه‌اندازی",
        "سرویس",
        "سرور",
        "delivery",
        "activate",
        "activation",
        "server",
        "service",
        "provision",
    )
    after_payment_terms = (
        "بعد از پرداخت",
        "پس از پرداخت",
        "بعد پرداخت",
        "after payment",
        "once i pay",
        "after i pay",
        "when i pay",
    )
    has_timing = any(term in normalized for term in timing_terms)
    has_delivery = any(term in normalized for term in delivery_terms)
    has_after_payment = any(term in normalized for term in after_payment_terms)
    return has_after_payment and (has_timing or has_delivery) or (has_timing and has_delivery)


def get_quick_support_reply(text: str, language: str) -> str | None:
    """Return a useful answer immediately for an unambiguous support question."""
    if language not in {"fa", "en"} or not is_delivery_question(text):
        return None

    if language == "fa":
        return (
            "بعد از پرداخت، اسکرین‌شات تراکنش رو همینجا بفرست تا تیم فعال‌سازی بررسیش کنه. "
            "بعد از تأیید پرداخت، سرویس در کوتاه‌ترین زمان تحویل می‌شه و اگر زمان دقیق لازم باشه همون‌جا بهت اعلام می‌کنیم."
        )

    return (
        "After payment, send the transaction screenshot here so the activation team can verify it. "
        "Once the payment is confirmed, the server is delivered as quickly as possible, and we’ll confirm the exact timing with you."
    )