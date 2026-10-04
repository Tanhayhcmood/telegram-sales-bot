"""Build the approved, fixed-layout free RDP/VPS channel post."""
import re
from datetime import datetime
from html import escape, unescape
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
FIXED_USERNAME = "Administrator"
ADMIN_URL = "https://t.me/VPS24H"

# The publisher resolves this marker to a fresh Playwright screenshot.
RDP_BANNER_IMAGE = "GENERATE_VPS_DESKTOP"


def _channel_link(username: str | None) -> str:
    if not username:
        return "this channel"
    safe_username = escape(username.lstrip("@"), quote=True)
    return f'<a href="https://t.me/{safe_username}">channel</a>'


def _now_parts() -> tuple[str, str]:
    now = datetime.now(TEHRAN)
    return now.strftime("%d %b %Y"), now.strftime("%H:%M")


def rdp_caption_utf16_length(content: str) -> int:
    """Return the caption length Telegram measures after HTML entities are parsed."""
    visible_text = unescape(re.sub(r"<[^>]*>", "", content))
    return len(visible_text.encode("utf-16-le")) // 2


def fit_rdp_caption(content: str, max_length: int = 1024) -> tuple[str, int]:
    """Keep an RDP post intact in one photo caption, compacting only divider rules."""
    current_length = rdp_caption_utf16_length(content)
    if current_length <= max_length:
        return content, 0

    lines = content.split("\n")
    removed = 0
    while current_length > max_length:
        candidates = [
            index
            for index, line in enumerate(lines)
            if len(line) > 18
            and line[0] in {"═", "─"}
            and all(char == line[0] for char in line)
        ]
        if not candidates:
            break
        index = max(candidates, key=lambda item: len(lines[item]))
        lines[index] = lines[index][:-1]
        current_length -= 1
        removed += 1

    if current_length > max_length:
        raise ValueError(
            f"RDP post exceeds Telegram's single-photo caption limit "
            f"({current_length}/{max_length} UTF-16 units)"
        )
    return "\n".join(lines), removed


def build_rdp_post(
    ip: str,
    port: int,
    username: str,
    password: str,
    country_name: str,
    country_flag: str,
    seed: int,
    channel_username: str | None = None,
) -> tuple[str, str]:
    """Build the approved fixed RDP post; only server details and live time vary."""
    del username, seed  # The approved copy always uses the same login name and wording.
    date_str, time_str = _now_parts()
    safe_ip = escape(str(ip))
    safe_port = escape(str(port))
    safe_password = escape(str(password))
    if not country_name or country_name.strip().lower() == "unknown":
        location = "Unknown"
    else:
        location = f"{escape(country_flag)} {escape(country_name)}".strip()
    channel_link = _channel_link(channel_username)
    admin_link = f'<a href="{ADMIN_URL}">@VPS24H</a>'

    text = (
        "🔥 FREE RDP • FREE VPS • WINDOWS RDP • CLOUD VPS 🔥\n"
        "═══════════════════════════════════\n"
        "📡 Live server drop — free access for everyone\n"
        "🔓 Full admin rights · Windows Server\n"
        f"📍 🌐 {location} · Port {safe_port}\n\n"
        "  ┌───────────────────────────────┐\n"
        f"  │  🌐  {safe_ip}:{safe_port}\n"
        f"  │  👤  {FIXED_USERNAME}\n"
        f"  │  🔑  {safe_password}\n"
        f"  │  🟢  LIVE · {date_str}  ·  {time_str}\n"
        "  └───────────────────────────────┘\n\n"
        "📋 ──────  N O T E  ────── 📋\n"
        "⚠️  Heavy user traffic on this server causes\n"
        "    the password to get changed over time.\n"
        "⏳  Can’t connect? A fresh server is posted here\n"
        "    every ~6 hours — stay tuned.\n"
        f"🔔  Follow this {channel_link} · Be first in line.\n"
        "──────────────────────────────\n\n"
        "🚀 Connect: mstsc → paste IP → login\n"
        "✅ Works on PC · Mac · Android · \n\n"
        "📌 Save this post · Share with friends!\n\n"
        "═══════════════════════════════════\n"
        f"<b>⚡ Instant purchase 24/7 from Telegram admin {admin_link}</b>"
    )
    return text, RDP_BANNER_IMAGE


def build_rdp_test_caption(channel_username: str | None = None) -> str:
    """Build a clearly labelled sample post with reserved fake server details."""
    text, _ = build_rdp_post(
        ip="203.0.113.42",
        port=3389,
        username=FIXED_USERNAME,
        password="TEST-ONLY-NOT-A-REAL-LOGIN",
        country_name="TEST DATA",
        country_flag="🧪",
        seed=0,
        channel_username=channel_username,
    )
    return "🧪 TEST ONLY — NOT A REAL SERVER\n\n" + text
