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


def _contains_letters(text: str) -> bool:
    """Return whether text contains a Unicode letter rather than only symbols/digits."""
    return any(character.isalpha() for character in text)


async def detect_language(text: str, fallback_language: str | None = None) -> str:
    """Return the message language, preserving context for language-neutral replies.

    Short replies such as ``۸``, ``yes``, or a product name do not always carry
    enough signal to identify a language.  In that case the active conversation
    language is the safest choice; a genuinely linguistic message still wins.
    """
    text = (text or "").strip()
    if not text:
        return normalize_language_code(fallback_language)
    if _looks_persian(text):
        return "fa"
    if not _contains_letters(text):
        return normalize_language_code(fallback_language)
    return DEFAULT_LANGUAGE


def get_language_name(code: str) -> str:
    normalized = normalize_language_code(code)
    return SUPPORTED_LANGUAGES.get(normalized, SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE])