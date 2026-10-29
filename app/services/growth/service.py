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
    from app.services.growth.publishing import start_growth_round as publish_growth_round
    return await publish_growth_round(bot=bot, now=now)


async def _edit_round_posts(round_obj: GrowthRound, entries_count: int, bot, now: datetime) -> None:
    from app.services.growth.publishing import refresh_growth_post
    await refresh_growth_post(str(round_obj.id))


async def refresh_growth_post(round_id: str | uuid.UUID | None = None) -> None:
    from app.services.growth.publishing import refresh_growth_post as refresh
    await refresh(str(round_id) if round_id else None)


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
    from app.services.growth.publishing import finalize_growth_round as finalize
    return await finalize(str(round_id), now)


async def advance_growth_schedule(now: datetime | None = None) -> dict:
    from app.services.growth.publishing import advance_growth_schedule as advance
    return await advance(now)


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
    from app.services.growth.publishing import run_growth_challenge_scheduler as run
    await run()
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
