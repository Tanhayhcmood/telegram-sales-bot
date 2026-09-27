import asyncio
from html import escape
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.challenge import Challenge, ChallengeParticipant
from app.models.public_user import PublicUser
from app.services.challenges.force_sub import (
    build_gate_message,
    check_membership,
    invalidate_cache,
    send_gate,
)
from app.services.challenges.service import (
    accept_terms,
    challenge_summary,
    get_active_challenge,
    get_or_create_public_user,
    leaderboard,
    public_referral_link,
    register_participant,
    submit_answer,
)

logger = get_logger(__name__)
router = Router()
_bot: Bot | None = None
_dispatcher: Dispatcher | None = None
_username: str | None = None
_polling_task: asyncio.Task | None = None


def get_public_bot_username() -> str | None:
    return _username or settings.PUBLIC_BOT_USERNAME or None


def get_public_bot() -> Bot | None:
    return _bot


# ── keyboard helpers ───────────────────────────────────────────────────────

def _answer_keyboard(slug: str, answers: list[str]) -> InlineKeyboardMarkup:
    labels = ("A", "B", "C", "D")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{labels[i]}  •  {answer}",
                    callback_data=f"challenge:{slug}:{i}",
                )
            ]
            for i, answer in enumerate(answers)
        ]
    )


def _registration_keyboard(payload: str = "") -> InlineKeyboardMarkup:
    suffix = f":{payload}" if payload else ""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Join the challenge", callback_data=f"terms_accept{suffix}")],
            [InlineKeyboardButton(text="How it works", callback_data="challenge_help")],
        ]
    )


def _profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎯 Active challenge", callback_data="active_challenge"),
                InlineKeyboardButton(text="🔗 Invite friends", callback_data="my_referral"),
            ],
            [InlineKeyboardButton(text="🏆 Leaderboard", callback_data="show_leaderboard")],
        ]
    )


# ── membership gate ──────────────────────────────────────────────────────────


async def _require_membership(message: Message) -> bool:
    """Return True if the user passes the force-subscription gate.

    When False the gate message has already been sent — the caller should
    simply return without doing any further work.

    Always call this as the very FIRST check inside every protected handler.
    """
    if _bot is None:
        await message.answer(
            "⚠️ The bot is starting up. Please wait a few seconds.",
            parse_mode=ParseMode.HTML,
        )
        return False
    allowed, statuses = await check_membership(_bot, message.from_user.id)
    if not allowed:
        await send_gate(message, statuses)
    return allowed


async def _require_membership_cb(callback: CallbackQuery) -> bool:
    """Return True if the user passes the force-subscription gate (callback version).

    Uses callback.from_user.id (the real user), NOT callback.message.from_user.id
    (which would be the bot itself).  Sends the gate message when blocked.
    """
    if _bot is None:
        await callback.answer("⚠️ The bot is starting up. Please wait a few seconds.", show_alert=True)
        return False
    allowed, statuses = await check_membership(_bot, callback.from_user.id)
    if not allowed:
        await callback.answer("Please join all required channels first.", show_alert=True)
        if callback.message:
            await send_gate(callback.message, statuses)
    return allowed


# ── content helpers ────────────────────────────────────────────────────────────

def _challenge_text(challenge: Challenge) -> str:
    return (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "      <b>UPGRADE TEAM</b>\n"
        "      <b>RDP SECURITY CHALLENGE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>{escape(challenge.title)}</b>\n\n"
        f"🎯 <b>Challenge Brief</b>\n{escape(challenge.question)}\n\n"
        f"🎁 <b>Reward:</b> {escape(challenge.reward)}\n"
        f"⏱ <b>Deadline:</b> {challenge.ends_at.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        "<i>Select the best answer below.</i>\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )


async def _load_user(message: Message, referral_code: str | None = None):
    user = message.from_user
    async with AsyncSessionLocal() as session:
        public_user, _ = await get_or_create_public_user(
            session, user.id, user.username, user.full_name, referral_code=referral_code
        )
        await session.commit()
        await session.refresh(public_user)
        return public_user


async def _send_registration(message: Message, challenge: Challenge | None, user) -> None:
    context = "the active RDP security challenge" if challenge else "the Upgrade Team community"
    await message.answer(
        "<b>Welcome to Upgrade Team Challenges</b>\n\n"
        "A public learning and competition space for RDP, VPS and server-security professionals.\n"
        f"To enter {context}, confirm that you want to participate.\n\n"
        "<b>How it works</b>\n"
        "• one verified Telegram identity per person\n"
        "• one answer per challenge\n"
        "• points for correct answers and referrals\n"
        "• fair, transparent leaderboard results\n\n"
        "<i>By joining, you agree to use the challenge only for lawful educational participation. "
        "Never share passwords, tokens or private server access.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=_registration_keyboard(challenge.slug if challenge else ""),
    )


async def _send_challenge(message: Message, challenge: Challenge, public_user) -> bool:
    """Send the challenge question. Re-checks membership as final guard."""
    if _bot is not None:
        allowed, statuses = await check_membership(_bot, message.from_user.id)
        if not allowed:
            await send_gate(message, statuses)
            return False
    async with AsyncSessionLocal() as session:
        current_user = await session.scalar(
            select(PublicUser).where(PublicUser.telegram_id == message.from_user.id)
        )
        if current_user is None or current_user.terms_accepted_at is None:
            await _send_registration(message, challenge, public_user)
            return False
        participant = await register_participant(
            session,
            challenge,
            message.from_user.id,
            message.from_user.username,
            message.from_user.full_name,
            public_user=current_user,
        )
    await message.answer(
        _challenge_text(challenge),
        parse_mode=ParseMode.HTML,
        reply_markup=_answer_keyboard(challenge.slug, challenge.answers)
        if not participant.answer_submitted
        else None,
    )
    return True


# ── command handlers ───────────────────────────────────────────────────────

@router.message(CommandStart())
async def start(message: Message):
    # STEP 1: membership gate — always the very first action
    if not await _require_membership(message):
        return

    # STEP 2: parse deep-link payload
    args = (message.text or "").split(maxsplit=1)
    payload = args[1].strip() if len(args) > 1 else ""
    referral_code = payload.removeprefix("ref_") if payload.startswith("ref_") else None
    slug = payload.removeprefix("challenge_") if payload.startswith("challenge_") else ""

    # STEP 3: load / create user
    user = await _load_user(message, referral_code=referral_code)

    # STEP 4: determine what to show
    async with AsyncSessionLocal() as session:
        challenge = (
            await session.scalar(
                select(Challenge).where(Challenge.slug == slug, Challenge.language == "en")
            )
            if slug
            else await get_active_challenge(session)
        )
        already_joined = (
            await session.scalar(
                select(ChallengeParticipant.id).where(
                    ChallengeParticipant.challenge_id == challenge.id,
                    ChallengeParticipant.telegram_id == message.from_user.id,
                )
            )
            if challenge and challenge.status == "active"
            else None
        )

    if user.terms_accepted_at is None:
        await _send_registration(
            message, challenge if challenge and challenge.status == "active" else None, user
        )
        return

    if not challenge or challenge.status != "active":
        await message.answer(
            "<b>Upgrade Team Challenges</b>\n\n"
            "There is no active challenge right now. Your profile is ready and you will be "
            "notified when the next RDP challenge opens.",
            parse_mode=ParseMode.HTML,
            reply_markup=_profile_keyboard(),
        )
        return

    if already_joined:
        await message.answer(
            "<b>You are already registered for the active challenge.</b>\n\n"
            "Use the panel below to open the challenge or view your profile.",
            parse_mode=ParseMode.HTML,
            reply_markup=_profile_keyboard(),
        )
        return

    await _send_challenge(message, challenge, user)


@router.message(Command("leaderboard"))
async def show_leaderboard(message: Message):
    if not await _require_membership(message):
        return
    async with AsyncSessionLocal() as session:
        challenge = await get_active_challenge(session)
        if not challenge:
            await message.answer("There is no active challenge right now.")
            return
        rows = await leaderboard(session, challenge.id)
    lines = ["🏆 <b>UPGRADE TEAM LEADERBOARD</b>", ""]
    for i, row in enumerate(rows, 1):
        name = (row.username and f"@{row.username}") or row.display_name or "Participant"
        lines.append(f"<b>{i}.</b> {escape(name)}  ·  {row.points} points")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@router.message(Command("profile"))
async def show_profile(message: Message):
    if not await _require_membership(message):
        return
    user = await _load_user(message)
    if user.terms_accepted_at is None:
        await _send_registration(message, None, user)
        return
    await message.answer(
        "<b>Your Challenge Profile</b>\n\n"
        f"Name: {escape(user.display_name or 'Participant')}\n"
        f"Total points: <b>{user.total_points}</b>\n"
        f"Correct answers: <b>{user.correct_answers}/{user.challenge_count}</b>\n"
        f"Invited participants: <b>{user.referral_count}</b>\n"
        f"Referral points: <b>{user.referral_points}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=_profile_keyboard(),
    )


@router.message(Command("referral"))
async def show_referral(message: Message):
    if not await _require_membership(message):
        return
    user = await _load_user(message)
    link = public_referral_link(user.referral_code, get_public_bot_username())
    await message.answer(
        "<b>Invite & learn together</b>\n\n"
        f"<code>{escape(link)}</code>\n\n"
        f"You receive {settings.CHALLENGE_REFERRAL_POINTS} points when a new participant "
        "confirms registration.",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("challenges"))
async def challenge_help(message: Message):
    if not await _require_membership(message):
        return
    await message.answer(
        "<b>UPGRADE TEAM CHALLENGES</b>\n\n"
        "Open the latest challenge link from our channel and select one answer.\n"
        "Each participant gets one attempt. Results are based on correctness and response time.\n\n"
        "View the leaderboard: /leaderboard",
        parse_mode=ParseMode.HTML,
    )


# ── callback handlers ──────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("terms_accept"))
async def accept_terms_callback(callback: CallbackQuery):
    if not await _require_membership_cb(callback):
        return
    parts = (callback.data or "").split(":", 1)
    slug = parts[1] if len(parts) == 2 and parts[1] else ""
    user = callback.from_user
    async with AsyncSessionLocal() as session:
        public_user, _ = await get_or_create_public_user(
            session, user.id, user.username, user.full_name
        )
        await accept_terms(session, public_user)
        challenge = (
            await session.scalar(
                select(Challenge).where(Challenge.slug == slug, Challenge.language == "en")
            )
            if slug
            else await get_active_challenge(session)
        )
    await callback.answer("Registration confirmed.")
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        if challenge and challenge.status == "active":
            await _send_challenge(callback.message, challenge, public_user)
        else:
            await callback.message.answer(
                "Your profile is active. There is no live challenge at the moment.",
                parse_mode=ParseMode.HTML,
                reply_markup=_profile_keyboard(),
            )


@router.callback_query(F.data == "challenge_help")
async def challenge_help_callback(callback: CallbackQuery):
    if not await _require_membership_cb(callback):
        return
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "<b>Upgrade Team Challenge Rules</b>\n\n"
            "Read the scenario, choose one answer, and learn from the explanation. "
            "Correct answers earn 10 points. Inviting a real participant who confirms "
            f"registration earns {settings.CHALLENGE_REFERRAL_POINTS} referral points. "
            "One Telegram identity can answer each challenge once.",
            parse_mode=ParseMode.HTML,
        )


@router.callback_query(F.data == "active_challenge")
async def active_challenge_callback(callback: CallbackQuery):
    if not await _require_membership_cb(callback):
        return
    await callback.answer()
    if not callback.message:
        return
    async with AsyncSessionLocal() as session:
        public_user = await session.scalar(
            select(PublicUser).where(PublicUser.telegram_id == callback.from_user.id)
        )
        challenge = await get_active_challenge(session)
    if public_user is None or public_user.terms_accepted_at is None:
        await _send_registration(callback.message, challenge, public_user)
    elif challenge is None:
        await callback.message.answer(
            "There is no active challenge right now. Please check back soon.",
            reply_markup=_profile_keyboard(),
        )
    else:
        await _send_challenge(callback.message, challenge, public_user)


@router.callback_query(F.data == "my_referral")
async def referral_callback(callback: CallbackQuery):
    if not await _require_membership_cb(callback):
        return
    user = callback.from_user
    async with AsyncSessionLocal() as session:
        public_user, _ = await get_or_create_public_user(
            session, user.id, user.username, user.full_name
        )
        await session.commit()
    link = public_referral_link(public_user.referral_code, get_public_bot_username())
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "<b>Your invitation link</b>\n\n"
            f"<code>{escape(link)}</code>\n\n"
            "Share it with people who genuinely want to learn about RDP and VPS security. "
            "Your stats update after a new participant confirms registration.\n\n"
            f"Invited participants: <b>{public_user.referral_count}</b>\n"
            f"Referral points: <b>{public_user.referral_points}</b>",
            parse_mode=ParseMode.HTML,
        )


@router.callback_query(F.data.startswith("challenge:"))
async def answer(callback: CallbackQuery):
    if not await _require_membership_cb(callback):
        return
    try:
        _, slug, raw_index = callback.data.split(":", 2)
        answer_index = int(raw_index)
    except (AttributeError, ValueError):
        await callback.answer("Invalid answer. Please try again.", show_alert=True)
        return
    async with AsyncSessionLocal() as session:
        challenge = await session.scalar(select(Challenge).where(Challenge.slug == slug))
        if not challenge or challenge.status != "active":
            await callback.answer("This challenge has ended.", show_alert=True)
            return
        if challenge.language != "en":
            await callback.answer("This challenge is no longer available.", show_alert=True)
            return
        public_user, _ = await get_or_create_public_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.full_name,
        )
        if public_user.terms_accepted_at is None:
            await callback.answer(
                "Please confirm registration with /start first.", show_alert=True
            )
            return
        participant = await register_participant(
            session,
            challenge,
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.full_name,
            public_user=public_user,
        )
        if participant.answer_submitted:
            await callback.answer(
                "You have already answered this challenge.", show_alert=True
            )
            return
        correct = await submit_answer(session, challenge, participant, answer_index)
        await callback.answer(
            "Correct answer — 10 points earned!"
            if correct
            else "Not quite. Keep learning and try the next challenge!",
            show_alert=True,
        )
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            (
                "✅ <b>Answer recorded.</b>\n\n"
                f"<b>Why:</b> {escape(challenge.learning_note or 'Review the correct option and apply the principle to your own environment.')}\n\n"
                "View the current leaderboard with /leaderboard."
            )
            if correct
            else "✅ <b>Answer recorded.</b> Watch for the next Upgrade Team challenge.",
            parse_mode=ParseMode.HTML,
        )


@router.callback_query(F.data == "fsub_verify")
async def fsub_verify_callback(callback: CallbackQuery):
    """User tapped '✅ Verify Membership' — invalidate cache and re-check."""
    if _bot is None:
        await callback.answer("The bot is not ready yet. Please wait a moment.", show_alert=True)
        return

    # Force a fresh Telegram API call by clearing the cache first
    invalidate_cache(callback.from_user.id)
    allowed, statuses = await check_membership(_bot, callback.from_user.id)

    if not allowed:
        await callback.answer("You have not joined all required channels yet. ❌", show_alert=True)
        if callback.message:
            try:
                text, kb = build_gate_message(statuses)
                await callback.message.edit_text(
                    text, parse_mode=ParseMode.HTML, reply_markup=kb
                )
            except Exception:
                await send_gate(callback.message, statuses)
        return

    # All channels joined ✅
    await callback.answer("✅ Membership verified!", show_alert=False)
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.answer(
            "<b>Membership verified ✅</b>\n\n"
            "You can now use the bot. Type /start to begin.",
            parse_mode=ParseMode.HTML,
        )


@router.callback_query(F.data == "show_leaderboard")
async def show_leaderboard_callback(callback: CallbackQuery):
    # FIX: previously called show_leaderboard(callback.message) which checked
    # callback.message.from_user.id (the BOT's ID) instead of the real user's ID,
    # effectively bypassing the membership gate entirely.
    if not await _require_membership_cb(callback):
        return
    await callback.answer()
    if not callback.message:
        return
    async with AsyncSessionLocal() as session:
        challenge = await get_active_challenge(session)
        if not challenge:
            await callback.message.answer("There is no active challenge right now.")
            return
        rows = await leaderboard(session, challenge.id)
    lines = ["🏆 <b>UPGRADE TEAM LEADERBOARD</b>", ""]
    for i, row in enumerate(rows, 1):
        name = (row.username and f"@{row.username}") or row.display_name or "Participant"
        lines.append(f"<b>{i}.</b> {escape(name)}  ·  {row.points} points")
    await callback.message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


# ── chat member update handler (leave detection) ───────────────────────────

@router.chat_member()
async def on_chat_member_updated(event: ChatMemberUpdated) -> None:
    """Detect when a user leaves one of the required channels.

    Telegram sends chat_member updates to the bot only when the bot is an
    admin of the channel.  If the bot is not admin, these events are silently
    skipped and the 60-second cache TTL acts as the fallback.

    When a leave IS detected:
    1. The user's membership cache is immediately invalidated.
    2. A lock message is sent to the user so they know they lost access.
    """
    # Only care about actual users leaving/being kicked — ignore joins and bot changes
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    left_statuses = {"left", "kicked", "banned"}

    if new_status not in left_statuses or old_status in left_statuses:
        # Not a leave event (e.g. join, admin change, etc.)
        return

    user = event.new_chat_member.user
    if user.is_bot:
        return

    # Check if this channel is one of the required ones
    required_raw = (settings.REQUIRED_CHANNELS or "").strip()
    if not required_raw:
        return

    required_channels = [c.strip() for c in required_raw.split(",") if c.strip()]
    event_chat_id = str(event.chat.id)
    event_chat_username = f"@{event.chat.username}" if event.chat.username else None

    is_required = any(
        ch == event_chat_id or (event_chat_username and ch == event_chat_username)
        for ch in required_channels
    )

    if not is_required:
        return

    # Invalidate cache immediately so the next bot interaction re-checks membership
    invalidate_cache(user.id)
    logger.info(
        "force_sub_user_left_channel",
        user_id=user.id,
        chat_id=event.chat.id,
        chat_username=event.chat.username,
    )

    # Notify the user that they lost access
    if _bot is not None:
        try:
            _, statuses = await check_membership(_bot, user.id)
            text, kb = build_gate_message(statuses)
            lock_notice = (
                "⛔ <b>Bot access revoked</b>\n\n"
                "You have left one of the required channels.\n"
                "To use the bot again, please rejoin and then type /start.\n\n"
            )
            await _bot.send_message(
                user.id,
                lock_notice + text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        except Exception as exc:
            # User may have blocked the bot — log and move on
            logger.warning(
                "force_sub_leave_notify_failed",
                user_id=user.id,
                error=str(exc),
            )


# ── bot lifecycle ──────────────────────────────────────────────────────────

async def _run_polling(bot: Bot, dispatcher: Dispatcher) -> None:
    while True:
        try:
            await dispatcher.start_polling(
                bot,
                allowed_updates=["message", "callback_query", "chat_member"],
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("public_bot_polling_failed", error=str(exc))
            await asyncio.sleep(5)


async def setup_public_bot() -> None:
    global _bot, _dispatcher, _username, _polling_task
    if not settings.public_bot_token:
        logger.warning("public_bot_token_not_set")
        return
    _bot = Bot(
        token=settings.public_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    _dispatcher = Dispatcher(storage=MemoryStorage())
    _dispatcher.include_router(router)
    try:
        me = await _bot.get_me()
        _username = me.username
    except Exception as exc:
        logger.error("public_bot_identity_failed", error=str(exc))
    webhook_url = (
        os.environ.get("WEBHOOK_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    )
    if webhook_url:
        url = webhook_url.rstrip("/") + "/tg-api/public-bot/webhook"
        try:
            await _bot.set_webhook(
                url=url,
                drop_pending_updates=False,
                allowed_updates=["message", "callback_query", "chat_member"],
            )
            logger.info("public_bot_webhook_set", url=url)
            return
        except Exception as exc:
            logger.error("public_bot_webhook_failed_falling_back_polling", error=str(exc))
    try:
        await _bot.delete_webhook(drop_pending_updates=False)
        logger.info("public_bot_webhook_cleared_for_polling")
    except Exception as exc:
        logger.warning("public_bot_webhook_clear_failed", error=str(exc))
    _polling_task = asyncio.create_task(_run_polling(_bot, _dispatcher))
    logger.info("public_bot_polling_started")


async def process_update(update_data: dict) -> None:
    if not _bot or not _dispatcher:
        return
    try:
        from aiogram.types import Update

        update = Update.model_validate(update_data)
        await _dispatcher.feed_update(_bot, update)
    except Exception as exc:
        logger.error("public_bot_update_processing_failed", error=str(exc))


async def shutdown_public_bot() -> None:
    global _polling_task
    if _polling_task:
        _polling_task.cancel()
        try:
            await _polling_task
        except asyncio.CancelledError:
            pass
        _polling_task = None
    if _bot:
        try:
            await _bot.session.close()
        except Exception as exc:
            logger.error("public_bot_shutdown_failed", error=str(exc))
