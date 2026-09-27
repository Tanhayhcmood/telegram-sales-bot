"""
RDP Plans Post Builder — beautiful tree-branch hierarchical layout for Telegram channels.

Each plan is rendered as a branching tree card with full labels + price.
Post is text-only (no image) so there is no caption length constraint.
Returns (post_text, image_url).
"""
import random as _random

# ── Plan catalogue — edit prices/specs here ───────────────────────────────────
RDP_PLANS = [
    {
        "icon":  "🌿",
        "badge": "🥈",
        "tier":  "Entry Level",
        "name":  "PRO",
        "cpu":   "4 vCPU",
        "ram":   "8 GB RAM",
        "disk":  "120 GB SSD",
        "net":   "1 Gbps",
        "price": "$16",
    },
    {
        "icon":  "⚡",
        "badge": "🥇",
        "tier":  "Standard",
        "name":  "POWER",
        "cpu":   "6 vCPU",
        "ram":   "16 GB RAM",
        "disk":  "250 GB SSD",
        "net":   "2 Gbps",
        "price": "$28",
    },
    {
        "icon":  "💠",
        "badge": "💎",
        "tier":  "Advanced",
        "name":  "ELITE",
        "cpu":   "8 vCPU",
        "ram":   "32 GB RAM",
        "disk":  "500 GB SSD",
        "net":   "2 Gbps",
        "price": "$45",
    },
    {
        "icon":  "🔱",
        "badge": "🏆",
        "tier":  "Ultimate",
        "name":  "ULTRA",
        "cpu":   "12 vCPU",
        "ram":   "64 GB RAM",
        "disk":  "1 TB SSD",
        "net":   "5 Gbps",
        "price": "$75",
    },
]

_BANNER_IMAGE = ""  # no image — text-only post

_CHANNEL_TAG_FORMATS = [
    "📢 @{u} — Join Our Channel",
    "📡 @{u} | Official Channel",
    "🔔 @{u} · Subscribe Now",
    "🌐 @{u} | Follow Us",
    "⭐ @{u} · Stay Updated",
]

_ADMIN_SIGNATURES = [
    "💎 Senior Admin | @VPS24H",
    "👑 Official Admin › @VPS24H",
    "🛡️ Head of Operations › @VPS24H",
    "⚜️ Verified Admin · @VPS24H",
    "🔱 Director & Admin › @VPS24H",
    "⚡ Chief Admin | @VPS24H",
    "🌟 Verified Publisher · @VPS24H",
    "🏆 Authorized Admin · @VPS24H",
    "🔐 Certified Admin › @VPS24H",
    "📡 Admin & Publisher | @VPS24H",
]

_SEP = "━" * 30


def _spaced(name: str) -> str:
    return "  ".join(name)


def _plan_card(p: dict) -> str:
    """Render a single plan as a tree-branch card with full labels."""
    return "\n".join([
        f"{p['icon']} ┌── {_spaced(p['name'])} ──────── {p['badge']}",
        f"   ├── 🖥️  Processor → {p['cpu']}",
        f"   ├── 🧠  Memory    → {p['ram']}",
        f"   ├── 💾  Storage   → {p['disk']}",
        f"   ├── 🌐  Network   → {p['net']}",
        f"   ├── 🏷️  Tier      → {p['tier']}",
        f"   └── 💰  Price     → {p['price']} / month",
    ])


def build_rdp_plans_post(
    channel_username: str | None = None,
    seed: int | None = None,
) -> tuple[str, str]:
    if seed is None:
        seed = _random.randint(0, 9_999_999)

    admin_sig = _ADMIN_SIGNATURES[seed % len(_ADMIN_SIGNATURES)]
    cards_txt = "\n\n".join(_plan_card(p) for p in RDP_PLANS)

    tag_line = ""
    if channel_username:
        u   = channel_username.lstrip("@")
        fmt = _CHANNEL_TAG_FORMATS[seed % len(_CHANNEL_TAG_FORMATS)]
        tag_line = fmt.format(u=u) + "\n"

    text = (
        f"{cards_txt}\n\n"
        f"{_SEP}\n\n"
        f"✅ Full RDP Access · Root Admin\n"
        f"✅ Instant Delivery · 24/7 Support\n"
        f"✅ Monthly Billing · Easy Renewal\n"
        f"{tag_line}"
        f"\n{_SEP}\n"
        f"{admin_sig}"
    )

    return text, _BANNER_IMAGE
