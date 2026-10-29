from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.core.config import settings
from app.core.logging import get_logger
from app.services.growth.publishing import list_growth_channel_statuses
from app.services.growth.service import (
    cancel_growth_round,
    growth_status,
    list_pending_growth_deliveries,
    mark_growth_delivery_delivered,
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
        text = "The Growth bot is not running. Check GROWTH_BOT_TOKEN."
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


@router.message(Command("growth_status"))
async def growth_status_command(message: Message):
    result = await growth_status()
    if result["status"] == "none":
        await message.answer(
            "No Growth Challenge rounds yet. The next round will publish on schedule.\n"
            f"Pending manual deliveries: {result['pending_deliveries']}.",
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
        f"Pending manual deliveries: {result['pending_deliveries']}\n"
        f"Delivered winners: {result['delivered_winners']}\n"
        f"Next round: {next_at}",
        parse_mode=None,
    )


@router.message(Command("growth_channels"))
async def growth_channels_command(message: Message):
    rows = await list_growth_channel_statuses()
    if not rows:
        await message.answer("No channel publish records are available yet.", parse_mode=None)
        return
    lines = ["Growth channel publish status:"]
    for row in rows[:60]:
        state = "active" if row["active"] else "disabled"
        details = f"{row['status'] or 'unknown'} at {row['step'] or '—'}"
        if row["error"]:
            details += f" — {row['error'][:140]}"
        lines.append(f"{row['channel_id']}: {state}; {details}")
    await message.answer("\n".join(lines), parse_mode=None)


@router.message(Command("growth_pending_deliveries"))
async def growth_pending_deliveries_command(message: Message):
    winners = await list_pending_growth_deliveries(limit=100)
    if not winners:
        await message.answer("There are no pending Growth Challenge deliveries.", parse_mode=None)
        return
    messages = []
    lines = ["Pending Growth Challenge deliveries:"]
    for winner in winners:
        username = f"@{winner['username']}" if winner["username"] else "no username"
        line = (
            f"{username} (ID {winner['telegram_user_id']})\n"
            f"Round: {winner['round_id']}\nWinner ID: {winner['id']}"
        )
        if len("\n\n".join(lines + [line])) > 3500:
            messages.append("\n\n".join(lines))
            lines = ["Pending Growth Challenge deliveries (continued):"]
        lines.append(line)
    lines.append("Mark one delivered with /growth_mark_delivered <winner-id>.")
    messages.append("\n\n".join(lines))
    for text in messages:
        await message.answer(text, parse_mode=None)


@router.message(Command("growth_mark_delivered"))
async def growth_mark_delivered_command(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Usage: /growth_mark_delivered <winner-id>",
            parse_mode=None,
        )
        return
    result = await mark_growth_delivery_delivered(parts[1].strip(), message.from_user.id)
    if result["status"] == "delivered":
        text = f"Winner marked delivered for round {result['round_id']}."
    elif result["status"] == "already_delivered":
        text = f"That winner was already marked delivered for round {result['round_id']}."
    elif result["status"] == "missing":
        text = "No winner matches that ID."
    elif result["status"] == "invalid":
        text = "Winner ID must be a valid UUID."
    else:
        text = "That winner is not pending manual delivery."
    await message.answer(text, parse_mode=None)


@router.callback_query(F.data.startswith("growth:"))
async def growth_review_callback(callback: CallbackQuery):
    if not callback.from_user or callback.from_user.id not in settings.admin_ids:
        await callback.answer("Admins only.", show_alert=True)
        return
    try:
        _, action, object_id = callback.data.split(":", 2)
        if action not in {"approve", "reject", "delivered"}:
            raise ValueError("unknown decision")
    except (AttributeError, ValueError):
        await callback.answer("This Growth Challenge button is invalid.", show_alert=True)
        return

    if action == "delivered":
        result = await mark_growth_delivery_delivered(object_id, callback.from_user.id)
        if result["status"] == "delivered":
            await callback.answer("Delivery marked complete.")
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=None)
        elif result["status"] == "already_delivered":
            await callback.answer("This delivery was already marked complete.", show_alert=True)
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=None)
        elif result["status"] == "missing":
            await callback.answer("This winner no longer exists.", show_alert=True)
        else:
            await callback.answer("This delivery is not pending.", show_alert=True)
        return

    entry_id = object_id
    result = await review_growth_entry(
        entry_id,
        callback.from_user.id,
        approve=action == "approve",
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
