"""Deterministic answers for direct Persian plan questions.

These questions are not needs-discovery prompts.  Once a customer has shared
their use case, asking for it again feels like the conversation lost state.
Keep this small router ahead of the LLM so pricing and adjacent-plan questions
always get a useful answer.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

PLAN_ORDER = ("ENTRY LEVEL", "POWER", "ELITE", "ULTRA")

_PLAN_ALIASES = {
    "ENTRY LEVEL": ("ENTRY LEVEL", "ENTRY", "پلن پایه", "پلن ورودی"),
    "POWER": ("POWER",),
    "ELITE": ("ELITE",),
    "ULTRA": ("ULTRA",),
}

_FA_PLAN_DETAILS = {
    "ENTRY LEVEL": {
        "label": "ENTRY",
        "specs": "۴ هسته، ۸ گیگ رم و ۱۲۰ گیگ SSD",
        "price": "۱۱ دلار در ماه (تخفیف‌دار)",
        "benefit": "برای استفاده شخصی و کارهای سبک",
    },
    "POWER": {
        "label": "POWER",
        "specs": "۶ هسته، ۱۶ گیگ رم و ۲۵۰ گیگ SSD",
        "price": "۲۰ دلار در ماه (تخفیف‌دار)",
        "benefit": "برای یه سرور گیم با چند نفر دوستت، چند بات و کارهای رو‌به‌رشد",
    },
    "ELITE": {
        "label": "ELITE",
        "specs": "۸ هسته، ۳۲ گیگ رم و ۵۰۰ گیگ SSD",
        "price": "۳۱ دلار در ماه (تخفیف‌دار)",
        "benefit": "برای پروژه‌های سنگین‌تر و ترافیک بالاتر",
    },
    "ULTRA": {
        "label": "ULTRA",
        "specs": "۱۲ هسته، ۶۴ گیگ رم و ۱ ترابایت SSD",
        "price": "قیمت با استعلام",
        "benefit": "بالاترین گزینه برای پروژه‌های حرفه‌ای و پرترافیک",
    },
}


def _normalize_digits(text: str) -> str:
    translation = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789",
    )
    return text.translate(translation)


def _normalized(text: str) -> str:
    text = _normalize_digits(text or "").replace("\u200c", "").casefold()
    text = re.sub(r"[؟?!،؛,:.()\[\]{}«»\"']", " ", text)
    return " ".join(text.split())


def _contains_any(text: str, phrases: Iterable[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def _direct_question_kind(text: str) -> str | None:
    normalized = _normalized(text)

    # Check adjacent-plan wording first because it can also contain "قیمت".
    if _contains_any(
        normalized,
        (
            "پلن بعدی",
            "پلن بعد از این",
            "بعد از این چی",
            "بعدی چیه",
            "بعدش چی",
            "مرحله بعد",
            "بالاتر از این",
            "قوی تر از این",
            "قویتر از این",
        ),
    ):
        return "next"
    if _contains_any(
        normalized,
        (
            "ارزون تر",
            "ارزان تر",
            "ارزونتر",
            "ارزانتر",
            "پایین تر",
            "پایینتر",
            "کم هزینه تر",
            "ارزون تر چی",
            "ارزان تر چی",
        ),
    ):
        return "cheaper"
    if _contains_any(
        normalized,
        (
            "گرون تر",
            "گران تر",
            "گرونتر",
            "گرانتر",
            "بیشتره",
            "قوی تر",
            "قویتر",
        ),
    ):
        return "more_expensive"
    if _contains_any(normalized, ("فرقش", "تفاوتش", "فرق این", "مقایسه")):
        return "compare"
    if _contains_any(
        normalized,
        (
            "قیمت",
            "هزینه",
            "تعرفه",
            "چنده",
            "چندن",
            "چقدره",
            "چقدر میشه",
        ),
    ):
        return "price"
    return None


def _plans_in_text(text: str) -> list[str]:
    normalized = _normalized(text)
    found_with_positions: list[tuple[int, str]] = []
    for plan in PLAN_ORDER:
        positions = [
            normalized.find(alias.casefold())
            for alias in _PLAN_ALIASES[plan]
            if normalized.find(alias.casefold()) >= 0
        ]
        if positions:
            found_with_positions.append((min(positions), plan))
    return [plan for _, plan in sorted(found_with_positions)]


def _current_plan(history: list[dict]) -> str | None:
    """Use the first plan in the latest assistant recommendation as current."""
    for message in reversed(history):
        if message.get("role") != "assistant":
            continue
        plans = _plans_in_text(message.get("content", ""))
        if plans:
            return plans[0]
    return None


def _plan_details(plan_name: str) -> dict:
    return _FA_PLAN_DETAILS[plan_name]


def _plan_index(plan_name: str | None) -> int:
    return PLAN_ORDER.index(plan_name) if plan_name in PLAN_ORDER else 0


def _plan_line(plan_name: str) -> str:
    plan = _plan_details(plan_name)
    return (
        f"{plan['specs']} و {plan['price']}. "
        f"{plan['benefit']}."
    )


def has_customer_context_hint(text: str) -> bool:
    """Return whether the current message already contains a concrete need."""
    normalized = _normalized(text)
    return bool(
        _contains_any(
            normalized,
            (
                "گیم",
                "بازی",
                "سرور بازی",
                "بات",
                "ربات",
                "سایت",
                "وبسایت",
                "فروشگاه",
                "شخصی",
                "سبک",
                "تست",
                "پروژه",
                "game",
                "bot",
                "website",
                "wordpress",
                "testing",
                "personal",
            ),
        )
        or re.search(r"\d+\s*(?:گیگ|gb|رم|ram|هسته|core|vcpu|cpu)", normalized)
    )


def _plan_for_customer_context(text: str) -> tuple[str, str] | None:
    """Choose a safe first recommendation from an explicit use-case/spec hint."""
    normalized = _normalized(text)

    ram_match = re.search(r"(\d+)\s*(?:گیگ|gb)\s*(?:رم|ram)?", normalized)
    if ram_match:
        ram = int(ram_match.group(1))
        if ram >= 64:
            return "ULTRA", "این مقدار رم"
        if ram >= 32:
            return "ELITE", "این مقدار رم"
        # Keep headroom for the customer's requested size, as requested by
        # the sales flow: an 8 GB request should not be matched to the floor.
        if ram >= 8:
            return "POWER", "این مقدار رم"
        return "ENTRY LEVEL", "این مقدار رم"

    core_match = re.search(r"(\d+)\s*(?:هسته|core|vcpu|cpu)", normalized)
    if core_match:
        cores = int(core_match.group(1))
        if cores >= 12:
            return "ULTRA", "این تعداد هسته"
        if cores >= 8:
            return "ELITE", "این تعداد هسته"
        if cores >= 6:
            return "POWER", "این تعداد هسته"
        return "ENTRY LEVEL", "این تعداد هسته"

    if _contains_any(
        normalized,
        ("پروژه سنگین", "ترافیک بالا", "بازی پرکاربر", "heavy", "high traffic"),
    ):
        return "ELITE", "پروژه یا ترافیک سنگین"
    if _contains_any(
        normalized,
        ("گیم", "بازی", "بات", "ربات", "سایت", "وبسایت", "فروشگاه", "game", "bot", "website"),
    ):
        return "POWER", "این کاربرد"
    if _contains_any(normalized, ("شخصی", "سبک", "تست", "personal", "light", "testing")):
        return "ENTRY LEVEL", "این کاربرد سبک"
    return None


def _context_reply(plan_name: str, reason: str) -> str:
    plan = _plan_details(plan_name)
    return (
        f"برای {reason}، پلن {plan['label']} مناسبه: {plan['specs']} و "
        f"{plan['price']}. {plan['benefit']}."
    )


_DISCOUNT_DETAILS = {
    "ENTRY LEVEL": ("16", "11", "5"),
    "POWER": ("28", "20", "8"),
    "ELITE": ("45", "31", "14"),
}


def _is_discount_question(text: str) -> bool:
    normalized = _normalized(text)
    return bool(
        _contains_any(
            normalized,
            (
                "تخفیف",
                "چقدر کمتر",
                "چند دلار کم",
                "discount",
                "save",
            ),
        )
        or re.search(r"\boff\b", normalized)
    )


def get_discount_reply(
    text: str,
    history: list[dict],
    language: str,
) -> str | None:
    """Return the fixed discount answer when the customer asks about savings."""
    if not _is_discount_question(text):
        return None

    plan_name = _current_plan(history) or (_plans_in_text(text) or ["POWER"])[0]
    if plan_name == "ULTRA":
        if language == "fa" or re.search(r"[\u0600-\u06ff]", text or ""):
            return "قیمت ULTRA با استعلام اعلام می‌شه؛ تخفیف فعلیش رو باید از تیم بررسی کنم."
        return "ULTRA is quote-based, so I need to confirm its current discount with the team."

    regular, current, savings = _DISCOUNT_DETAILS[plan_name]
    if language == "fa" or re.search(r"[\u0600-\u06ff]", text or ""):
        return (
            f"روی پلن {plan_name} الان ۳۰٪ تخفیف داریم؛ از {regular} دلار در ماه "
            f"شده {current} دلار، یعنی {savings} دلار کمتر."
        )
    return (
        f"{plan_name} is currently 30% off — from ${regular}/month down to "
        f"${current}/month, so you save ${savings}."
    )


def _compare_line(left: str, right: str) -> str:
    left_plan = _plan_details(left)
    right_plan = _plan_details(right)
    return (
        f"{left_plan['label']} نسبت به {right_plan['label']}، "
        f"{left_plan['specs']} داره و {left_plan['price']}؛ "
        f"{right_plan['label']} {right_plan['specs']} و {right_plan['price']} داره."
    )


def get_direct_sales_reply(
    text: str,
    history: list[dict],
    language: str,
) -> str | None:
    """Return a direct Persian plan answer, or None for normal LLM handling."""
    if language != "fa" and not re.search(r"[\u0600-\u06ff]", text or ""):
        return None

    kind = _direct_question_kind(text)
    if kind is None:
        context_plan = _plan_for_customer_context(text)
        if context_plan:
            return _context_reply(*context_plan)
        return None

    current = _current_plan(history) or (_plans_in_text(text) or ["ENTRY LEVEL"])[0]
    current_index = _plan_index(current)

    if kind == "next":
        if current_index >= len(PLAN_ORDER) - 1:
            return "ULTRA بالاترین پلنه و گزینه‌ای بالاتر از این نداریم. اگر مشخصات حرفه‌ای‌تری لازم داری، باید کانفیگ سفارشی بررسی بشه."
        target = PLAN_ORDER[current_index + 1]
        return (
            f"پلن بعدی {target} هست، {_plan_line(target)} "
            f"می‌خوای همین رو ثبت کنم یا {_plan_details(current)['label']} برات کافیه؟"
        )

    if kind == "cheaper":
        if current_index == 0:
            return "ENTRY پایین‌ترین پلنه: ۴ هسته، ۸ گیگ رم و ۱۲۰ گیگ SSD با قیمت ۱۱ دلار در ماه (تخفیف‌دار)."
        target = PLAN_ORDER[current_index - 1]
        return f"بله، گزینه ارزان‌تر {target} هست؛ {_plan_line(target)}"

    if kind == "more_expensive":
        if current_index >= len(PLAN_ORDER) - 1:
            return "ULTRA بالاترین پلنه و گزینه‌ای گران‌تر از این نداریم. برای نیاز خاص می‌تونیم کانفیگ سفارشی بررسی کنیم."
        target = PLAN_ORDER[current_index + 1]
        return f"بله، گزینه قوی‌تر و گران‌تر {target} هست؛ {_plan_line(target)}"

    if kind == "compare":
        if current_index == 0:
            return "ENTRY پایین‌ترین پلنه؛ برای مقایسه با پلن بالاتر، POWER شش هسته، ۱۶ گیگ رم و ۲۵۰ گیگ SSD داره و ۲۰ دلار در ماهه."
        previous = PLAN_ORDER[current_index - 1]
        return _compare_line(current, previous)

    return f"قیمت {current} {_plan_details(current)['price']} است. {_plan_line(current)}"
