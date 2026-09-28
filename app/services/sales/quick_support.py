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
            "حتماً. پس از پرداخت، تصویر رسید (اسکرین‌شات تراکنش) و در صورت امکان TXID یا هش تراکنش را همینجا ارسال کن "
            "تا تیم مالی بررسی کند. پس از تأیید نهایی، فعال‌سازی سرویس انجام می‌شود و زمان دقیق تحویل را همینجا اعلام می‌کنیم."
        )

    return (
        "Certainly. After payment, send the receipt and, if available, the TXID or transaction hash here "
        "so the finance team can verify it. Once payment is confirmed, activation will proceed and we’ll confirm the exact delivery timing here."
    )