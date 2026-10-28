import asyncio
import hashlib
import html
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Awaitable, Callable

from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.channel import TelegramChannel
from app.models.growth import GrowthEntry, GrowthRound, GrowthWinner

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
_last_scheduler_skip_by_reason: dict[str, str] = {}


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
    system = (
        "Write natural English copy for a Telegram channel promotion challenge. "
        "Sound like a person, not an AI or an ad template. Avoid emoji, hype, "
        "fake urgency, repeated slogans, and filler. Do not mention prizes; the bot "
        "adds the fixed prize line separately."
    )
    for attempt in range(1, SIMILARITY_RETRIES + 1):
        variation = random.choice(variation_prompts)
        prompt = (
            f"Create one fresh Growth Challenge. The action must be: "
            f"{CHALLENGE_TYPE_PROMPTS[challenge_type]}\n"
            f"Variation direction: {variation}\n"
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


def _prize_copy(round_obj: GrowthRound) -> str:
    options = (
        "Prize: a free RDP or VPS.",
        "One winner will receive a free RDP or VPS.",
        "The prize is a free RDP or VPS.",
        "Win a free RDP or VPS.",
    )
    digest = hashlib.sha256(str(round_obj.id).encode("utf-8")).digest()
    return options[digest[0] % len(options)]


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
    return f"{round_obj.challenge_text.strip()}\n\n{_prize_copy(round_obj)}\n\n{status}"


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
                text=html.escape(
                    f"{round_obj.challenge_text.strip()}\n\n{_prize_copy(round_obj)}",
                    quote=False,
                ),
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
            return {"status": "no_channels"}
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
        return {"status": "admin_bot_unavailable"}
    try:
        challenge_text, challenge_hash = await generate_unique_challenge(
            challenge_type, history, username
        )
    except Exception as exc:
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


async def growth_status() -> dict:
    async with AsyncSessionLocal() as session:
        round_obj = await session.scalar(
            select(GrowthRound).order_by(GrowthRound.started_at.desc()).limit(1)
        )
        pending_deliveries = await session.scalar(
            select(func.count(GrowthWinner.id)).where(
                GrowthWinner.delivery_status == "pending_delivery"
            )
        )
        if not round_obj:
            return {
                "status": "none",
                "pending_deliveries": int(pending_deliveries or 0),
                "delivered_winners": 0,
            }
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
            "pending_deliveries": int(pending_deliveries or 0),
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


async def list_pending_growth_deliveries(limit: int = 50) -> list[dict]:
    async with AsyncSessionLocal() as session:
        winners = (
            await session.execute(
                select(GrowthWinner)
                .where(GrowthWinner.delivery_status == "pending_delivery")
                .order_by(GrowthWinner.selected_at.asc())
                .limit(limit)
            )
        ).scalars().all()
        return [
            {
                "id": str(winner.id),
                "round_id": str(winner.round_id),
                "telegram_user_id": winner.telegram_user_id,
                "username": winner.username,
                "selected_at": winner.selected_at,
            }
            for winner in winners
        ]


async def mark_growth_delivery_delivered(winner_id: str, admin_id: int) -> dict:
    try:
        winner_uuid = uuid.UUID(str(winner_id))
    except (TypeError, ValueError, AttributeError):
        return {"status": "invalid"}
    async with AsyncSessionLocal() as session:
        winner = await session.scalar(
            select(GrowthWinner).where(GrowthWinner.id == winner_uuid).with_for_update()
        )
        if not winner:
            return {"status": "missing"}
        if winner.delivery_status == "delivered":
            return {"status": "already_delivered", "round_id": str(winner.round_id)}
        if winner.delivery_status != "pending_delivery":
            return {"status": "not_pending", "round_id": str(winner.round_id)}
        winner.delivery_status = "delivered"
        winner.delivered_at = _now()
        result = {
            "status": "delivered",
            "round_id": str(winner.round_id),
            "telegram_user_id": winner.telegram_user_id,
        }
        await session.commit()
    logger.info(
        "growth_delivery_marked_delivered",
        winner_id=winner_id,
        round_id=result["round_id"],
        user_id=result["telegram_user_id"],
        admin_id=admin_id,
    )
    return result


async def _notify_selected_winner(winner_id: uuid.UUID, public_bot) -> None:
    async with AsyncSessionLocal() as session:
        winner = await session.get(GrowthWinner, winner_id)
        if not winner:
            return
        user_id = winner.telegram_user_id
        username = winner.username
        round_id = str(winner.round_id)
        winner_id_text = str(winner.id)

    if public_bot:
        try:
            await public_bot.send_message(
                chat_id=user_id,
                text=(
                    "You won this Growth Challenge. An admin will contact you soon "
                    "to deliver your free RDP or VPS."
                ),
                parse_mode=None,
            )
        except Exception as exc:
            logger.warning(
                "growth_winner_dm_failed",
                round_id=round_id,
                user_id=user_id,
                error=str(exc)[:180],
            )

    try:
        from app.services.admin_bot.bot import get_bot

        admin_bot = get_bot()
    except Exception:
        admin_bot = None
    if not admin_bot:
        logger.error(
            "growth_winner_admin_notification_bot_unavailable",
            winner_id=winner_id_text,
            round_id=round_id,
        )
        return
    winner_name = f"@{username}" if username else "no username"
    text = "Growth Challenge winner — manual delivery pending\n"
    text += f"Winner: {winner_name}"
    text += f"\nTelegram ID: {user_id}\nRound ID: {round_id}"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Mark as delivered",
                callback_data=f"growth:delivered:{winner_id_text}",
            )
        ]]
    )
    for admin_id in settings.admin_ids:
        try:
            await admin_bot.send_message(
                chat_id=admin_id,
                text=text,
                reply_markup=keyboard,
                parse_mode=None,
            )
        except Exception as exc:
            logger.warning(
                "growth_winner_admin_notification_failed",
                admin_id=admin_id,
                winner_id=winner_id_text,
                error=str(exc)[:180],
            )


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
        username = winners[0][1]
        winner_name = f"@{username}" if username else "the selected participant"
        announcement = (
            f"Growth Challenge winner: {winner_name}. "
            "The prize is a free RDP or VPS."
        )
    elif round_obj.last_error == "no_approved_entries":
        announcement = "No winner this round because no entries were approved."
    elif round_obj.last_error == "no_eligible_users":
        announcement = (
            "No winner this round. Approved participants who won within the last "
            "7 days were not eligible."
        )
    else:
        announcement = "No winner was selected this round."

    posts = list(round_obj.published_messages or [])
    if not posts:
        logger.error("growth_winner_announcement_missing_posts", round_id=str(round_obj.id))
        return False
    succeeded = 0
    post_text = html.escape(
        f"{round_obj.challenge_text.strip()}\n\n{_prize_copy(round_obj)}\n\n{announcement}",
        quote=False,
    )
    for post in posts:
        try:
            await public_bot.edit_message_text(
                chat_id=post["chat_id"],
                message_id=int(post["message_id"]),
                text=post_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            succeeded += 1
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                succeeded += 1
                continue
            logger.warning(
                "growth_winner_announcement_failed",
                round_id=str(round_obj.id),
                chat_id=str(post.get("chat_id")),
                error=str(exc)[:200],
            )
    return succeeded == len(posts)


async def finalize_growth_round(round_id: str | uuid.UUID, now: datetime | None = None) -> dict:
    now = now or _now()
    round_uuid = uuid.UUID(str(round_id))
    new_winner_ids: list[uuid.UUID] = []
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
            recent_wins = (
                await session.execute(
                    select(GrowthWinner.telegram_user_id).where(
                        GrowthWinner.selected_at > now - WIN_COOLDOWN
                    )
                )
            ).scalars().all()
            blocked_users = {int(user_id) for user_id in recent_wins}
            eligible = [
                (int(user_id), username)
                for user_id, username in approved_users
                if int(user_id) not in blocked_users
            ]
            if approved_count == 0:
                round_obj.final_outcome = "no_winner"
                round_obj.last_error = "no_approved_entries"
            elif eligible:
                user_id, username = random.SystemRandom().choice(eligible)
                winner = GrowthWinner(
                    round_id=round_obj.id,
                    telegram_user_id=user_id,
                    username=username,
                    delivery_status="pending_delivery",
                    selected_at=now,
                )
                session.add(winner)
                await session.flush()
                new_winner_ids.append(winner.id)
                round_obj.final_outcome = "completed"
            else:
                round_obj.final_outcome = "no_winner"
                round_obj.last_error = "no_eligible_users"
            await session.commit()
        else:
            await session.commit()
        round_copy = round_obj

    public_bot = _public_bot()
    for winner_id in new_winner_ids:
        await _notify_selected_winner(winner_id, public_bot)
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


async def _log_scheduler_skip_once(result: dict) -> None:
    reason = result.get("status")
    if reason not in {
        "bot_unavailable",
        "no_channels",
        "admin_bot_unavailable",
        "generation_failed",
        "publish_failed",
    }:
        return
    async with AsyncSessionLocal() as session:
        latest = await session.scalar(
            select(GrowthRound).order_by(GrowthRound.started_at.desc()).limit(1)
        )
        scheduled_at = latest.next_round_at.isoformat() if latest else "initial"
    if _last_scheduler_skip_by_reason.get(reason) == scheduled_at:
        return
    _last_scheduler_skip_by_reason[reason] = scheduled_at
    logger.warning(
        "growth_round_scheduler_skipped",
        reason=reason,
        scheduled_at=scheduled_at,
    )


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
                result = await advance_growth_schedule()
                await _log_scheduler_skip_once(result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("growth_challenge_scheduler_failed", error=str(exc)[:240])
        await asyncio.sleep(30)
