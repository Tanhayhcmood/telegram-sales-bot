import asyncio
import hashlib
import html
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.channel import TelegramChannel
from app.models.growth import GrowthEntry, GrowthRound, GrowthWinner
from app.services.growth.bot import get_growth_bot, get_growth_bot_username

logger = get_logger(__name__)
ROUND_HOURS = 9
ENTRY_HOURS = 8
WIN_COOLDOWN = timedelta(days=7)
MAX_BONUS_ENTRIES = 30
CHALLENGE_TYPES = ("share_post", "invite_friends", "story_status", "tech_quiz")
_scheduler_lock = asyncio.Lock()
_last_skip: dict[str, str] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_text(text: str) -> str:
    normalized = " ".join((text or "").lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _next_type(previous: str | None) -> str:
    if previous not in CHALLENGE_TYPES:
        return CHALLENGE_TYPES[0]
    return CHALLENGE_TYPES[(CHALLENGE_TYPES.index(previous) + 1) % len(CHALLENGE_TYPES)]


def _merge_target_channels(database_channels: list[Any], required_channels: str | None) -> list[str]:
    """Combine registered and environment channels without dropping duplicates."""
    channels = [
        str(channel).strip()
        for channel in database_channels
        if channel is not None and str(channel).strip()
    ]
    channels.extend(
        channel.strip()
        for channel in (required_channels or "").split(",")
        if channel.strip()
    )
    return list(dict.fromkeys(channels))


async def _target_channels(session) -> list[str]:
    result = await session.execute(
        select(TelegramChannel.telegram_channel_id).where(TelegramChannel.is_active.is_(True))
    )
    # A previous permission failure is a status, not a permanent configuration
    # decision. Retry every configured target on each round so restored access
    # can recover without a database edit.
    return _merge_target_channels(result.scalars().all(), settings.REQUIRED_CHANNELS)


def _caption(round_obj: GrowthRound, entries: int, now: datetime, bot_username: str | None,
             sister: str, leaders: list[dict[str, Any]] | None = None) -> str:
    prize = "Prize: one free RDP or VPS."
    if round_obj.status == "open":
        seconds = max(0, int((round_obj.entries_close_at - now).total_seconds()))
        left = f"{seconds // 3600}h {(seconds % 3600) // 60}m"
        status = f"LIVE — {left} left | Entries: {entries}"
    elif round_obj.status == "review":
        status = f"Entries closed | Entries: {entries} | Admin review in progress"
    else:
        status = f"Round complete | Entries: {entries}"
    destination = f"@{bot_username}" if bot_username else "the Growth bot"
    task = round_obj.challenge_text.strip()
    rules = (
        "Rules: Use a genuine screenshot with the group name visible; no spam or misleading invites; "
        f"send proof privately to {destination} (up to 3 submissions)."
    )
    top = ""
    if leaders:
        parts = []
        for row in leaders[:3]:
            name = f"@{row['username']}" if row.get("username") else f"User {row['user_id']}"
            parts.append(f"{name} ({row['entries']})")
        if parts:
            top = "Top inviters: " + ", ".join(parts) + "\n"
    caption = f"{prize}\n\n{task}\n\n{rules}\n\n{status}\n{top}{sister}".strip()
    return caption[:1024]


def _round_keyboard(round_obj: GrowthRound, username: str | None, join_url: str | None) -> InlineKeyboardMarkup:
    rows = []
    if username:
        rows.append([InlineKeyboardButton(
            text="Submit entry",
            url=f"https://t.me/{username.lstrip('@')}?start={round_obj.id}",
        )])
    if join_url:
        rows.append([InlineKeyboardButton(text="Join channel", url=join_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _join_url(bot, channel_id: str) -> str | None:
    if channel_id.startswith("@"):
        return f"https://t.me/{channel_id[1:]}"
    try:
        chat = await bot.get_chat(channel_id)
        if getattr(chat, "username", None):
            return f"https://t.me/{chat.username}"
        if getattr(chat, "invite_link", None):
            return chat.invite_link
        invite = await bot.create_chat_invite_link(chat_id=channel_id, name="Growth Challenge")
        return invite.invite_link
    except Exception as exc:
        logger.warning("growth_channel_join_link_failed", channel_id=channel_id,
                       exception_type=type(exc).__name__, message=str(exc)[:180], step="send")
        return None


async def _sister_line(bot, channels: list[str], index: int) -> str:
    if len(channels) < 2:
        return ""
    sister_id = channels[(index + 1) % len(channels)]
    try:
        chat = await bot.get_chat(sister_id)
        username = getattr(chat, "username", None)
        if username:
            return f"More VPS tips: https://t.me/{username}"
        title = getattr(chat, "title", None)
        return f"Explore our sister channel: {title}." if title else "Explore our sister channel for more VPS tips."
    except Exception:
        return "Explore our sister channel for more VPS tips."


async def _retry_once(operation, *, channel_id: str, step: str):
    try:
        return await operation()
    except TelegramRetryAfter as exc:
        logger.warning("growth_channel_flood_wait", channel_id=channel_id, step=step,
                       retry_after=exc.retry_after)
        await asyncio.sleep(max(0, exc.retry_after))
        return await operation()


def _is_permanent(exc: Exception) -> bool:
    text = str(exc).lower()
    if isinstance(exc, TelegramForbiddenError):
        return True
    return isinstance(exc, TelegramBadRequest) and any(
        term in text for term in ("chat not found", "not enough rights", "forbidden", "bot was kicked")
    )


async def _record_channel_status(channel_id: str, status: str, step: str | None = None,
                                error: str | None = None, deactivate: bool = False) -> None:
    try:
        from app.models.growth import GrowthChannelStatus
    except (ImportError, AttributeError):
        return
    async with AsyncSessionLocal() as session:
        row = await session.get(GrowthChannelStatus, str(channel_id))
        if row is None:
            row = GrowthChannelStatus(channel_id=str(channel_id), is_active=True)
            session.add(row)
        row.last_status = status
        row.last_step = step
        row.last_error = error[:1000] if error else None
        row.last_publish_at = _now()
        # Successful or transient attempts restore the channel; permanent errors
        # remain visible as disabled, but _target_channels will retry them next round.
        row.is_active = not deactivate
        await session.commit()


async def _admin_channel_summary(round_id: str, failures: list[dict[str, str]]) -> None:
    if not failures:
        return
    from app.services.admin_bot.bot import get_bot as get_admin_bot
    admin_bot = get_admin_bot()
    if not admin_bot:
        logger.error("growth_channel_admin_summary_unavailable", round_id=round_id,
                     failed_channels=len(failures))
        return
    lines = [f"Growth round {round_id}: permanently disabled channels"]
    lines.extend(f"{row['channel_id']}: {row['reason'][:180]}" for row in failures[:30])
    text = "\n".join(lines)
    for admin_id in settings.admin_ids:
        try:
            await admin_bot.send_message(chat_id=admin_id, text=text, parse_mode=None)
        except Exception as exc:
            logger.warning("growth_channel_admin_summary_failed", admin_id=admin_id,
                           error=str(exc)[:160])


async def _publish_channel(bot, channel_id: str, round_obj: GrowthRound, entries: int,
                           channels: list[str], index: int) -> tuple[dict | None, dict | None, dict | None]:
    username = get_growth_bot_username()
    join_url = await _join_url(bot, channel_id)
    sister = await _sister_line(bot, channels, index)
    caption = _caption(round_obj, entries, _now(), username, sister)
    markup = _round_keyboard(round_obj, username, join_url)
    banner = Path(__file__).resolve().parents[2] / "assets" / "challenge_banner.jpg"
    message = None
    try:
        message = await _retry_once(
            lambda: bot.send_photo(chat_id=channel_id, photo=FSInputFile(str(banner)),
                                   caption=caption, parse_mode=None, reply_markup=markup),
            channel_id=channel_id, step="send",
        )
        record = {"chat_id": str(channel_id), "message_id": int(message.message_id)}
        await _record_channel_status(channel_id, "published", "send")
    except Exception as exc:
        permanent = _is_permanent(exc)
        logger.error("growth_channel_publish_failed", channel_id=channel_id, step="send",
                     exception_type=type(exc).__name__, message=str(exc)[:240])
        await _record_channel_status(channel_id, "deactivated" if permanent else "failed",
                                     "send", str(exc), permanent)
        reason = {"channel_id": channel_id, "reason": f"send: {type(exc).__name__}: {exc}"} if permanent else None
        return None, {"channel_id": channel_id, "status": "failed"}, reason

    record["sister"] = sister
    try:
        edited = _caption(round_obj, entries, _now(), username, sister)
        await _retry_once(
            lambda: bot.edit_message_caption(chat_id=channel_id, message_id=record["message_id"],
                                            caption=edited, parse_mode=None, reply_markup=markup),
            channel_id=channel_id, step="edit",
        )
        await _record_channel_status(channel_id, "published", "edit")
    except Exception as exc:
        permanent = _is_permanent(exc)
        logger.error("growth_channel_publish_failed", channel_id=channel_id, step="edit",
                     exception_type=type(exc).__name__, message=str(exc)[:240])
        await _record_channel_status(channel_id, "deactivated" if permanent else "partial",
                                     "edit", str(exc), permanent)
        if permanent:
            return record, {"channel_id": channel_id, "status": "partial"}, {
                "channel_id": channel_id, "reason": f"edit: {type(exc).__name__}: {exc}"
            }
    try:
        await _retry_once(
            lambda: bot.pin_chat_message(chat_id=channel_id, message_id=record["message_id"],
                                         disable_notification=True),
            channel_id=channel_id, step="pin",
        )
    except Exception as exc:
        logger.warning("growth_channel_publish_failed", channel_id=channel_id, step="pin",
                       exception_type=type(exc).__name__, message=str(exc)[:240])
    return record, {"channel_id": channel_id, "status": "published"}, None


async def _unpin_previous(bot, posts: list[dict]) -> None:
    for post in posts or []:
        try:
            await bot.unpin_chat_message(chat_id=post["chat_id"], message_id=int(post["message_id"]))
        except Exception as exc:
            logger.warning("growth_previous_post_unpin_failed", channel_id=str(post.get("chat_id")),
                           exception_type=type(exc).__name__, message=str(exc)[:180], step="pin")


async def _challenge_copy(challenge_type: str, angle: str, history: list[str], username: str | None,
                          sister: str) -> tuple[str, str]:
    try:
        from app.services.growth.content import generate_growth_copy
        return await generate_growth_copy(challenge_type, angle, history, username, sister)
    except ImportError:
        from app.services.growth.service import generate_unique_challenge
        text, digest = await generate_unique_challenge(challenge_type, history, username)
        return text, angle


async def start_growth_round(bot=None, now: datetime | None = None) -> dict:
    bot = bot or get_growth_bot()
    if not bot:
        return {"status": "bot_unavailable"}
    now = now or _now()
    async with _scheduler_lock:
        async with AsyncSessionLocal() as session:
            active = await session.scalar(select(GrowthRound).where(GrowthRound.is_active.is_(True))
                                          .with_for_update())
            if active and active.started_at >= now - timedelta(minutes=20):
                return {"status": "active", "round_id": str(active.id)}
            if active:
                active.status = "publish_failed"
                active.is_active = False
                await session.commit()
            channels = await _target_channels(session)
            if not channels:
                return {"status": "no_channels"}
            previous = await session.scalar(select(GrowthRound).order_by(GrowthRound.started_at.desc()).limit(1))
            previous_type = previous.challenge_type if previous else None
            previous_posts = list(previous.published_messages or []) if previous else []
            history_rows = await session.execute(select(GrowthRound.challenge_text)
                                                 .order_by(GrowthRound.started_at.desc()).limit(60))
            history = [row[0] for row in history_rows.all() if row[0]]
        challenge_type = _next_type(previous_type)
        index = CHALLENGE_TYPES.index(challenge_type)
        angles = ("a practical group-sharing moment", "a personal invitation", "a useful status update",
                  "a quick VPS knowledge check")
        angle = angles[index]
        sister = await _sister_line(bot, channels, 0)
        username = get_growth_bot_username()
        try:
            text, angle = await _challenge_copy(challenge_type, angle, history, username, sister)
        except Exception as exc:
            logger.error("growth_challenge_generation_failed", challenge_type=challenge_type,
                         exception_type=type(exc).__name__, message=str(exc)[:200])
            return {"status": "generation_failed"}
        round_obj = GrowthRound(
            challenge_type=challenge_type, challenge_text=text, challenge_hash=_hash_text(text),
            status="draft", is_active=True, channel_ids=channels, published_messages=[],
            started_at=now, entries_close_at=now + timedelta(hours=ENTRY_HOURS),
            review_ends_at=now + timedelta(hours=ROUND_HOURS),
            next_round_at=now + timedelta(hours=ROUND_HOURS), status_updated_at=now,
        )
        setattr(round_obj, "challenge_angle", angle)
        async with AsyncSessionLocal() as session:
            session.add(round_obj)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return {"status": "active"}
            await _unpin_previous(bot, previous_posts)
            published, failures, permanent = [], [], []
            for i, channel_id in enumerate(channels):
                record, result, error = await _publish_channel(bot, channel_id, round_obj, 0, channels, i)
                if record:
                    published.append(record)
                    round_obj.published_messages = list(published)
                    round_obj.status = "open"
                    await session.commit()
                if result:
                    failures.append(result)
                if error:
                    permanent.append(error)
            round_obj.status = "open" if published else "publish_failed"
            round_obj.is_active = bool(published)
            round_obj.last_error = "; ".join(x["reason"] for x in permanent)[:1000] or None
            await session.commit()
        await _admin_channel_summary(str(round_obj.id), permanent)
        logger.info("growth_round_published", round_id=str(round_obj.id), challenge_type=challenge_type,
                    published=len(published), total=len(channels))
        return {"status": "open" if published else "publish_failed", "round_id": str(round_obj.id),
                "challenge_type": challenge_type, "published": len(published), "total": len(channels)}


async def _invite_bonus(round_obj: GrowthRound) -> dict[int, int]:
    try:
        from app.services.growth.referrals import verified_bonus_entries
        return await verified_bonus_entries(round_obj)
    except (ImportError, AttributeError):
        return {}


async def growth_leaderboard(round_id: str | None = None) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        query = select(GrowthRound).where(GrowthRound.is_active.is_(True))
        if round_id:
            query = query.where(GrowthRound.id == round_id)
        round_obj = await session.scalar(query.order_by(GrowthRound.started_at.desc()).limit(1))
        if not round_obj:
            return []
        rows = (await session.execute(
            select(GrowthEntry.telegram_user_id, GrowthEntry.username, func.count(GrowthEntry.id))
            .where(GrowthEntry.round_id == round_obj.id, GrowthEntry.status == "approved")
            .group_by(GrowthEntry.telegram_user_id, GrowthEntry.username)
        )).all()
    bonus = await _invite_bonus(round_obj)
    result = [{"user_id": int(uid), "username": name,
               "entries": int(count) + bonus.get(int(uid), 0)} for uid, name, count in rows]
    result.sort(key=lambda row: (-row["entries"], row["user_id"]))
    return result[:10]


async def refresh_growth_post(round_id: str | None = None) -> None:
    bot = get_growth_bot()
    if not bot:
        return
    async with AsyncSessionLocal() as session:
        query = select(GrowthRound).where(GrowthRound.is_active.is_(True))
        if round_id:
            import uuid
            query = query.where(GrowthRound.id == uuid.UUID(str(round_id)))
        round_obj = await session.scalar(query.order_by(GrowthRound.started_at.desc()).limit(1))
        if not round_obj:
            return
        entries = await session.scalar(select(func.count(GrowthEntry.id)).where(
            GrowthEntry.round_id == round_obj.id, GrowthEntry.status.in_(("pending", "approved"))))
        posts = list(round_obj.published_messages or [])
        channels = list(round_obj.channel_ids or [])
        round_copy = round_obj
    leaders = await growth_leaderboard(str(round_copy.id))
    for post in posts:
        channel_id = str(post["chat_id"])
        sister = post.get("sister") or await _sister_line(bot, channels, channels.index(channel_id) if channel_id in channels else 0)
        try:
            markup = _round_keyboard(round_copy, get_growth_bot_username(), await _join_url(bot, channel_id))
            caption = _caption(round_copy, int(entries or 0) + sum(x["entries"] for x in leaders),
                               _now(), get_growth_bot_username(), sister, leaders)
            await _retry_once(lambda: bot.edit_message_caption(
                chat_id=channel_id, message_id=int(post["message_id"]), caption=caption,
                parse_mode=None, reply_markup=markup), channel_id=channel_id, step="edit")
        except Exception as exc:
            logger.error("growth_channel_publish_failed", channel_id=channel_id, step="edit",
                         exception_type=type(exc).__name__, message=str(exc)[:200])


async def _member_check(bot, user_id: int, channels: list[str]) -> bool:
    for channel in channels:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status in {"member", "administrator", "creator"} or (
                member.status == "restricted" and getattr(member, "is_member", False)
            ):
                return True
        except Exception as exc:
            logger.warning("growth_membership_check_failed", channel_id=str(channel), user_id=user_id,
                           exception_type=type(exc).__name__, message=str(exc)[:160])
            try:
                from app.services.growth.referrals import userbot_is_member
                if await userbot_is_member(str(channel), user_id):
                    return True
            except Exception:
                pass
    return False


async def _notify_winner(winner: GrowthWinner, bot) -> None:
    try:
        await bot.send_message(chat_id=winner.telegram_user_id,
            text="You won this Growth Challenge. An admin will contact you soon to deliver your free RDP or VPS.",
            parse_mode=None)
    except Exception as exc:
        logger.warning("growth_winner_dm_failed", user_id=winner.telegram_user_id,
                       exception_type=type(exc).__name__, message=str(exc)[:180])
    from app.services.admin_bot.bot import get_bot as get_admin_bot
    admin_bot = get_admin_bot()
    if not admin_bot:
        logger.error("growth_winner_admin_notification_bot_unavailable", winner_id=str(winner.id))
        return
    user_name = f"@{winner.username}" if winner.username else "no username"
    text = ("Growth Challenge winner — manual delivery pending\n"
            f"Winner: {user_name}\nTelegram ID: {winner.telegram_user_id}\nRound ID: {winner.round_id}")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="Mark as delivered", callback_data=f"growth:delivered:{winner.id}")]])
    for admin_id in settings.admin_ids:
        try:
            await admin_bot.send_message(chat_id=admin_id, text=text, reply_markup=keyboard, parse_mode=None)
        except Exception as exc:
            logger.warning("growth_winner_admin_notification_failed", admin_id=admin_id,
                           exception_type=type(exc).__name__, message=str(exc)[:180])


async def _announce_winner(round_obj: GrowthRound, bot, winner: GrowthWinner | None) -> bool:
    announcement = (f"Winner: @{winner.username}. Prize: a free RDP or VPS."
                    if winner and winner.username else
                    "A winner has been selected. The prize is a free RDP or VPS."
                    if winner else "No eligible winner this round.")
    success = 0
    for post in round_obj.published_messages or []:
        try:
            await bot.edit_message_caption(chat_id=post["chat_id"], message_id=int(post["message_id"]),
                caption=f"Prize: one free RDP or VPS.\n\n{round_obj.challenge_text[:650]}\n\n{announcement}"[:1024],
                parse_mode=None, reply_markup=None)
            success += 1
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                success += 1
            else:
                logger.warning("growth_winner_announcement_failed", channel_id=post.get("chat_id"),
                               exception_type=type(exc).__name__, message=str(exc)[:160])
    return success == len(round_obj.published_messages or []) and success > 0


async def finalize_growth_round(round_id: str, now: datetime | None = None) -> dict:
    now = now or _now()
    import uuid
    round_uuid = uuid.UUID(str(round_id))
    bot = get_growth_bot()
    if not bot:
        return {"status": "bot_unavailable"}
    async with AsyncSessionLocal() as session:
        round_obj = await session.scalar(select(GrowthRound).where(GrowthRound.id == round_uuid).with_for_update())
        if not round_obj or round_obj.status not in {"review", "finalizing"}:
            return {"status": "not_due"}
        if round_obj.status == "review" and now < round_obj.review_ends_at:
            return {"status": "not_due"}
        round_obj.status = "finalizing"
        await session.commit()
        channel_ids = list(round_obj.channel_ids or [])
        approved = (await session.execute(
            select(GrowthEntry.telegram_user_id, GrowthEntry.username, func.count(GrowthEntry.id))
            .where(GrowthEntry.round_id == round_uuid, GrowthEntry.status == "approved")
            .group_by(GrowthEntry.telegram_user_id, GrowthEntry.username)
        )).all()
        recent = (await session.execute(select(GrowthWinner.telegram_user_id).where(
            GrowthWinner.selected_at >= now - WIN_COOLDOWN))).scalars().all()
        recent_ids = {int(x) for x in recent}
        round_copy = round_obj
    bonus = await _invite_bonus(round_copy)
    eligible = []
    for user_id, username, proofs in approved:
        user_id = int(user_id)
        if user_id in recent_ids or not await _member_check(bot, user_id, channel_ids):
            continue
        weight = int(proofs) + min(MAX_BONUS_ENTRIES, bonus.get(user_id, 0))
        if weight > 0:
            eligible.append((user_id, username, weight))
    winner = None
    if eligible:
        ticket = random.SystemRandom().randrange(sum(row[2] for row in eligible))
        for user_id, username, weight in eligible:
            if ticket < weight:
                winner = (user_id, username)
                break
            ticket -= weight
    async with AsyncSessionLocal() as session:
        current = await session.scalar(select(GrowthRound).where(GrowthRound.id == round_uuid).with_for_update())
        if winner:
            existing = await session.scalar(select(GrowthWinner).where(
                GrowthWinner.round_id == round_uuid, GrowthWinner.telegram_user_id == winner[0]))
            if not existing:
                existing = GrowthWinner(round_id=round_uuid, telegram_user_id=winner[0], username=winner[1],
                    delivery_status="pending_delivery", selected_at=now)
                session.add(existing)
                await session.flush()
            selected = existing
            current.final_outcome = "completed"
        else:
            selected = None
            current.final_outcome = "no_winner"
            current.last_error = "no_eligible_users"
        await session.commit()
        round_copy = current
    if selected:
        await _notify_winner(selected, bot)
    if not round_copy.announcement_sent:
        if not await _announce_winner(round_copy, bot, selected):
            return {"status": "announcement_pending", "round_id": str(round_uuid)}
    async with AsyncSessionLocal() as session:
        current = await session.scalar(select(GrowthRound).where(GrowthRound.id == round_uuid).with_for_update())
        current.announcement_sent = True
        current.status = current.final_outcome or "no_winner"
        current.is_active = False
        current.status_updated_at = _now()
        current.next_round_at = now + timedelta(hours=ROUND_HOURS)
        await session.commit()
    return {"status": round_copy.final_outcome or "no_winner", "round_id": str(round_uuid)}


async def advance_growth_schedule(now: datetime | None = None) -> dict:
    now = now or _now()
    due = None
    refresh = None
    async with AsyncSessionLocal() as session:
        active = await session.scalar(select(GrowthRound).where(GrowthRound.is_active.is_(True)).with_for_update())
        if active:
            if active.status == "open" and now >= active.entries_close_at:
                active.status = "review"
                active.status_updated_at = now
                refresh = str(active.id)
                await session.commit()
            elif active.status == "open" and (not active.status_updated_at or now-active.status_updated_at >= timedelta(minutes=5)):
                active.status_updated_at = now
                refresh = str(active.id)
                await session.commit()
            elif active.status == "review" and now >= active.review_ends_at:
                due = str(active.id)
            elif active.status in {"open", "review", "finalizing"}:
                if active.status == "review" and (not active.status_updated_at or now-active.status_updated_at >= timedelta(minutes=5)):
                    active.status_updated_at = now
                    refresh = str(active.id)
                    await session.commit()
                if active.status == "finalizing":
                    due = str(active.id)
                if not due:
                    return {"status": active.status, "round_id": str(active.id)}
        latest = await session.scalar(select(GrowthRound).order_by(GrowthRound.started_at.desc()).limit(1))
        should_start = not active and (latest is None or latest.next_round_at <= now)
        latest_id = str(latest.id) if latest else "initial"
    if refresh:
        await refresh_growth_post(refresh)
    if due:
        return await finalize_growth_round(due, now)
    if should_start:
        result = await start_growth_round(now=now)
        reason = result.get("status")
        if reason in {"bot_unavailable", "no_channels", "generation_failed", "publish_failed"}:
            if _last_skip.get(reason) != latest_id:
                _last_skip[reason] = latest_id
                logger.warning("growth_round_scheduler_skipped", reason=reason, round_id=latest_id)
        return result
    return {"status": latest.status if latest else "idle"}


async def run_growth_challenge_scheduler() -> None:
    logger.info("growth_challenge_scheduler_started", round_hours=ROUND_HOURS, entries_hours=ENTRY_HOURS)
    while True:
        try:
            async with _scheduler_lock:
                await advance_growth_schedule()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("growth_challenge_scheduler_failed", error=str(exc)[:240])
        await asyncio.sleep(30)


async def list_growth_channel_statuses() -> list[dict[str, Any]]:
    try:
        from app.models.growth import GrowthChannelStatus
    except (ImportError, AttributeError):
        return []
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(GrowthChannelStatus).order_by(GrowthChannelStatus.channel_id))).scalars().all()
        configured = await _target_channels(session)
        configured_set = set(configured)
        by_id = {str(row.channel_id): row for row in rows}
        channel_ids = list(dict.fromkeys(configured + [str(row.channel_id) for row in rows]))
        return [
            {
                "channel_id": channel_id,
                "active": by_id[channel_id].is_active if channel_id in by_id else True,
                "configured": channel_id in configured_set,
                "status": by_id[channel_id].last_status if channel_id in by_id else None,
                "step": by_id[channel_id].last_step if channel_id in by_id else None,
                "error": by_id[channel_id].last_error if channel_id in by_id else None,
                "published_at": by_id[channel_id].last_publish_at if channel_id in by_id else None,
            }
            for channel_id in channel_ids
        ]
