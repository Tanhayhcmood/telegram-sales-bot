import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.growth import GrowthInvite, GrowthJoin, GrowthRound
from app.services.growth.bot import get_growth_bot

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _status_value(value) -> str:
    return str(getattr(value, "value", value)).lower()


def _member_status(member) -> bool:
    status = _status_value(member.status)
    return status in {"member", "administrator", "creator"} or (
        status == "restricted" and bool(getattr(member, "is_member", False))
    )


def _userbot_client():
    try:
        from app.services.userbot.manager import userbot_manager
        return getattr(userbot_manager, "client", None) or getattr(userbot_manager, "_client", None)
    except Exception:
        return None


async def userbot_is_member(channel_id: str, user_id: int) -> bool:
    client = _userbot_client()
    if not client:
        return False
    try:
        connected = client.is_connected()
        if asyncio.iscoroutine(connected):
            connected = await connected
        if not connected:
            return False
        entity = await client.get_entity(int(channel_id) if channel_id.lstrip("-").isdigit() else channel_id)
        await client.get_permissions(entity, user_id)
        return True
    except Exception:
        return False


async def _userbot_invite(channel_id: str, title: str) -> str | None:
    client = _userbot_client()
    if not client:
        return None
    try:
        from telethon.tl.functions.messages import ExportChatInviteRequest
        entity = await client.get_entity(int(channel_id) if channel_id.lstrip("-").isdigit() else channel_id)
        result = await client(ExportChatInviteRequest(peer=entity, title=title[:32]))
        return getattr(result, "link", None)
    except Exception as exc:
        logger.warning("growth_userbot_invite_failed", channel_id=channel_id,
                       exception_type=type(exc).__name__, message=str(exc)[:160])
        return None


async def create_growth_invite(user_id: int) -> str | None:
    bot = get_growth_bot()
    if not bot:
        return None
    async with AsyncSessionLocal() as session:
        round_obj = await session.scalar(select(GrowthRound).where(
            GrowthRound.is_active.is_(True), GrowthRound.status == "open").order_by(
                GrowthRound.started_at.desc()).limit(1))
        if not round_obj or not round_obj.channel_ids:
            return None
        round_id = round_obj.id
        channel_id = str(round_obj.channel_ids[0])
        existing = await session.scalar(select(GrowthInvite).where(
            GrowthInvite.round_id == round_id, GrowthInvite.inviter_user_id == user_id))
        if existing:
            return existing.invite_link
    link = None
    name = f"g-{str(round_id).replace('-', '')[:8]}-{user_id}"[:32]
    try:
        invite = await bot.create_chat_invite_link(chat_id=channel_id, name=name)
        link = invite.invite_link
    except Exception as exc:
        logger.info("growth_bot_invite_unavailable_using_userbot", channel_id=channel_id,
                    exception_type=type(exc).__name__, message=str(exc)[:140])
        link = await _userbot_invite(channel_id, name)
    if not link:
        return None
    async with AsyncSessionLocal() as session:
        row = GrowthInvite(round_id=round_id, inviter_user_id=user_id,
                           channel_id=channel_id, invite_link=link)
        session.add(row)
        try:
            await session.commit()
            return link
        except IntegrityError:
            await session.rollback()
            existing = await session.scalar(select(GrowthInvite).where(
                GrowthInvite.round_id == round_id, GrowthInvite.inviter_user_id == user_id))
            return existing.invite_link if existing else None


async def record_growth_membership_update(update) -> None:
    invite_link_obj = getattr(update, "invite_link", None)
    invite_link = getattr(invite_link_obj, "invite_link", None)
    user = getattr(update, "new_chat_member", None)
    joined_user = getattr(user, "user", None)
    if not invite_link or not joined_user or getattr(joined_user, "is_bot", False):
        return
    new_member = _member_status(user)
    old_member_obj = getattr(update, "old_chat_member", None)
    was_member = _member_status(old_member_obj) if old_member_obj else False
    now = _now()
    async with AsyncSessionLocal() as session:
        invite = await session.scalar(select(GrowthInvite).where(GrowthInvite.invite_link == invite_link))
        if not invite or invite.inviter_user_id == joined_user.id:
            return
        row = await session.scalar(select(GrowthJoin).where(
            GrowthJoin.round_id == invite.round_id, GrowthJoin.invitee_user_id == joined_user.id))
        if new_member and not was_member:
            if row:
                row.left_at = None
                row.joined_at = now
            else:
                row = GrowthJoin(round_id=invite.round_id, invite_id=invite.id,
                    inviter_user_id=invite.inviter_user_id, invitee_user_id=joined_user.id,
                    channel_id=invite.channel_id, joined_at=now, suspicious=False)
                session.add(row)
        elif not new_member and was_member and row:
            row.left_at = now
        await session.flush()
        if row and new_member and not was_member:
            recent = await session.scalar(select(func.count(GrowthJoin.id)).where(
                GrowthJoin.round_id == invite.round_id,
                GrowthJoin.joined_at >= now - timedelta(minutes=10)))
            if int(recent or 0) >= 10:
                row.suspicious = True
                if int(recent or 0) == 10:
                    await session.commit()
                    await _notify_suspicious_spike(str(invite.round_id), int(recent or 0))
                    return
        await session.commit()


async def _notify_suspicious_spike(round_id: str, count: int) -> None:
    try:
        from app.services.admin_bot.bot import get_bot
        admin_bot = get_bot()
        if not admin_bot:
            return
        text = (f"Growth Challenge referral spike flagged: {count} joins in 10 minutes. "
                f"Round {round_id}. Please review the referral activity.")
        for admin_id in settings.admin_ids:
            await admin_bot.send_message(chat_id=admin_id, text=text, parse_mode=None)
    except Exception as exc:
        logger.warning("growth_suspicious_spike_notice_failed", round_id=round_id,
                       exception_type=type(exc).__name__, message=str(exc)[:160])


async def verified_bonus_entries(round_obj: GrowthRound) -> dict[int, int]:
    bot = get_growth_bot()
    if not bot:
        return {}
    async with AsyncSessionLocal() as session:
        joins = (await session.execute(select(GrowthJoin).where(
            GrowthJoin.round_id == round_obj.id,
            GrowthJoin.left_at.is_(None),
            GrowthJoin.joined_at <= round_obj.entries_close_at,
        ))).scalars().all()
    counts: dict[int, int] = {}
    for join in joins:
        try:
            member = await bot.get_chat_member(join.channel_id, join.invitee_user_id)
            joiner_active = _member_status(member)
        except Exception:
            joiner_active = await userbot_is_member(join.channel_id, join.invitee_user_id)
        if not joiner_active:
            continue
        try:
            inviter = await bot.get_chat_member(join.channel_id, join.inviter_user_id)
            inviter_active = _member_status(inviter)
        except Exception:
            inviter_active = await userbot_is_member(join.channel_id, join.inviter_user_id)
        if inviter_active:
            inviter_id = int(join.inviter_user_id)
            counts[inviter_id] = counts.get(inviter_id, 0) + 3
    return {user_id: min(entries, 30) for user_id, entries in counts.items()}
