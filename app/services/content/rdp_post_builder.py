"""Build a localized public VPS promotion without publishing server access details."""
import html
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
RDP_BANNER_IMAGE = "GENERATE_VPS_DESKTOP"
_HEADER_EMOJIS = ("🟢", "⚡", "🌐")
_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "vps_promo.json"


def _load_templates() -> dict:
    with _TEMPLATE_PATH.open(encoding="utf-8") as template_file:
        return json.load(template_file)


def _language_key(language: str | None) -> str:
    requested = (language or "en").strip().lower().replace("_", "-").split("-", 1)[0]
    templates = _load_templates()
    return requested if requested in templates else "en"


def _now_text() -> str:
    return datetime.now(TEHRAN).strftime("%d %b %Y %H:%M")


def _escape_dynamic(value: object, max_output_length: int = 96) -> str:
    """Escape and bound user-configured display data for compact captions."""
    normalized = str(value).replace("\r", " ").replace("\n", " ").strip()
    escaped_parts = []
    output_length = 0
    for character in normalized:
        escaped_character = html.escape(character, quote=True)
        if output_length + len(escaped_character) > max_output_length:
            break
        escaped_parts.append(escaped_character)
        output_length += len(escaped_character)
    return "".join(escaped_parts)


def build_vps_promo_post(
    *,
    language: str = "en",
    location: str = "Ask support for current regions",
    cpu: str = "",
    ram: str = "",
    os_name: str = "",
    time_value: str | None = None,
    admin_username: str = "VPS24H",
    seed: int = 0,
) -> tuple[str, str]:
    """Render a short promo with configured, non-sensitive server specs only."""
    templates = _load_templates()
    language = _language_key(language)
    locale = templates[language]
    variant = int(seed) % len(_HEADER_EMOJIS)
    admin_username_raw = str(admin_username).lstrip("@").strip()[:32] or "VPS24H"
    safe_values = {
        "header_emoji": _HEADER_EMOJIS[variant],
        "region_label": locale["region"],
        "updated_label": locale["updated"],
        "cpu_label": locale["cpu"],
        "ram_label": locale["ram"],
        "os_label": locale["os"],
        "cpu": _escape_dynamic(str(cpu).strip() or locale["specs_request"], 36),
        "ram": _escape_dynamic(str(ram).strip() or locale["specs_request"], 28),
        "os_name": _escape_dynamic(str(os_name).strip() or locale["specs_request"], 48),
        "location": _escape_dynamic(location, 80),
        "time": _escape_dynamic(time_value or _now_text(), 48),
        "admin_username": _escape_dynamic(admin_username_raw, 32),
        "sales_text": html.escape(
            locale["sales"][variant].format(admin_username=admin_username_raw),
            quote=True,
        ),
    }
    return locale["template"].format(**safe_values), RDP_BANNER_IMAGE


def build_rdp_post(
    ip: str = "",
    port: int | str = "",
    username: str = "",
    password: str = "",
    country_name: str = "",
    country_flag: str = "",
    seed: int = 0,
    channel_username: str | None = None,
    language: str = "en",
) -> tuple[str, str]:
    """Compatibility adapter: discard all scan and credential data."""
    del ip, port, username, password, country_name, country_flag, channel_username
    return build_vps_promo_post(language=language, seed=seed)


def build_rdp_test_caption(channel_username: str | None = None) -> str:
    """Build a sample marketing caption containing no connection details."""
    del channel_username
    text, _ = build_vps_promo_post(language="en", seed=0)
    return "🧪 TEST ONLY — NOT A LIVE SERVER\n\n" + text


def rdp_caption_utf16_length(content: str) -> int:
    """Return the caption length Telegram measures after HTML is parsed."""
    visible_text = html.unescape(re.sub(r"<[^>]*>", "", content))
    return len(visible_text.encode("utf-16-le")) // 2


def fit_rdp_caption(content: str, max_length: int = 1024) -> tuple[str, int]:
    """Retain the legacy helper while enforcing Telegram's photo-caption limit."""
    current_length = rdp_caption_utf16_length(content)
    if current_length > max_length:
        raise ValueError(
            f"VPS promo exceeds Telegram's single-photo caption limit "
            f"({current_length}/{max_length} UTF-16 units)"
        )
    return content, 0
