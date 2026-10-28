from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.core.config import settings
from app.core.logging import get_logger
from app.services.growth.service import (
    add_growth_prize,
    cancel_growth_round,
    growth_prize_pool_count,
    growth_status,
    refresh_growth_post,
    review_growth_entry,
    start_growth_round,
)

logger = get_logger(__name__)
router = Router()


def _review_keyboard(entry_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Approve", callback_data=f"growth:approve:{entry_id}"),
                InlineKeyboardButton(text="Reject", callback_data=f"growth:reject:{entry_id}"),
            ]
        ]
    )


@router.message(Command("growth_start"))
async def growth_start_command(message: Message):
    status = await message.answer("Starting a Growth Challenge round…", parse_mode=None)
    result = await start_growth_round()
    if result["status"] == "open":
        text = (
            f"Round is live ({result['challenge_type']}).\n"
            f"Published to {result['published']}/{result['total']} configured channels."
        )
    elif result["status"] == "active":
        text = f"A round is already active. Round ID: {result.get('round_id', 'available in /growth_status')}."
    elif result["status"] == "no_channels":
        text = "No active channels or REQUIRED_CHANNELS are configured."
    elif result["status"] == "bot_unavailable":
        text = "The public challenge bot is not running. Check TELEGRAM_PUBLIC_BOT_TOKEN."
    elif result["status"] == "no_prizes":
        text = "Add at least one RDP or VPS prize with /growth_add_prize before starting a round."
    elif result["status"] == "prize_key_invalid":
        text = "The prize encryption key is missing, invalid, or cannot decrypt the available pool."
    elif result["status"] == "admin_bot_unavailable":
        text = "The admin bot is unavailable. Check ADMIN_BOT_TOKEN before starting a round."
    else:
        text = f"Could not start the round ({result['status']}). Check the application logs."
    await status.edit_text(text, parse_mode=None)


@router.message(Command("growth_cancel"))
async def growth_cancel_command(message: Message):
    result = await cancel_growth_round()
    if result["status"] == "cancelled":
        await message.answer(
            f"Growth round {result['round_id']} was cancelled. The next automatic round remains on its 9-hour schedule.",
            parse_mode=None,
        )
    else:
        await message.answer("There is no active Growth Challenge round to cancel.", parse_mode=None)


@router.message(Command("growth_add_prize"))
async def growth_add_prize_command(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or "|" not in parts[1]:
        await message.answer(
            "Usage: /growth_add_prize RDP | prize details\n"
            "Use VPS instead of RDP for a VPS prize. Details are encrypted before storage.",
            parse_mode=None,
        )
        return
    kind, _, payload = parts[1].partition("|")
    result = await add_growth_prize(kind, payload)
    if result["status"] == "added":
        await message.answer(
            f"{result['kind']} prize added to the encrypted pool. Available prizes: "
            f"{await growth_prize_pool_count()}.",
            parse_mode=None,
        )
    elif result["status"] == "encryption_not_configured":
        await message.answer(
            "Prize storage is disabled until GROWTH_PRIZE_ENCRYPTION_KEY is configured.",
            parse_mode=None,
        )
    elif result["status"] == "invalid_kind":
        await message.answer("Prize type must be RDP or VPS.", parse_mode=None)
    else:
        await message.answer("Prize details cannot be empty.", parse_mode=None)


@router.message(Command("growth_prizes"))
async def growth_prizes_command(message: Message):
    count = await growth_prize_pool_count()
    await message.answer(f"Available encrypted prizes: {count}.", parse_mode=None)


@router.message(Command("growth_status"))
async def growth_status_command(message: Message):
    result = await growth_status()
    if result["status"] == "none":
        await message.answer(
            f"No Growth Challenge rounds yet. Available prizes: {result['prizes']}.",
            parse_mode=None,
        )
        return
    started = result["started_at"].strftime("%Y-%m-%d %H:%M UTC")
    closes = result["entries_close_at"].strftime("%Y-%m-%d %H:%M UTC")
    next_at = result["next_round_at"].strftime("%Y-%m-%d %H:%M UTC")
    await message.answer(
        f"Growth Challenge status: {result['status']}\n"
        f"Round: {result['round_id']}\n"
        f"Type: {result['challenge_type']}\n"
        f"Started: {started}\n"
        f"Entries close: {closes}\n"
        f"Submitted: {result['submitted']} (pending {result['pending']}, "
        f"approved {result['approved']}, rejected {result['rejected']})\n"
        f"Winners delivered: {result['delivered_winners']}\n"
        f"Available prizes: {result['prizes']}\n"
        f"Next round: {next_at}",
        parse_mode=None,
    )


@router.callback_query(F.data.startswith("growth:"))
async def growth_review_callback(callback: CallbackQuery):
    if not callback.from_user or callback.from_user.id not in settings.admin_ids:
        await callback.answer("Admins only.", show_alert=True)
        return
    try:
        _, decision, entry_id = callback.data.split(":", 2)
        if decision not in {"approve", "reject"}:
            raise ValueError("unknown decision")
    except (AttributeError, ValueError):
        await callback.answer("This review button is invalid.", show_alert=True)
        return

    result = await review_growth_entry(
        entry_id,
        callback.from_user.id,
        approve=decision == "approve",
    )
    await callback.answer(
        "Decision recorded." if result["status"] in {"approved", "rejected"}
        else "This entry has already been reviewed." if result["status"] == "already_reviewed"
        else "This round is closed.",
        show_alert=result["status"] not in {"approved", "rejected"},
    )
    for notice in result.get("notifications", []):
        try:
            await callback.bot.edit_message_reply_markup(
                chat_id=notice["chat_id"],
                message_id=notice["message_id"],
                reply_markup=None,
            )
        except Exception as exc:
            logger.warning(
                "growth_review_button_disable_failed",
                entry_id=entry_id,
                chat_id=notice.get("chat_id"),
                message_id=notice.get("message_id"),
                error=str(exc)[:160],
            )

    if result["status"] in {"approved", "rejected"}:
        if callback.bot:
            text = (
                "Your proof was approved and will be included in the winner draw."
                if result["status"] == "approved"
                else "Your proof was not approved. You can submit another proof while entries are open."
            )
            try:
                await callback.bot.send_message(
                    chat_id=result["telegram_user_id"],
                    text=text,
                    parse_mode=None,
                )
            except Exception as exc:
                logger.warning(
                    "growth_review_result_dm_failed",
                    entry_id=entry_id,
                    user_id=result["telegram_user_id"],
                    error=str(exc)[:180],
                )
        await refresh_growth_post(result["round_id"])
