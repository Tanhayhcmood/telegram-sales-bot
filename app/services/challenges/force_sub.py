"""
Force-subscription gate for the public challenge bot.

Configuration (Render environment variables)
--------------------------------------------
FORCE_SUBSCRIPTION_ENABLED=true          # set to "false" to bypass completely
REQUIRED_CHANNELS=@channel1,@channel2   # comma-separated list of channel usernames
                                         # or numeric IDs (e.g. -1001234567890)

How it works
------------
1. On every protected handler call:
       allowed, statuses = await check_membership(bot, user_id)
2. If allowed is True  → proceed normally.
3. If allowed is False → call send_gate(message, statuses) to show the join screen.
4. When the user clicks "✅ Verify Membership":
       invalidate_cache(user_id)
       allowed, statuses = await check_membership(bot, user_id)

Channel targeting
-----------------
Each entry in REQUIRED_CHANNELS can be:
  • @username        — public channel, no special bot privileges needed
  • -1001234567890   — private channel; bot MUST be admin of that channel

getChatMember notes
-------------------
- Public channel with @username: works without bot being admin.
- Private channel with numeric ID: bot must be admin of that channel.
- Any Telegram API error is logged and treated as "unverified"
  (gate stays closed) to prevent bypasses on network failures.

Caching
-------
Results are cached per user for CACHE_TTL seconds (default 60 s).
Call invalidate_cache(user_id) before a re-check so the bot contacts
Telegram fresh instead of serving the old cached answer.

Adding more channels later
--------------------------
Just update REQUIRED_CHANNELS in Render and redeploy (or restart).
No code changes needed.
"""

from __future__ import annotations

import time
from typing import TypedDict

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── constants ──────────────────────────────────────────────────────────────

CACHE_TTL: float = 60.0  # seconds between re-checks per user

# Telegram member statuses that count as "joined"
_MEMBER_STATUSES = {"member", "administrator", "creator"}

# ── types ──────────────────────────────────────────────────────────────────


class ChannelStatus(TypedDict):
    """Result for a single channel membership check."""

    name: str          # display name shown in the gate message
    link: str | None   # join URL (https://t.me/username or invite link)
    status: str        # "joined" | "not_joined" | "unverified"


# ── per-user result cache ─────────────────────────────────────────────────
# Structure: { user_id: (monotonic_timestamp, allowed, statuses) }
_cache: dict[int, tuple[float, bool, list[ChannelStatus]]] = {}


def invalidate_cache(user_id: int) -> None:
    """Remove the cached result for *user_id*.

    Call this before re-checking so the bot queries Telegram fresh instead
    of returning the stale cached answer.
    """
    _cache.pop(user_id, None)


# ── channel list parsing ──────────────────────────────────────────────────


def _parse_required_channels() -> list[str]:
    """Return the list of channel chat_ids/usernames from the env var.

    Each entry is either an @username (str) or a numeric string that will be
    converted to int by the caller.  Empty strings and pure whitespace are
    skipped automatically.
    """
    raw = (settings.REQUIRED_CHANNELS or "").strip()
    if not raw:
        return []
    entries: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            entries.append(part)
    return entries


def _channel_display_name(chat_id_str: str) -> str:
    """Human-friendly label for a channel identifier."""
    if chat_id_str.startswith("@"):
        return chat_id_str
    # Numeric ID — we don't know the title without an API call; use the ID
    return f"Channel {chat_id_str}"


def _channel_join_url(chat_id_str: str) -> str | None:
    """Return a join URL for public channels; None for private numeric IDs."""
    if chat_id_str.startswith("@"):
        return "https://t.me/" + chat_id_str.lstrip("@")
    return None  # private channel — admin must supply an invite link separately


# ── single-channel check ──────────────────────────────────────────────────


async def _check_one_channel(
    bot: Bot,
    user_id: int,
    chat_id_str: str,
) -> ChannelStatus:
    """Check whether *user_id* is a member of the channel.

    Tries the entry as-is first, then falls back to a numeric conversion when
    the string looks like a number.

    Returns a :class:`ChannelStatus` with status:
      "joined"      — user is a member / admin / creator
      "not_joined"  — user has left or was never a member
      "unverified"  — all API calls failed (network error, bot not admin, etc.)
    """
    name = _channel_display_name(chat_id_str)
    link = _channel_join_url(chat_id_str)

    # Build candidate chat_id values to try (string first, then int if numeric)
    candidates: list[str | int] = [chat_id_str]
    numeric_str = chat_id_str.lstrip("-")
    if numeric_str.isdigit():
        candidates.append(int(chat_id_str))

    for chat_id in candidates:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in _MEMBER_STATUSES:
                return ChannelStatus(name=name, link=link, status="joined")
            return ChannelStatus(name=name, link=link, status="not_joined")
        except Exception as exc:
            err = str(exc)
            # "user not found" / "chat not found" → not_joined, not unverified
            if "user not found" in err.lower() or "chat not found" in err.lower():
                return ChannelStatus(name=name, link=link, status="not_joined")
            logger.warning(
                "force_sub_check_failed",
                chat_id=chat_id,
                user_id=user_id,
                error=err[:200],
            )
            # continue to next candidate

    # All attempts failed
    logger.error(
        "force_sub_check_unverified",
        chat_id_str=chat_id_str,
        user_id=user_id,
    )
    return ChannelStatus(name=name, link=link, status="unverified")


# ── main public API ───────────────────────────────────────────────────────


async def check_membership(
    bot: Bot,
    user_id: int,
) -> tuple[bool, list[ChannelStatus]]:
    """Check whether *user_id* is a member of all required channels.

    Returns ``(allowed, statuses)`` where:
      allowed  — True if the user may proceed (feature disabled, no channels
                 configured, or all checks passed)
      statuses — list of per-channel results (empty when allowed via bypass)

    Results are cached for CACHE_TTL seconds.  Call invalidate_cache() first
    to force a fresh check (e.g. after the user taps "Verify").
    """
    # ── fast-path: feature disabled ───────────────────────────────────────
    if not settings.FORCE_SUBSCRIPTION_ENABLED:
        return True, []

    channels = _parse_required_channels()

    # ── fast-path: no channels configured → open access ───────────────────
    if not channels:
        logger.warning(
            "force_sub_enabled_but_no_channels",
            hint="Set REQUIRED_CHANNELS in Render env to a comma-separated list "
                 "of @usernames or numeric channel IDs.",
        )
        return True, []

    # ── cache hit ─────────────────────────────────────────────────────────
    cached = _cache.get(user_id)
    if cached is not None:
        ts, allowed, statuses = cached
        if time.monotonic() - ts < CACHE_TTL:
            return allowed, statuses

    # ── check each channel ────────────────────────────────────────────────
    import asyncio
    tasks = [_check_one_channel(bot, user_id, ch) for ch in channels]
    statuses: list[ChannelStatus] = await asyncio.gather(*tasks)

    # User is allowed only when every channel returns "joined"
    allowed = all(s["status"] == "joined" for s in statuses)

    logger.info(
        "force_sub_check",
        user_id=user_id,
        channels=len(statuses),
        allowed=allowed,
        not_joined=sum(1 for s in statuses if s["status"] == "not_joined"),
        unverified=sum(1 for s in statuses if s["status"] == "unverified"),
    )

    _cache[user_id] = (time.monotonic(), allowed, list(statuses))
    return allowed, list(statuses)


# ── gate message builder ──────────────────────────────────────────────────


def build_gate_message(
    statuses: list[ChannelStatus],
) -> tuple[str, InlineKeyboardMarkup]:
    """Build the gate message text and keyboard from *statuses*.

    Returns ``(text, keyboard)`` ready to pass directly to ``message.answer()``.
    """
    lines = [
        "<b>⛔ Membership Required</b>",
        "",
        "To use this bot you must join <b>all</b> of the channels below:",
        "",
    ]
    buttons: list[list[InlineKeyboardButton]] = []

    for s in statuses:
        icon = "✅" if s["status"] == "joined" else "❌"
        label = f"{icon}  {s['name']}"
        if s["link"]:
            # Clickable button that opens the channel
            buttons.append([InlineKeyboardButton(text=label, url=s["link"])])
        else:
            # Private channel with no join URL — show as text line
            lines.append(f"{icon} {s['name']}")

    lines += [
        "",
        "Once you have joined all channels, click the button below:",
    ]
    buttons.append(
        [InlineKeyboardButton(text="✅ Verify Membership", callback_data="fsub_verify")]
    )

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


async def send_gate(
    message: Message,
    statuses: list[ChannelStatus],
) -> None:
    """Send the force-subscription gate message to the user."""
    text, kb = build_gate_message(statuses)
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)
