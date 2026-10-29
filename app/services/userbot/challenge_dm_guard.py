import re

from sqlalchemy import select

from app.cache.redis_client import cache_get, cache_set, get_redis
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal

logger = get_logger(__name__)

SILENCE_TTL_SECONDS = 24 * 60 * 60
NOTIFICATION_TTL_SECONDS = 90 * 24 * 60 * 60
AI_CHALLENGE_SKIP_OVERRIDE_KEY = "ai_challenge_skip:override"
AI_CHALLENGE_SILENCE_KEY_PREFIX = "ai_challenge_silenced"

_CHALLENGE_KEYWORDS = (
    "challenge", "contest", "giveaway", "competition", "winner", "win",
    "prize", "entry", "entries", "submit", "proof", "screenshot", "round",
    "leaderboard", "invite link", "referral", "@VPS24HBot", "چالش", "مسابقه",
    "برنده", "جایزه", "اثبات", "اسکرین‌شات", "اسکرین شات", "لینک دعوت", "رفرال",
)
_SOURCE_CHALLENGE_MARKERS = (
    "challenge", "contest", "giveaway", "competition", "prize", "winner",
    "leaderboard", "proof", "screenshot", "referral", "@vps24hbot",
    "growth challenge", "rdp security challenge", "challenge brief", "entries close",
    "send your proof privately", "چالش", "مسابقه", "برنده", "جایزه", "اثبات",
    "اسکرین‌شات", "اسکرین شات", "لینک دعوت", "رفرال",
)


def _normalized_text(text: str) -> str:
    return (text or "").casefold().replace("\u200c", "")


def _contains_challenge_keyword(text: str) -> bool:
    normalized = _normalized_text(text)
    if any(_normalized_text(keyword) in normalized for keyword in _CHALLENGE_KEYWORDS):
        return True
    return bool(re.search(
        r"(?:https?://)?(?:www\.)?t\.me/vps24hbot\?start=[^\s]+",
        text or "",
        flags=re.IGNORECASE,
    ))


def _is_challenge_source_text(text: str) -> bool:
    normalized = _normalized_text(text)
    if any(_normalized_text(marker) in normalized for marker in _SOURCE_CHALLENGE_MARKERS):
        return True
    return bool(re.search(
        r"(?:https?://)?(?:www\.)?t\.me/vps24hbot\?start=[^\s]+",
        text or "",
        flags=re.IGNORECASE,
    ))


def _is_challenge_bot(source) -> bool:
    if not source:
        return False
    if isinstance(source, str):
        names = [source]
    else:
        names = [
            getattr(source, "username", None),
            getattr(source, "from_name", None),
            getattr(source, "first_name", None),
            getattr(source, "last_name", None),
            getattr(source, "title", None),
        ]
    return any("vps24hbot" in _normalized_text(str(name)) for name in names if name)


def _message_text(message) -> str:
    return (
        getattr(message, "message", None)
        or getattr(message, "text", None)
        or getattr(message, "raw_text", None)
        or ""
    )


async def _is_challenge_related(event) -> bool:
    message = event.message
    if _contains_challenge_keyword(_message_text(message)):
        return True

    reply_header = getattr(message, "reply_to", None)
    quote_text = getattr(reply_header, "quote_text", None)
    if _is_challenge_source_text(quote_text or ""):
        return True

    reply_id = (
        getattr(message, "reply_to_msg_id", None)
        or getattr(reply_header, "reply_to_msg_id", None)
    )
    if reply_id:
        reply_message = None
        get_reply = getattr(event, "get_reply_message", None)
        if not callable(get_reply):
            get_reply = getattr(message, "get_reply_message", None)
        if callable(get_reply):
            try:
                reply_message = await get_reply()
            except Exception as error:
                logger.debug("challenge_reply_context_fetch_failed", error=str(error)[:120])
        if reply_message:
            if _is_challenge_source_text(_message_text(reply_message)):
                return True
            try:
                if _is_challenge_bot(await reply_message.get_sender()):
                    return True
            except Exception:
                pass

    forward = getattr(message, "fwd_from", None)
    if forward:
        if _is_challenge_bot(forward) or _is_challenge_source_text(getattr(forward, "from_name", "") or ""):
            return True
        source_id = getattr(forward, "from_id", None)
        if source_id:
            try:
                if _is_challenge_bot(await event.client.get_entity(source_id)):
                    return True
            except Exception:
                pass
        if _is_challenge_source_text(_message_text(message)):
            return True
    return False


async def _active_round_id() -> str:
    try:
        from app.models.growth import GrowthRound

        async with AsyncSessionLocal() as session:
            round_id = await session.scalar(
                select(GrowthRound.id)
                .where(GrowthRound.is_active.is_(True))
                .order_by(GrowthRound.started_at.desc())
                .limit(1)
            )
            if round_id:
                return str(round_id)

            from app.models.challenge import Challenge

            challenge_id = await session.scalar(
                select(Challenge.id)
                .where(Challenge.status == "active")
                .order_by(Challenge.created_at.desc())
                .limit(1)
            )
            return str(challenge_id) if challenge_id else "untracked"
    except Exception as error:
        logger.warning("challenge_dm_round_lookup_failed", error=str(error)[:160])
        return "untracked"


async def _notify_admins_once(sender, user_id: int, text: str, round_id: str) -> None:
    admin_ids = settings.admin_ids
    if not admin_ids:
        logger.warning("challenge_dm_admin_notification_skipped_no_admins", user_id=user_id)
        return

    redis = await get_redis()
    notified_key = f"ai_challenge_dm_notified:{round_id}:{user_id}"
    lock_key = f"{notified_key}:lock"
    if await redis.exists(notified_key):
        return
    if not await redis.set(lock_key, "1", ex=60, nx=True):
        return

    delivered = False
    try:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        from app.services.admin_bot.bot import get_bot

        bot = get_bot()
        if bot is None:
            logger.warning("challenge_dm_admin_notification_skipped_no_bot", user_id=user_id)
            return

        display_name = " ".join(
            part for part in (
                getattr(sender, "first_name", None),
                getattr(sender, "last_name", None),
            ) if part
        ).replace("\n", " ").replace("\r", " ").strip() or "Unknown"
        username = getattr(sender, "username", None)
        username_label = f"@{username}" if username else "No username"
        message_text = (text or "[media attachment]").strip()
        if len(message_text) > 1400:
            message_text = message_text[:1399].rstrip() + "…"
        admin_text = (
            "Growth challenge DM silenced\n"
            f"User: {display_name} / {username_label} / ID {user_id}\n"
            f"Round: {round_id}\n"
            f"Message: {message_text}"
        )
        chat_url = f"https://t.me/{username}" if username else f"tg://user?id={user_id}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Open chat", url=chat_url),
        ]])
        for admin_id in admin_ids:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=admin_text,
                    reply_markup=keyboard,
                    parse_mode=None,
                )
                delivered = True
            except Exception as error:
                logger.warning(
                    "challenge_dm_admin_notification_failed",
                    admin_id=admin_id,
                    user_id=user_id,
                    error=str(error)[:160],
                )
        if delivered:
            await redis.set(notified_key, "1", ex=NOTIFICATION_TTL_SECONDS)
    except Exception as error:
        logger.error("challenge_dm_admin_notification_error", user_id=user_id, error=str(error)[:160])
    finally:
        try:
            await redis.delete(lock_key)
        except Exception:
            pass


async def should_silence_challenge_dm(event, sender, user_id: int, text: str) -> bool:
    """Return True before any automated userbot reply when challenge context is active."""
    try:
        override = await cache_get(AI_CHALLENGE_SKIP_OVERRIDE_KEY)
        if override is None:
            enabled = settings.AI_SKIP_CHALLENGE_DMS
        elif isinstance(override, str):
            enabled = override.strip().casefold() in {"1", "true", "on", "yes"}
        else:
            enabled = bool(override)
        if not enabled:
            return False

        silence_key = f"{AI_CHALLENGE_SILENCE_KEY_PREFIX}:{user_id}"
        if await _is_challenge_related(event):
            round_id = await _active_round_id()
            metadata = {
                "user_id": user_id,
                "username": getattr(sender, "username", None),
                "display_name": " ".join(
                    part for part in (
                        getattr(sender, "first_name", None),
                        getattr(sender, "last_name", None),
                    ) if part
                ).strip(),
                "round_id": round_id,
            }
            await cache_set(silence_key, metadata, ttl=SILENCE_TTL_SECONDS)
            await _notify_admins_once(sender, user_id, text, round_id)
            logger.info("challenge_dm_silenced", user_id=user_id, round_id=round_id)
            return True

        if await cache_get(silence_key):
            logger.info("challenge_dm_context_silenced", user_id=user_id)
            return True
        return False
    except Exception as error:
        logger.error("challenge_dm_guard_failed_closed", user_id=user_id, error=str(error)[:160])
        return True
