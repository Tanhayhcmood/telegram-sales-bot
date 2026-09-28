import re

try:
    from langdetect import DetectorFactory, LangDetectException, detect_langs

    # langdetect uses a random seed unless this is set. A language switch must
    # never depend on which worker happened to process the Telegram update.
    DetectorFactory.seed = 0
except ImportError:  # pragma: no cover - requirements.txt installs langdetect
    detect_langs = None

    class LangDetectException(Exception):
        pass


SUPPORTED_LANGUAGES = {
    "af": "Afrikaans",
    "ar": "Arabic",
    "bg": "Bulgarian",
    "bn": "Bengali",
    "ca": "Catalan",
    "cs": "Czech",
    "cy": "Welsh",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "fa": "Persian (Farsi)",
    "fi": "Finnish",
    "fr": "French",
    "gu": "Gujarati",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "kn": "Kannada",
    "ko": "Korean",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "mk": "Macedonian",
    "ml": "Malayalam",
    "mr": "Marathi",
    "ne": "Nepali",
    "nl": "Dutch",
    "no": "Norwegian",
    "pa": "Punjabi",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "so": "Somali",
    "sq": "Albanian",
    "sr": "Serbian",
    "sv": "Swedish",
    "sw": "Swahili",
    "ta": "Tamil",
    "te": "Telugu",
    "th": "Thai",
    "tl": "Tagalog",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "vi": "Vietnamese",
    "zh-cn": "Simplified Chinese",
    "zh-tw": "Traditional Chinese",
}

DEFAULT_LANGUAGE = "en"

_LANGUAGE_ALIASES = {
    "iw": "he",
    "in": "id",
    "ji": "yi",
    "zh": "zh-cn",
}

# Persian-specific characters that don't exist in standard Arabic.
_PERSIAN_EXCLUSIVE = set("پچژگکی‌")
_PERSIAN_WORD_HINTS = (
    "سلام", "درود", "سرور", "پرداخت", "واریز", "رمزارز", "کیف پول",
    "قیمت", "میخوام", "می خواهم", "می‌خواهم", "برای", "چطور", "میشه",
    "ممنون", "لطفا", "لطفاً",
)

# Short Telegram messages are where statistical detectors are least reliable.
# These hints cover greetings and common short phrases without locking the
# conversation to one language for longer messages.
_SHORT_LANGUAGE_HINTS = {
    "hi": "en",
    "hello": "en",
    "hey": "en",
    "سلام": "fa",
    "درود": "fa",
    "مرحبا": "ar",
    "اهلا": "ar",
    "أهلا": "ar",
    "merhaba": "tr",
    "привет": "ru",
    "здравствуйте": "ru",
    "hallo": "de",
    "bonjour": "fr",
    "hola": "es",
    "ciao": "it",
    "olá": "pt",
    "ola": "pt",
    "你好": "zh-cn",
    "こんにちは": "ja",
    "안녕하세요": "ko",
    "नमस्ते": "hi",
    "mujhe lena hai": "hi",
    "mujhe chahiye": "hi",
    "server chahiye": "hi",
}

_PRODUCT_ONLY_TOKENS = {
    "vps", "rdp", "server", "servers", "ubuntu", "windows", "linux", "ssh",
    "vpn", "hosting", "host", "bot", "game", "website", "wordpress", "ram",
    "ssd", "cpu", "vcpu", "gb", "tb", "gbps", "lts",
}


def normalize_language_code(code: str | None) -> str:
    normalized = (code or DEFAULT_LANGUAGE).casefold().replace("_", "-")
    normalized = _LANGUAGE_ALIASES.get(normalized, normalized)
    return normalized if normalized in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def _normalized_short_text(text: str) -> str:
    text = text.casefold().replace("‌", " ")
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


def _script_hint(text: str) -> str | None:
    """Return a strong script-based language hint when one is available."""
    if _looks_persian(text):
        return "fa"
    if re.search(r"[\u0590-\u05ff]", text):
        return "he"
    if re.search(r"[\u0900-\u097f]", text):
        return "hi"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    return None


async def detect_language(text: str) -> str:
    """Detect the latest customer's language instead of using a fa/en switch."""
    text = (text or "").strip()
    if not text:
        return DEFAULT_LANGUAGE

    normalized = _normalized_short_text(text)
    if normalized in _SHORT_LANGUAGE_HINTS:
        return _SHORT_LANGUAGE_HINTS[normalized]

    script_language = _script_hint(text)
    if script_language:
        return script_language

    # Product names and specs do not identify a human language. langdetect
    # may call "VPS" Lithuanian or "Ubuntu 22.04 LTS" Indonesian; keep these
    # neutral messages in English rather than switching languages randomly.
    tokens = re.findall(r"[a-z0-9]+", normalized)
    if tokens and len(tokens) <= 5 and all(
        token in _PRODUCT_ONLY_TOKENS or token.isdigit() for token in tokens
    ):
        return DEFAULT_LANGUAGE

    if detect_langs is not None:
        try:
            candidates = detect_langs(text)
            if candidates:
                return normalize_language_code(candidates[0].lang)
        except (LangDetectException, ValueError):
            pass

    return DEFAULT_LANGUAGE


def get_language_name(code: str) -> str:
    normalized = normalize_language_code(code)
    return SUPPORTED_LANGUAGES.get(normalized, SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE])