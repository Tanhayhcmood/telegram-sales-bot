"""
Flash Sale Post Builder - time-limited discount post for RDP plans.
Returns (post_text, image_url).
"""
import random as _random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")

_PLANS = [
    {"icon": "🌿", "badge": "🥈", "name": "PRO",   "tier": "Entry Level", "cpu": "4 vCPU",  "ram": "8 GB RAM",  "storage": "120 GB SSD", "net": "1 Gbps", "price": 16, "sale_price": 11},
    {"icon": "⚡",  "badge": "🥇", "name": "POWER", "tier": "Standard",    "cpu": "6 vCPU",  "ram": "16 GB RAM", "storage": "250 GB SSD", "net": "2 Gbps", "price": 28, "sale_price": 20},
    {"icon": "💠", "badge": "💎", "name": "ELITE", "tier": "Advanced",    "cpu": "8 vCPU",  "ram": "32 GB RAM", "storage": "500 GB SSD", "net": "2 Gbps", "price": 45, "sale_price": 31},
    {"icon": "🔱", "badge": "🏆", "name": "ULTRA", "tier": "Ultimate",    "cpu": "12 vCPU", "ram": "64 GB RAM", "storage": "1 TB SSD",   "net": "5 Gbps", "price": 75},
]

_DISCOUNTS = [20, 25, 30]

_ADMIN_SIGNATURES = [
    "💎 Senior Admin | @VPS24H",
    "👑 Official Admin › @VPS24H",
    "⚡ Chief Admin | @VPS24H",
    "🔱 Director & Admin › @VPS24H",
    "⚜️ Verified Admin · @VPS24H",
]

_SEP = "━" * 28
_TELEGRAM_CAPTION_LIMIT = 1020


def _sale_card(p: dict, discount: int) -> str:
    orig = p["price"]
    sale = p.get("sale_price", round(orig * (1 - discount / 100)))
    lines = [
        p["icon"] + " ┌── " + p["name"] + " " + p["badge"],
        "   ├── Processor → " + p["cpu"],
        "   ├── Memory    → " + p["ram"],
        "   ├── Storage   → " + p["storage"],
        "   ├── Network   → " + p["net"],
        "   ├── Tier      → " + p["tier"],
        "   ├── Was       → $" + str(orig) + " / month",
        "   └── NOW       → $" + str(sale) + " / month  🔥 -" + str(discount) + "%",
    ]
    return "\n".join(lines)


def build_flash_sale_post(
    channel_username: str | None = None,
    seed: int | None = None,
    duration_hours: int = 2,
) -> tuple[str, str]:
    """Build a timed flash-sale post. Returns (text, image_url)."""
    if seed is None:
        seed = _random.randint(0, 9_999_999)

    discount = _DISCOUNTS[seed % len(_DISCOUNTS)]
    admin_sig = _ADMIN_SIGNATURES[seed % len(_ADMIN_SIGNATURES)]

    now_ny = datetime.now(NEW_YORK)
    expires_at = now_ny + timedelta(hours=duration_hours)
    expires_str = expires_at.strftime("%H:%M")

    cards_txt = "\n\n".join(_sale_card(p, discount) for p in _PLANS)

    tag_line = ""
    if channel_username:
        u = channel_username.lstrip("@")
        tag_line = "\n📢 @" + u + " — Join for more deals"

    text = (
        "⚡ FLASH SALE ⚡\n"
        + _SEP + "\n\n"
        + "🔥 LIMITED TIME — " + str(duration_hours) + " HOURS ONLY\n"
        + "⏰ Expires: " + expires_str + " (New York Time)\n\n"
        + cards_txt + "\n\n"
        + _SEP + "\n\n"
        + "✅ Full RDP Access · Root Admin\n"
        + "✅ Instant Delivery · 24/7 Support\n"
        + "✅ Monthly Billing · Easy Renewal\n"
        + "📲 DM @VPS24H to claim your discount"
        + tag_line + "\n"
        + _SEP + "\n"
        + admin_sig
    )

    # Telegram captions are limited to 1024 characters. Keep a small safety
    # margin for Markdown/entities added by the publisher so Flash Sale always
    # remains a photo + caption message instead of falling back to text.
    if len(text) > _TELEGRAM_CAPTION_LIMIT:
        text = text[:_TELEGRAM_CAPTION_LIMIT - 1].rstrip() + "…"

    return text, "FILE:app/assets/upgrade_team_logo.jpg"
