"""RDP post text builder.

The image value is a marker consumed by the publishing layer.  The actual VPS
desktop screenshot is rendered immediately before each Telegram send.
"""
import random as _random
from datetime import datetime
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
FIXED_USERNAME = "Administrator"

# The publisher resolves this marker to a fresh Playwright screenshot.
RDP_BANNER_IMAGE = "GENERATE_VPS_DESKTOP"


_DROP_LINES = [
    "\U0001f4a5 Free Windows Server just dropped \u2014 grab it now",
    "\U0001f525 Premium server unlocked \u2014 100% free, no tricks",
    "\U0001f381 Free RDP just dropped \u2014 yours for the taking",
    "\u26a1 Live free server alert \u2014 limited time, act fast",
    "\U0001f4e2 Exclusive drop \u2014 free Windows Server online now",
    "\U0001f30d Free server found \u2014 sharing with the community",
    "\U0001f48e Premium RDP access \u2014 dropped for free today",
    "\U0001f680 Hot drop \u2014 free Windows Server just went live",
    "\U0001f4bb Free server unlocked \u2014 connect before it\u2019s gone",
    "\u2b50 Server giveaway \u2014 full admin access, totally free",
    "\U0001f4e1 Live server drop \u2014 free access for everyone",
    "\U0001f3c6 Big drop \u2014 free RDP server online right now",
]

_CHANNEL_TAG_FORMATS = [
    "\U0001f517  @{u}  \u00b7  Tap to Follow",
    "\U0001f4e2  @{u}  \u2014  Join Our Channel",
    "\U0001f4e1  @{u}  |  Official Channel",
    "\U0001f514  @{u}  \u00b7  Subscribe Now",
    "\U0001f4ac  @{u}  \u2014  Our Channel",
    "\U0001f310  @{u}  |  Follow Us",
    "\u2b50  @{u}  \u00b7  Stay Updated",
    "\U0001f4a1  @{u}  \u2014  Main Channel",
    "\U0001f4e3  @{u}  |  Official Feed",
    "\U0001f6e1  @{u}  \u00b7  Verified Channel",
    "\U0001f48e  @{u}  \u2014  Premium Channel",
    "\U0001f3c6  @{u}  |  Top Channel",
]

_ADMIN_SIGNATURES = [
    "\U0001f451  Official Admin  |  @VPS24H",
    "\U0001f451  Channel Admin  \u203a  @VPS24H",
    "\u26dc\ufe0f  Verified Admin  \u00b7  @VPS24H",
    "\U0001f531  Director & Admin  \u203a  @VPS24H",
    "\U0001f4a0  Channel Manager  |  @VPS24H",
    "\U0001f6e1\ufe0f  Head of Operations  \u203a  @VPS24H",
    "\U0001f3c6  Authorized Admin  \u00b7  @VPS24H",
    "\U0001f4e1  Admin & Publisher  |  @VPS24H",
    "\U0001f510  Certified Admin  \u203a  @VPS24H",
    "\u2699\ufe0f  System Admin  |  @VPS24H",
    "\U0001f30d  Network Admin  \u00b7  @VPS24H",
    "\U0001f680  Channel Lead  \u203a  @VPS24H",
    "\U0001f4ce  Senior Admin  |  @VPS24H",
    "\U0001f3af  Operations Lead  \u00b7  @VPS24H",
    "\U0001f52e  Channel Director  \u203a  @VPS24H",
    "\u26a1  Chief Admin  |  @VPS24H",
    "\U0001f31f  Verified Publisher  \u00b7  @VPS24H",
    "\U0001f3c5  Admin Authority  \u203a  @VPS24H",
    "\U0001f6f0\ufe0f  Broadcast Admin  |  @VPS24H",
    "\U0001f4bc  Executive Admin  \u00b7  @VPS24H",
]


def _drop_line(seed: int) -> str:
    return _DROP_LINES[seed % len(_DROP_LINES)]


def _channel_tag(username: str | None, seed: int) -> str:
    """Return a rotating channel tag line for the given username."""
    if not username:
        return ""
    u = username.lstrip("@")
    fmt = _CHANNEL_TAG_FORMATS[seed % len(_CHANNEL_TAG_FORMATS)]
    return fmt.format(u=u)


def _admin_sig(seed: int) -> str:
    return _ADMIN_SIGNATURES[(seed + 7) % len(_ADMIN_SIGNATURES)]


def _channel_link(username: str | None) -> str:
    """Return markdown [channel](t.me/username) link if username is set."""
    if not username:
        return "this channel"
    u = username.lstrip("@")
    return f"[channel](t.me/{u})"


def _now_parts() -> tuple[str, str]:
    now = datetime.now(TEHRAN)
    return now.strftime("%d %b %Y"), now.strftime("%H:%M")


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
    """
    Build the Free RDP/VPS drop post.
    Username is always Administrator regardless of what is passed.
    Image is always RDP/VPS/Server/VDS themed.
    Returns (post_text, image_urls_string).
    """
    date_str, time_str = _now_parts()
    channel_link = _channel_link(channel_username)
    tag_line = _channel_tag(channel_username, seed)
    admin_line = _admin_sig(seed)

    text = (
        "\U0001f525 FREE RDP \u2022 FREE VPS \u2022 WINDOWS RDP \u2022 CLOUD VPS \U0001f525\n"
        "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u2550\u2550\u2550\u2550\u2550\u2550\n\n"
        f"{_drop_line(seed)}\n"
        "\U0001f513 Full admin rights \u00b7 Windows Server\n"
        f"\U0001f4cd {country_flag} {country_name} \u00b7 Port {port}\n\n"
        "  \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2510\n"
        f"  \u2502  \U0001f310  {ip}:{port}\n"
        f"  \u2502  \U0001f464  {FIXED_USERNAME}\n"
        f"  \u2502  \U0001f511  {password}\n"
        f"  \u2502  \U0001f7e2  LIVE \u00b7 {date_str}  \u00b7  {time_str}\n"
        "  \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2518\n\n"
        "\U0001f4cb \u2500\u2500\u2500\u2500\u2500\u2500  N O T E  \u2500\u2500\u2500\u2500\u2500\u2500 \U0001f4cb\n"
        "\u26a0\ufe0f  Heavy user traffic on this server causes\n"
        "    the password to get changed over time.\n"
        "\u23f3  Can\u2019t connect? A fresh server is posted here\n"
        "    every ~6 hours \u2014 stay tuned.\n"
        f"\U0001f514  Follow this {channel_link} \u00b7 Be first in line.\n"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n"
        "\U0001f680 Connect: mstsc \u2192 paste IP \u2192 login\n"
        "\u2705 Works on PC \u00b7 Mac \u00b7 Android \u00b7 iPhone\n\n"
        "\U0001f4cc Save this post \u00b7 Share with friends!\n\n"
        "#ServerDrop #FreeRDP #WindowsFree #RemoteServer #CloudFree\n\n"
        f"{tag_line}\n\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\n"
        f"{admin_line}"
    )

    return text, RDP_BANNER_IMAGE
