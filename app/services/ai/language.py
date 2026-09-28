import re


SUPPORTED_LANGUAGES = {
    "en": "English",
    "fa": "Persian (Farsi)",
}

DEFAULT_LANGUAGE = "en"

# Persian-specific characters that don't exist in standard Arabic. These
# provide a reliable fast path for the only non-English response mode.
_PERSIAN_EXCLUSIVE = set("پچژگکی‌")

# Common Persian words that may contain no Persian-exclusive character after
# copy/paste normalization. Keep this list intentionally conservative: every
# other language must use the English response mode.
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


def normalize_language_code(code: str | None) -> str:
    """Normalize any stored/detected locale to the two customer reply modes."""
    return "fa" if (code or "").casefold().replace("_", "-") == "fa" else DEFAULT_LANGUAGE


def _normalized_short_text(text: str) -> str:
    text = (text or "").casefold().replace("‌", " ")
    return " ".join(
        re.sub(r"[^\w\s\u0600-\u06ff\u0900-\u097f]", " ", text).split()
    )


def _looks_persian(text: str) -> bool:
    normalized = _normalized_short_text(text)
    if any(ch in _PERSIAN_EXCLUSIVE for ch in normalized):
        return True
    return any(
        re.search(rf"(?<!\w){re.escape(word)}(?!\w)", normalized)
        for word in _PERSIAN_WORD_HINTS
    )


async def detect_language(text: str) -> str:
    """Return Persian for Persian input and English for every other language."""
    text = (text or "").strip()
    if not text:
        return DEFAULT_LANGUAGE
    return "fa" if _looks_persian(text) else DEFAULT_LANGUAGE


def get_language_name(code: str) -> str:
    normalized = normalize_language_code(code)
    return SUPPORTED_LANGUAGES.get(normalized, SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE])