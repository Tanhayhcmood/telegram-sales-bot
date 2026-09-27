import re


SUPPORTED_LANGUAGES = {
    "en": "English",
    "fa": "Persian (Farsi)",
}

DEFAULT_LANGUAGE = "en"

# Persian-specific characters that don't exist in standard Arabic. These
# provide a reliable fast path without asking a statistical detector to pick
# among languages that the customer-facing bot does not support.
_PERSIAN_EXCLUSIVE = set("پچژگکی‌")

# Language detection must intentionally have only two outcomes. These hints
# handle short messages where script alone is ambiguous; every other language
# is English from the bot's point of view.
_SHORT_LANGUAGE_HINTS = {
    "سلام": "fa",
    "درود": "fa",
}

# Common Persian words that may contain no Persian-exclusive character after
# copy/paste normalization (for example, "سلام"). This is deliberately a
# small allow-list: anything not confidently Persian must produce English.
_PERSIAN_WORD_HINTS = (
    "سلام",
    "درود",
    "سرور",
    "پرداخت",
    "واریز",
    "رمزارز",
    "کیف پول",
    "قیمت",
    "میخوام",
    "می خواهم",
    "می‌خواهم",
    "برای",
    "چطور",
    "میشه",
    "ممنون",
    "لطفا",
    "لطفاً",
)


def _normalized_short_text(text: str) -> str:
    text = (
        text.casefold()
        .replace("‌", " ")
    )
    return " ".join(
        re.sub(r"[^\w\s\u0600-\u06ff\u0900-\u097f]", " ", text).split()
    )


def _looks_persian(text: str) -> bool:
    """
    Return True only when the message contains a strong Persian signal.

    This is intentionally not a general-purpose language detector. The bot
    has exactly two response modes: Persian for confidently Persian input and
    standard English for everything else.
    """
    normalized = _normalized_short_text(text)
    if any(ch in _PERSIAN_EXCLUSIVE for ch in normalized):
        return True
    return any(
        re.search(rf"(?<!\w){re.escape(word)}(?!\w)", normalized)
        for word in _PERSIAN_WORD_HINTS
    )


async def detect_language(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return DEFAULT_LANGUAGE

    normalized = _normalized_short_text(text)
    if normalized in _SHORT_LANGUAGE_HINTS:
        return _SHORT_LANGUAGE_HINTS[normalized]

    return "fa" if _looks_persian(text) else DEFAULT_LANGUAGE


def get_language_name(code: str) -> str:
    return SUPPORTED_LANGUAGES.get(
        "fa" if code == "fa" else DEFAULT_LANGUAGE,
        "English",
    )