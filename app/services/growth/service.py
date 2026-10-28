import asyncio
import hashlib
import html
import json
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Awaitable, Callable

from aiogram.enums import ParseMode
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.channel import TelegramChannel
from app.models.growth import GrowthEntry, GrowthPrize, GrowthRound, GrowthWinner

logger = get_logger(__name__)

ROUND_HOURS = 9
ENTRY_HOURS = 8
REVIEW_HOURS = 1
MAX_PROOFS_PER_USER = 3
WIN_COOLDOWN = timedelta(days=7)
SIMILARITY_RETRIES = 5
ACTIVE_STATUSES = {"draft", "open", "review", "finalizing"}
CHALLENGE_TYPES = ("share_post", "invite_friends", "story_status")
CHALLENGE_TYPE_PROMPTS = {
    "share_post": "Share one recent post from the channel to a relevant group or chat.",
    "invite_friends": "Invite friends to the channel and show a genuine invitation or join.",
    "story_status": "Publish an honest story or status recommending the channel.",
}
_TEXT_STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "because", "before", "from",
    "have", "into", "just", "more", "only", "that", "their", "them", "then",
    "there", "these", "they", "this", "those", "through", "with", "your",
}
_scheduler_lock = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalized_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").lower()))


def _challenge_hash(value: str) -> str:
    return hashlib.sha256(_normalized_text(value).encode("utf-8")).hexdigest()


def _too_similar(candidate: str, history: list[str]) -> bool:
    candidate_norm = _normalized_text(candidate)
    candidate_words = {
        word for word in candidate_norm.split()
        if len(word) > 3 and word not in _TEXT_STOP_WORDS
    }
    for previous in history:
        previous_norm = _normalized_text(previous)
        if not previous_norm:
            continue
        if candidate_norm == previous_norm:
            return True
        if min(len(candidate_norm), len(previous_norm)) >= 100:
            if SequenceMatcher(None, candidate_norm, previous_norm).ratio() >= 0.78:
                return True
        previous_words = {
            word for word in previous_norm.split()
            if len(word) > 3 and word not in _TEXT_STOP_WORDS
        }
        if candidate_words and previous_words:
            overlap = len(candidate_words & previous_words) / min(
                len(candidate_words), len(previous_words)
            )
            if overlap >= 0.82:
                return True
    return False


def next_challenge_type(previous: str | None) -> str:
    """Return the next item in the fixed rotation, never the previous type."""
    if previous not in CHALLENGE_TYPES:
        return CHALLENGE_TYPES[0]
    return CHALLENGE_TYPES[(CHALLENGE_TYPES.index(previous) + 1) % len(CHALLENGE_TYPES)]


async def generate_unique_challenge(
    challenge_type: str,
    history: list[str],
    bot_username: str | None = None,
    prize_kinds: list[str] | None = None,
) -> tuple[str, str]:
    from app.services.ai.engine import generate_content

    variation_prompts = (
        "Use a compact, conversational dare.",
        "Open with a specific observation, then make the action clear.",
        "Use a practical, matter-of-fact voice.",
        "Frame it as a question someone might actually ask a friend.",
        "Write a short story-led invitation, without sounding promotional.",
        "Keep it direct and warm, with a different rhythm from a standard announcement.",
    )
    recent = history[-25:]
    recent_text = "\n".join(f"- {text[:700]}" for text in recent)
    proof_destination = f"@{bot_username}" if bot_username else "this bot"
    prize_kinds = sorted(set(prize_kinds or []))
    if len(prize_kinds) == 1:
        prize_description = f"The prize is one {prize_kinds[0]} prize from the admin-added pool."
    else:
        prize_description = "The prize is one RDP or VPS prize from the admin-added pool."
    system = (
        "Write natural English copy for a Telegram channel promotion challenge. "
        "Sound like a person, not an AI or an ad template. Avoid emoji, hype, "
        "fake urgency, repeated slogans, and filler. Never invent a prize or claim."
    )
    for attempt in range(1, SIMILARITY_RETRIES + 1):
        variation = random.choice(variation_prompts)
        prompt = (
            f"Create one fresh Growth Challenge. The action must be: "
            f"{CHALLENGE_TYPE_PROMPTS[challenge_type]}\n"
            f"Variation direction: {variation}\n"
            f"{prize_description} Mention that prize without inventing specs, value, or extra prizes. "
            f"Tell participants to send a screenshot or forward their proof privately "
            f"to {proof_destination}. Entries close eight hours after publication. "
            "The copy must be entirely in English and clearly describe one honest action. "
            "Vary the length, tone, opening, and structure; do not use a fixed template. "
            "Do not pressure people to spam groups or mislead friends. "
            "Return only the user-facing challenge copy, with no heading or explanation.\n\n"
            "Previous Growth Challenges. Do not reuse their wording, scenario, or angle; "
            "write a meaningfully different challenge:\n"
            f"{recent_text or '- No earlier Growth Challenges.'}"
        )
        generated = await generate_content(prompt, system=system, temperature=0.88)
        text = (generated or "").strip().strip("`").strip()
        if len(text) < 70 or len(text) > 2800:
            logger.warning("growth_challenge_generation_rejected", reason="invalid_length", attempt=attempt)
            continue
        if _too_similar(text, history):
            logger.warning("growth_challenge_similarity_retry", attempt=attempt)
            continue
        return text, _challenge_hash(text)
    raise RuntimeError("AI did not produce a sufficiently distinct English challenge after five attempts")


def _public_bot():
    from app.services.challenges.public_bot import get_public_bot

    return get_public_bot()


async def _submission_bot_username() -> str | None:
    try:
        from app.services.admin_bot.bot import get_bot

        bot = get_bot()
        if bot:
            me = await bot.get_me()
            if me.username:
                return me.username.lstrip("@")
    except Exception:
        pass
    return None


async def _target_channels(session) -> list[str]:
    result = await session.execute(
        select(TelegramChannel.telegram_channel_id).where(TelegramChannel.is_active.is_(True))
    )
    channels = [str(channel_id) for channel_id in result.scalars().all()]
    channels.extend(
        channel.strip()
        for channel in (settings.REQUIRED_CHANNELS or "").split(",")
        if channel.strip()
    )
    return list(dict.fromkeys(channels))


def _remaining_text(deadline: datetime, now: datetime) -> str:
    seconds = max(0, int((deadline - now).total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def render_round_post(
    round_obj: GrowthRound,
    entries_count: int,
    now: datetime,
    bot_username: str | None,
) -> str:
    if round_obj.status == "open":
        destination = f"@{bot_username}" if bot_username else "this bot"
        status = (
            f"LIVE — {_remaining_text(round_obj.entries_close_at, now)} left\n"
            f"Entries: {entries_count}\n"
            f"Send a screenshot or forwarded proof to {destination} in a private chat. "
            "Up to 3 proofs per person this round."
        )
    elif round_obj.status == "review":
        status = (
            "Entries are closed; admins are reviewing the proof.\n"
            f"Entries: {entries_count}\n"
            f"Winner announcement: {round_obj.review_ends_at.strftime('%H:%M UTC')}."
        )
    elif round_obj.status == "cancelled":
        status = "This round was cancelled. Entries are closed."
    else:
        status = f"Round status: {round_obj.status}."
    return f"{round_obj.challenge_text.strip()}\n\n{status}"


async def publish_round_to_channels(
    bot,
    channels: list[str],
    round_obj: GrowthRound,
    entries_count: int,
    bot_username: str | None,
    on_published: Callable[[dict], Awaitable[None]] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Post, edit to live status, and pin each channel independently."""
    published: list[dict] = []
    results: list[dict] = []
    for channel_id in channels:
        try:
            sent = await bot.send_message(
                chat_id=channel_id,
                text=html.escape(round_obj.challenge_text.strip(), quote=False),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            message_id = getattr(sent, "message_id", None) or getattr(sent, "id", None)
            if message_id is None:
                raise RuntimeError("Telegram did not return a message id")
            record = {"chat_id": str(channel_id), "message_id": int(message_id)}
            published.append(record)
            if on_published:
                await on_published(record)
            results.append({"chat_id": str(channel_id), "status": "published", "message_id": int(message_id)})
        except Exception as exc:
            results.append({"chat_id": str(channel_id), "status": "failed", "error": str(exc)[:240]})
            logger.exception("growth_channel_publish_failed", chat_id=str(channel_id))
            continue

        live_text = render_round_post(round_obj, entries_count, _now(), bot_username)
        try:
            await bot.edit_message_text(
                chat_id=channel_id,
                message_id=int(message_id),
                text=html.escape(live_text, quote=False),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as exc:
            logger.warning(
                "growth_channel_live_edit_failed",
                chat_id=str(channel_id),
                message_id=int(message_id),
                error=str(exc)[:200],
            )
        try:
            await bot.pin_chat_message(
                chat_id=channel_id,
                message_id=int(message_id),
                disable_notification=True,
            )
        except Exception as exc:
            logger.warning(
                "growth_channel_pin_failed",
                chat_id=str(channel_id),
                message_id=int(message_id),
                error=str(exc)[:200],
            )
    return published, results


async def _unpin_previous_round(bot, messages: list[dict]) -> None:
    if not bot:
        return
    for post in messages or []:
        try:
            await bot.unpin_chat_message(
                chat_id=post["chat_id"],
                message_id=int(post["message_id"]),
            )
        except Exception as exc:
            logger.warning(
                "growth_previous_post_unpin_failed",
                chat_id=str(post.get("chat_id")),
                message_id=post.get("message_id"),
                error=str(exc)[:200],
            )


async def start_growth_round(bot=None, now: datetime | None = None) -> dict:
    bot = bot or _public_bot()
    requested_now = now
    now = now or _now()
    if not bot:
        return {"status": "bot_unavailable"}

    async with AsyncSessionLocal() as session:
        active = await session.scalar(
            select(GrowthRound).where(GrowthRound.is_active.is_(True)).with_for_update()
        )
        if active:
            if active.status == "draft" and active.started_at < now - timedelta(minutes=20):
                active.status = "publish_failed"
                active.is_active = False
                active.last_error = "stale draft recovered by scheduler"
                await session.commit()
            else:
                return {"status": "active", "round_id": str(active.id)}

        channels = await _target_channels(session)
        if not channels:
            logger.error("growth_round_no_configured_channels")
            return {"status": "no_channels"}
        prize_rows = (
            await session.execute(
                select(GrowthPrize.id, GrowthPrize.kind, GrowthPrize.encrypted_payload).where(
                    GrowthPrize.status == "available"
                )
            )
        ).all()
        if not prize_rows:
            logger.warning("growth_round_skipped_empty_prize_pool")
            return {"status": "no_prizes"}
        try:
            cipher = _fernet()
        except RuntimeError:
            logger.error("growth_round_prize_encryption_key_unavailable")
            return {"status": "prize_key_invalid"}
        prize_kinds_set: set[str] = set()
        for prize_id, kind, encrypted_payload in prize_rows:
            try:
                cipher.decrypt(encrypted_payload.encode("ascii"))
                prize_kinds_set.add(kind)
            except Exception:
                logger.warning("growth_prize_unreadable", prize_id=str(prize_id))
        prize_kinds = sorted(prize_kinds_set)
        if not prize_kinds:
            return {"status": "prize_key_invalid"}

        previous = await session.scalar(
            select(GrowthRound).order_by(GrowthRound.started_at.desc()).limit(1)
        )
        previous_type = previous.challenge_type if previous else None
        last_published = await session.scalar(
            select(GrowthRound)
            .where(GrowthRound.published_messages != [])
            .order_by(GrowthRound.started_at.desc())
            .limit(1)
        )
        previous_messages = list(last_published.published_messages or []) if last_published else []
        history_result = await session.execute(select(GrowthRound.challenge_text))
        history = [row[0] for row in history_result.all() if row[0]]

    challenge_type = next_challenge_type(previous_type)
    username = await _submission_bot_username()
    if not username:
        logger.error("growth_round_admin_bot_unavailable")
        return {"status": "admin_bot_unavailable"}
    try:
        challenge_text, challenge_hash = await generate_unique_challenge(
            challenge_type, history, username, prize_kinds
        )
    except Exception as exc:
        logger.error("growth_challenge_generation_failed", error=str(exc)[:240])
        return {"status": "generation_failed"}

    if requested_now is None:
        now = _now()
    ends_at = now + timedelta(hours=ENTRY_HOURS)
    review_ends_at = now + timedelta(hours=ROUND_HOURS)
    round_obj = GrowthRound(
        challenge_type=challenge_type,
        challenge_text=challenge_text,
        challenge_hash=challenge_hash,
        status="draft",
        is_active=True,
        channel_ids=channels,
        prize_types=prize_kinds,
        published_messages=[],
        started_at=now,
        entries_close_at=ends_at,
        review_ends_at=review_ends_at,
        next_round_at=review_ends_at,
        status_updated_at=now,
    )
    async with AsyncSessionLocal() as session:
        active = await session.scalar(
            select(GrowthRound).where(GrowthRound.is_active.is_(True)).with_for_update()
        )
        if active:
            return {"status": "active", "round_id": str(active.id)}
        session.add(round_obj)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.warning("growth_round_insert_conflict")
            return {"status": "active"}

        await _unpin_previous_round(bot, previous_messages)

        async def save_published_message(record: dict) -> None:
            current = list(round_obj.published_messages or [])
            current.append(record)
            round_obj.published_messages = current
            round_obj.status = "open"
            round_obj.status_updated_at = _now()
            await session.commit()

        published, results = await publish_round_to_channels(
            bot,
            channels,
            round_obj,
            entries_count=0,
            bot_username=username,
            on_published=save_published_message,
        )
        failures = [row for row in results if row["status"] != "published"]
        if published:
            round_obj.status = "open"
            round_obj.last_error = (
                "; ".join(f"{row['chat_id']}: {row['error']}" for row in failures)[:1000]
                if failures else None
            )
            round_obj.status_updated_at = _now()
            await session.commit()
        else:
            round_obj.status = "publish_failed"
            round_obj.is_active = False
            round_obj.last_error = "No configured channel accepted the post."
            round_obj.next_round_at = now + timedelta(hours=ROUND_HOURS)
            await session.commit()

    logger.info(
        "growth_round_published",
        round_id=str(round_obj.id),
        challenge_type=challenge_type,
        published=len(published),
        total=len(channels),
    )
    return {
        "status": "open" if published else "publish_failed",
        "round_id": str(round_obj.id),
        "challenge_type": challenge_type,
        "published": len(published),
        "total": len(channels),
    }


async def _edit_round_posts(round_obj: GrowthRound, entries_count: int, bot, now: datetime) -> None:
    if not bot:
        return
    text = html.escape(
        render_round_post(round_obj, entries_count, now, await _submission_bot_username()),
        quote=False,
    )
    for post in round_obj.published_messages or []:
        try:
            await bot.edit_message_text(
                chat_id=post["chat_id"],
                message_id=int(post["message_id"]),
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as exc:
            logger.warning(
                "growth_status_edit_failed",
                chat_id=str(post.get("chat_id")),
                message_id=post.get("message_id"),
                error=str(exc)[:200],
            )


async def refresh_growth_post(round_id: str | uuid.UUID | None = None) -> None:
    bot = _public_bot()
    if not bot:
        return
    now = _now()
    async with AsyncSessionLocal() as session:
        query = select(GrowthRound).where(GrowthRound.is_active.is_(True))
        if round_id:
            query = query.where(GrowthRound.id == uuid.UUID(str(round_id)))
        round_obj = await session.scalar(query.order_by(GrowthRound.started_at.desc()).limit(1))
        if not round_obj or round_obj.status not in {"open", "review", "cancelled"}:
            return
        count = await session.scalar(
            select(func.count(GrowthEntry.id)).where(
                GrowthEntry.round_id == round_obj.id,
                GrowthEntry.status.in_(("pending", "approved")),
            )
        )
        await _edit_round_posts(round_obj, int(count or 0), bot, now)
        round_obj.status_updated_at = now
        await session.commit()


async def submit_growth_proof(
    telegram_user_id: int,
    username: str | None,
    source_chat_id: int,
    source_message_id: int,
    proof_type: str,
    proof_hash: str,
    proof_file_id: str | None = None,
) -> dict:
    now = _now()
    async with AsyncSessionLocal() as session:
        round_obj = await session.scalar(
            select(GrowthRound)
            .where(GrowthRound.is_active.is_(True), GrowthRound.status == "open")
            .order_by(GrowthRound.started_at.desc())
            .with_for_update()
            .limit(1)
        )
        if not round_obj or now >= round_obj.entries_close_at:
            return {"status": "closed"}

        duplicate = await session.scalar(
            select(GrowthEntry.id).where(GrowthEntry.proof_hash == proof_hash)
        )
        if duplicate:
            return {"status": "duplicate"}

        user_count = await session.scalar(
            select(func.count(GrowthEntry.id)).where(
                GrowthEntry.round_id == round_obj.id,
                GrowthEntry.telegram_user_id == telegram_user_id,
            )
        )
        if int(user_count or 0) >= MAX_PROOFS_PER_USER:
            return {"status": "limit", "round_id": str(round_obj.id)}

        entry = GrowthEntry(
            round_id=round_obj.id,
            telegram_user_id=telegram_user_id,
            username=username,
            proof_type=proof_type,
            proof_hash=proof_hash,
            proof_file_id=proof_file_id,
            source_user_id=telegram_user_id,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            status="pending",
            admin_notifications=[],
        )
        session.add(entry)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return {"status": "duplicate"}
        remaining = MAX_PROOFS_PER_USER - int(user_count or 0) - 1
        return {
            "status": "submitted",
            "entry_id": str(entry.id),
            "round_id": str(round_obj.id),
            "remaining": remaining,
            "challenge_type": round_obj.challenge_type,
        }


async def record_admin_notification(entry_id: str, chat_id: int, message_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        entry = await session.scalar(
            select(GrowthEntry).where(GrowthEntry.id == uuid.UUID(entry_id)).with_for_update()
        )
        if not entry:
            return False
        notifications = list(entry.admin_notifications or [])
        notifications.append({"chat_id": int(chat_id), "message_id": int(message_id)})
        entry.admin_notifications = notifications
        pending = entry.status == "pending"
        await session.commit()
        return pending


async def review_growth_entry(entry_id: str, admin_id: int, approve: bool) -> dict:
    async with AsyncSessionLocal() as session:
        entry = await session.scalar(
            select(GrowthEntry).where(GrowthEntry.id == uuid.UUID(entry_id)).with_for_update()
        )
        if not entry:
            return {"status": "missing", "notifications": []}
        notifications = list(entry.admin_notifications or [])
        if entry.status != "pending":
            return {"status": "already_reviewed", "notifications": notifications}
        round_obj = await session.get(GrowthRound, entry.round_id)
        if not round_obj or round_obj.status not in {"open", "review"}:
            return {"status": "closed", "notifications": notifications}
        entry.status = "approved" if approve else "rejected"
        entry.reviewed_by = admin_id
        entry.reviewed_at = _now()
        result = {
            "status": entry.status,
            "notifications": notifications,
            "telegram_user_id": entry.telegram_user_id,
            "username": entry.username,
            "round_id": str(entry.round_id),
        }
        await session.commit()
        return result


def _fernet() -> Fernet:
    key = (settings.GROWTH_PRIZE_ENCRYPTION_KEY or "").strip()
    if not key:
        raise RuntimeError("GROWTH_PRIZE_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(key.encode("ascii"))
    except Exception as exc:
        raise RuntimeError("GROWTH_PRIZE_ENCRYPTION_KEY is not a valid Fernet key") from exc


async def add_growth_prize(kind: str, payload: str) -> dict:
    kind = (kind or "").strip().upper()
    payload = (payload or "").strip()
    if kind not in {"RDP", "VPS"}:
        return {"status": "invalid_kind"}
    if not payload:
        return {"status": "empty"}
    try:
        encrypted = _fernet().encrypt(payload.encode("utf-8")).decode("ascii")
    except RuntimeError:
        logger.error("growth_prize_encryption_not_configured")
        return {"status": "encryption_not_configured"}
    async with AsyncSessionLocal() as session:
        prize = GrowthPrize(
            kind=kind,
            encrypted_payload=encrypted,
            status="available",
        )
        session.add(prize)
        await session.commit()
        prize_id = str(prize.id)
    logger.info("growth_prize_added", prize_id=prize_id, kind=kind)
    return {"status": "added", "prize_id": prize_id, "kind": kind}


async def growth_prize_pool_count() -> int:
    async with AsyncSessionLocal() as session:
        count = await session.scalar(
            select(func.count(GrowthPrize.id)).where(GrowthPrize.status == "available")
        )
    return int(count or 0)


async def growth_status() -> dict:
    async with AsyncSessionLocal() as session:
        round_obj = await session.scalar(
            select(GrowthRound).order_by(GrowthRound.started_at.desc()).limit(1)
        )
        prizes = await session.scalar(
            select(func.count(GrowthPrize.id)).where(GrowthPrize.status == "available")
        )
        if not round_obj:
            return {"status": "none", "prizes": int(prizes or 0)}
        counts = await session.execute(
            select(GrowthEntry.status, func.count(GrowthEntry.id))
            .where(GrowthEntry.round_id == round_obj.id)
            .group_by(GrowthEntry.status)
        )
        entry_counts = {status: int(count) for status, count in counts.all()}
        winners = await session.scalar(
            select(func.count(GrowthWinner.id)).where(
                GrowthWinner.round_id == round_obj.id,
                GrowthWinner.delivery_status == "delivered",
            )
        )
        return {
            "status": round_obj.status,
            "round_id": str(round_obj.id),
            "challenge_type": round_obj.challenge_type,
            "started_at": round_obj.started_at,
            "entries_close_at": round_obj.entries_close_at,
            "next_round_at": round_obj.next_round_at,
            "submitted": sum(entry_counts.values()),
            "pending": entry_counts.get("pending", 0),
            "approved": entry_counts.get("approved", 0),
            "rejected": entry_counts.get("rejected", 0),
            "delivered_winners": int(winners or 0),
            "prizes": int(prizes or 0),
        }


async def cancel_growth_round(bot=None) -> dict:
    now = _now()
    async with AsyncSessionLocal() as session:
        round_obj = await session.scalar(
            select(GrowthRound).where(GrowthRound.is_active.is_(True)).with_for_update()
        )
        if not round_obj:
            return {"status": "none"}
        round_obj.status = "cancelled"
        round_obj.is_active = False
        round_obj.status_updated_at = now
        round_obj.last_error = "Cancelled manually by an administrator."
        count = await session.scalar(
            select(func.count(GrowthEntry.id)).where(
                GrowthEntry.round_id == round_obj.id,
                GrowthEntry.status.in_(("pending", "approved")),
            )
        )
        await session.commit()
        await _edit_round_posts(round_obj, int(count or 0), bot or _public_bot(), now)
        return {"status": "cancelled", "round_id": str(round_obj.id)}


async def _notify_delivery_failure(user_id: int, round_id: str, error: str) -> None:
    try:
        from app.services.admin_bot.bot import get_bot

        bot = get_bot()
    except Exception:
        bot = None
    if not bot:
        logger.error(
            "growth_prize_delivery_failed_admin_bot_unavailable",
            user_id=user_id,
            round_id=round_id,
            error=error[:200],
        )
        return
    text = (
        "Growth prize delivery failed after three attempts.\n"
        f"Round: {round_id}\nUser ID: {user_id}\n"
        f"Error: {error[:300]}"
    )
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=text, parse_mode=None)
        except Exception as exc:
            logger.warning(
                "growth_delivery_alert_failed",
                admin_id=admin_id,
                error=str(exc)[:180],
            )


async def _deliver_winner(winner_id: uuid.UUID) -> None:
    exhausted_failure: tuple[int, str, str] | None = None
    while True:
        async with AsyncSessionLocal() as session:
            winner = await session.scalar(
                select(GrowthWinner).where(GrowthWinner.id == winner_id).with_for_update()
            )
            if not winner or winner.delivery_status != "pending":
                return
            if winner.delivery_attempts >= 3:
                winner.delivery_status = "failed"
                winner.last_error = winner.last_error or "delivery attempts exhausted"
                prize = await session.get(GrowthPrize, winner.prize_id)
                if prize and prize.status == "reserved":
                    prize.status = "available"
                    prize.reserved_round_id = None
                    prize.reserved_at = None
                exhausted_failure = (
                    winner.telegram_user_id,
                    str(winner.round_id),
                    winner.last_error,
                )
                await session.commit()
                break
            attempt = winner.delivery_attempts + 1
            winner.delivery_attempts = attempt
            prize = await session.get(GrowthPrize, winner.prize_id)
            user_id = winner.telegram_user_id
            round_id = str(winner.round_id)
            username = winner.username
            encrypted_payload = prize.encrypted_payload if prize else None
            await session.commit()

        error = ""
        try:
            from app.services.admin_bot.bot import get_bot

            delivery_bot = get_bot()
            if not delivery_bot:
                raise RuntimeError("admin challenge bot is unavailable")
            if not encrypted_payload:
                raise RuntimeError("reserved prize record is missing")
            payload = _fernet().decrypt(encrypted_payload.encode("ascii")).decode("utf-8")
            await delivery_bot.send_message(
                chat_id=user_id,
                text=(
                    "Congratulations — you were selected as a Growth Challenge winner.\n\n"
                    f"Prize: {payload}"
                ),
                parse_mode=None,
            )
        except Exception as exc:
            error = str(exc)[:300]

        async with AsyncSessionLocal() as session:
            winner = await session.scalar(
                select(GrowthWinner).where(GrowthWinner.id == winner_id).with_for_update()
            )
            prize = await session.get(GrowthPrize, winner.prize_id) if winner else None
            if not winner:
                return
            logs = list(winner.delivery_log or [])
            logs.append(
                {
                    "attempt": attempt,
                    "at": _now().isoformat(),
                    "status": "delivered" if not error else "failed",
                    "error": error or None,
                }
            )
            winner.delivery_log = logs
            if not error and prize:
                winner.delivery_status = "delivered"
                winner.delivered_at = _now()
                prize.status = "used"
                prize.used_at = _now()
                logger.info(
                    "growth_prize_delivery_succeeded",
                    round_id=round_id,
                    user_id=user_id,
                    attempt=attempt,
                )
            else:
                winner.last_error = error or "reserved prize record is missing"
                if attempt >= 3:
                    winner.delivery_status = "failed"
                    if prize and prize.status == "reserved":
                        prize.status = "available"
                        prize.reserved_round_id = None
                        prize.reserved_at = None
                logger.warning(
                    "growth_prize_delivery_attempt_failed",
                    round_id=round_id,
                    user_id=user_id,
                    attempt=attempt,
                    error=winner.last_error[:200],
                )
            await session.commit()
            finished = winner.delivery_status in {"delivered", "failed"}
            final_error = winner.last_error or ""

        if finished:
            if error:
                await _notify_delivery_failure(user_id, round_id, final_error)
            return
        await asyncio.sleep(2 ** (attempt - 1))
    if exhausted_failure:
        await _notify_delivery_failure(*exhausted_failure)


async def _announce_round(round_obj: GrowthRound, public_bot) -> bool:
    if not public_bot:
        logger.error("growth_announcement_bot_unavailable", round_id=str(round_obj.id))
        return False
    async with AsyncSessionLocal() as session:
        winners = (
            await session.execute(
                select(GrowthWinner.telegram_user_id, GrowthWinner.username)
                .where(GrowthWinner.round_id == round_obj.id)
                .order_by(GrowthWinner.selected_at)
            )
        ).all()
    if winners:
        names = [
            f"@{username}" if username else f"user {user_id}"
            for user_id, username in winners
        ]
        announcement = (
            "The Growth Challenge is complete. Congratulations to "
            + ", ".join(names)
            + ". Winners were selected from approved entries."
        )
    elif round_obj.last_error == "no_available_prizes":
        announcement = "No winner was selected this round because no RDP or VPS prize was available."
    elif round_obj.last_error == "no_eligible_users":
        announcement = "No eligible winner could be selected this round. The prize remains in the pool."
    else:
        announcement = "No valid entries were approved this round. The prize remains in the pool."

    for channel_id in round_obj.channel_ids or []:
        try:
            await public_bot.send_message(
                chat_id=channel_id,
                text=html.escape(announcement, quote=False),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as exc:
            logger.error(
                "growth_winner_announcement_failed",
                round_id=str(round_obj.id),
                chat_id=str(channel_id),
                error=str(exc)[:200],
            )
    return True


async def finalize_growth_round(round_id: str | uuid.UUID, now: datetime | None = None) -> dict:
    now = now or _now()
    round_uuid = uuid.UUID(str(round_id))
    async with AsyncSessionLocal() as session:
        round_obj = await session.scalar(
            select(GrowthRound).where(GrowthRound.id == round_uuid).with_for_update()
        )
        if not round_obj or round_obj.status not in {"review", "finalizing"}:
            return {"status": "not_due"}
        if round_obj.status == "review" and now < round_obj.review_ends_at:
            return {"status": "not_due"}
        round_obj.status = "finalizing"
        if round_obj.final_outcome is None:
            approved_count = int(
                await session.scalar(
                    select(func.count(GrowthEntry.id)).where(
                        GrowthEntry.round_id == round_obj.id,
                        GrowthEntry.status == "approved",
                    )
                )
                or 0
            )
            approved_users = (
                await session.execute(
                    select(GrowthEntry.telegram_user_id, GrowthEntry.username)
                    .where(
                        GrowthEntry.round_id == round_obj.id,
                        GrowthEntry.status == "approved",
                    )
                    .order_by(GrowthEntry.created_at)
                )
            ).all()
            user_names: dict[int, str | None] = {}
            for user_id, username in approved_users:
                user_names.setdefault(int(user_id), username)
            recent_wins = (
                await session.execute(
                    select(GrowthWinner.telegram_user_id).where(
                        GrowthWinner.selected_at >= now - WIN_COOLDOWN
                    )
                )
            ).scalars().all()
            blocked_users = {int(user_id) for user_id in recent_wins}
            eligible = [
                (user_id, username)
                for user_id, username in user_names.items()
                if user_id not in blocked_users
            ]
            desired = 2 if approved_count >= 10 else 1
            prizes = (
                await session.execute(
                    select(GrowthPrize)
                    .where(
                        GrowthPrize.status == "available",
                        GrowthPrize.kind.in_(round_obj.prize_types or ("RDP", "VPS")),
                    )
                    .order_by(GrowthPrize.created_at)
                    .with_for_update(skip_locked=True)
                )
            ).scalars().all()
            try:
                cipher = _fernet()
            except RuntimeError:
                cipher = None
            usable_prizes: list[GrowthPrize] = []
            for prize in prizes:
                try:
                    if not cipher:
                        raise RuntimeError("prize encryption key unavailable")
                    cipher.decrypt(prize.encrypted_payload.encode("ascii"))
                    usable_prizes.append(prize)
                except Exception:
                    logger.warning("growth_prize_unreadable", prize_id=str(prize.id))
                if len(usable_prizes) >= desired:
                    break
            prizes = usable_prizes
            winner_count = min(desired, len(eligible), len(prizes))
            if winner_count:
                selected_users = random.SystemRandom().sample(eligible, winner_count)
                for (user_id, username), prize in zip(selected_users, prizes):
                    prize.status = "reserved"
                    prize.reserved_round_id = round_obj.id
                    prize.reserved_at = now
                    session.add(
                        GrowthWinner(
                            round_id=round_obj.id,
                            prize_id=prize.id,
                            telegram_user_id=user_id,
                            username=username,
                            delivery_status="pending",
                            delivery_attempts=0,
                            delivery_log=[],
                            selected_at=now,
                        )
                    )
                round_obj.final_outcome = "completed"
                if desired == 2 and winner_count < 2:
                    logger.warning(
                        "growth_second_winner_unavailable",
                        round_id=str(round_obj.id),
                        approved_entries=approved_count,
                        available_prizes=len(prizes),
                        eligible_users=len(eligible),
                    )
            else:
                round_obj.final_outcome = "no_winner"
                if not prizes:
                    round_obj.last_error = "no_available_prizes"
                else:
                    round_obj.last_error = "no_eligible_users"
                if approved_count == 0:
                    round_obj.last_error = "no_approved_entries"
            await session.commit()
        else:
            await session.commit()
        winner_ids = (
            await session.execute(
                select(GrowthWinner.id).where(GrowthWinner.round_id == round_obj.id)
            )
        ).scalars().all()
        round_copy = round_obj

    for winner_id in winner_ids:
        await _deliver_winner(winner_id)
    public_bot = _public_bot()
    if not round_copy.announcement_sent:
        announced = await _announce_round(round_copy, public_bot)
        if not announced:
            return {"status": "announcement_pending", "round_id": str(round_uuid)}
        async with AsyncSessionLocal() as session:
            updated = await session.scalar(
                select(GrowthRound).where(GrowthRound.id == round_uuid).with_for_update()
            )
            if updated:
                updated.announcement_sent = True
                await session.commit()

    async with AsyncSessionLocal() as session:
        completed = await session.scalar(
            select(GrowthRound).where(GrowthRound.id == round_uuid).with_for_update()
        )
        if completed:
            completed.status = completed.final_outcome or "no_winner"
            completed.is_active = False
            completed.status_updated_at = _now()
            await session.commit()
    return {"status": round_copy.final_outcome or "no_winner", "round_id": str(round_uuid)}


async def advance_growth_schedule(now: datetime | None = None) -> dict:
    now = now or _now()
    due_round_id: uuid.UUID | None = None
    status_to_refresh: uuid.UUID | None = None
    async with AsyncSessionLocal() as session:
        active = await session.scalar(
            select(GrowthRound).where(GrowthRound.is_active.is_(True)).with_for_update()
        )
        if active:
            if active.status == "draft" and active.started_at < now - timedelta(minutes=20):
                active.status = "publish_failed"
                active.is_active = False
                active.last_error = "stale draft recovered by scheduler"
                await session.commit()
            elif active.status == "open" and now >= active.entries_close_at:
                active.status = "review"
                active.status_updated_at = now
                status_to_refresh = active.id
                if now >= active.review_ends_at:
                    due_round_id = active.id
                await session.commit()
            elif active.status == "open":
                if not active.status_updated_at or now - active.status_updated_at >= timedelta(minutes=5):
                    status_to_refresh = active.id
                    active.status_updated_at = now
                    await session.commit()
            elif active.status == "review" and now >= active.review_ends_at:
                due_round_id = active.id
            elif active.status == "review":
                if not active.status_updated_at or now - active.status_updated_at >= timedelta(minutes=5):
                    status_to_refresh = active.id
                    active.status_updated_at = now
                    await session.commit()
            elif active.status == "finalizing":
                due_round_id = active.id
            else:
                return {"status": active.status}

    if status_to_refresh:
        await refresh_growth_post(status_to_refresh)
    if due_round_id:
        await finalize_growth_round(due_round_id, now)

    async with AsyncSessionLocal() as session:
        active = await session.scalar(
            select(GrowthRound).where(GrowthRound.is_active.is_(True)).limit(1)
        )
        latest = await session.scalar(
            select(GrowthRound).order_by(GrowthRound.started_at.desc()).limit(1)
        )
        should_start = not active and (
            latest is None or latest.next_round_at <= now
        )
    if should_start:
        return await start_growth_round()
    if active:
        return {"status": active.status, "round_id": str(active.id)}
    return {"status": latest.status if latest else "idle"}


async def run_growth_challenge_scheduler() -> None:
    logger.info(
        "growth_challenge_scheduler_started",
        round_hours=ROUND_HOURS,
        entries_hours=ENTRY_HOURS,
        review_hours=REVIEW_HOURS,
    )
    while True:
        try:
            async with _scheduler_lock:
                await advance_growth_schedule()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("growth_challenge_scheduler_failed", error=str(exc)[:240])
        await asyncio.sleep(30)
