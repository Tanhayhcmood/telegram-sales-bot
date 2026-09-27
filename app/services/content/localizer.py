from app.services.ai.engine import generate_content
from app.core.logging import get_logger

logger = get_logger(__name__)

TRANSLATE_PROMPT = """Translate the following text to {language_name}.
Keep the formatting (bold, emojis, line breaks) exactly the same.
Only translate the text content, not Telegram markdown symbols.
Return ONLY the translation without any explanation.

Text to translate:
{text}"""

LANGUAGE_NAMES = {
    "en": "English", "fa": "Persian (Farsi)", "ar": "Arabic",
    "tr": "Turkish", "ru": "Russian", "de": "German",
    "fr": "French", "es": "Spanish",
}


async def translate_content(text: str, target_language: str) -> str:
    if not text:
        return text
    language_name = LANGUAGE_NAMES.get(target_language, "English")
    prompt = TRANSLATE_PROMPT.format(language_name=language_name, text=text)
    try:
        translated = await generate_content(prompt)
        return translated
    except Exception as e:
        logger.error("translation_failed", lang=target_language, error=str(e))
        return text
