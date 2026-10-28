import hashlib
import json

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.core.config import settings
from app.core.logging import get_logger
from app.services.admin_bot.bot import get_bot as get_admin_bot
from app.services.growth.service import (
    record_admin_notification,
    refresh_growth_post,
    submit_growth_proof,
)

logger = get_logger(__name__)
router = Router()


def _message_file(message: Message) -> tuple[str | None, str | None, bool]:
    if message.photo:
        photo = message.photo[-1]
        return photo.file_id, photo.file_unique_id, True
    if message.document:
        is_image = bool(message.document.mime_type and message.document.mime_type.startswith("image/"))
        return message.document.file_id, message.document.file_unique_id, is_image
    for attr in ("video", "animation", "audio", "voice", "video_note"):
        item = getattr(message, attr, None)
        if item:
            return item.file_id, item.file_unique_id, False
    return None, None, False


async def _proof_hash(message: Message) -> tuple[str | None, str | None, str | None]:
    file_id, file_unique_id, is_image = _message_file(message)
    if file_id:
        try:
            file = await message.bot.get_file(file_id)
            data = await message.bot.download_file(file.file_path)
            if hasattr(data, "read"):
                data = data.read()
            if isinstance(data, bytes) and data:
                return hashlib.sha256(data).hexdigest(), file_id, "screenshot" if is_image else "forwarded"
        except Exception as exc:
            logger.warning(
                "growth_proof_file_hash_failed",
                user_id=message.from_user.id if message.from_user else None,
                error=str(exc)[:180],
            )
        if file_unique_id:
            return hashlib.sha256(file_unique_id.encode("utf-8")).hexdigest(), file_id, (
                "screenshot" if is_image else "forwarded"
            )

    origin = getattr(message, "forward_origin", None)
    if origin:
        try:
            canonical_origin = json.dumps(
                origin.model_dump(mode="json", exclude_none=True),
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        except Exception:
            canonical_origin = str(origin)
        content = "\n".join(
            part for part in (canonical_origin, message.text or "", message.caption or "") if part
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest(), None, "forwarded"
    return None, None, None


def _review_keyboard(entry_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Approve", callback_data=f"growth:approve:{entry_id}"),
                InlineKeyboardButton(text="Reject", callback_data=f"growth:reject:{entry_id}"),
            ]
        ]
    )


async def _notify_admins(message: Message, entry: dict) -> None:
    admin_bot = get_admin_bot()
    if not admin_bot:
        logger.error("growth_review_admin_bot_unavailable", entry_id=entry["entry_id"])
        return
    user = message.from_user
    username = f"@{user.username}" if user and user.username else "no username"
    header = (
        "Growth Challenge proof\n"
        f"User: {username} (ID {user.id})\n"
        f"Entry: {entry['entry_id']}\n"
        f"Proof type: {entry['proof_type']}"
    )
    for admin_id in settings.admin_ids:
        try:
            proof_copied = False
            try:
                notice = await admin_bot.copy_message(
                    chat_id=admin_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                    reply_markup=_review_keyboard(entry["entry_id"]),
                )
                proof_copied = True
            except Exception as copy_exc:
                logger.warning(
                    "growth_proof_copy_to_admin_failed",
                    entry_id=entry["entry_id"],
                    admin_id=admin_id,
                    error=str(copy_exc)[:180],
                )
                notice = await admin_bot.send_message(
                    chat_id=admin_id,
                    text=header,
                    reply_markup=_review_keyboard(entry["entry_id"]),
                    parse_mode=None,
                )
            still_pending = await record_admin_notification(
                entry["entry_id"], admin_id, notice.message_id
            )
            if not still_pending:
                try:
                    await admin_bot.edit_message_reply_markup(
                        chat_id=admin_id,
                        message_id=notice.message_id,
                        reply_markup=None,
                    )
                except Exception:
                    pass
            if proof_copied:
                try:
                    await admin_bot.send_message(chat_id=admin_id, text=header, parse_mode=None)
                except Exception as exc:
                    logger.warning(
                        "growth_admin_proof_context_failed",
                        entry_id=entry["entry_id"],
                        admin_id=admin_id,
                        error=str(exc)[:180],
                    )
        except Exception as exc:
            logger.warning(
                "growth_admin_proof_notification_failed",
                entry_id=entry["entry_id"],
                admin_id=admin_id,
                error=str(exc)[:180],
            )


@router.message(F.chat.type == "private")
async def receive_growth_proof(message: Message) -> None:
    if not message.from_user or message.from_user.is_bot:
        return
    is_forwarded = bool(getattr(message, "forward_origin", None))
    file_id, _, is_image = _message_file(message)
    if not ((file_id and is_image) or is_forwarded):
        return

    proof_hash, proof_file_id, proof_type = await _proof_hash(message)
    if not proof_hash or not proof_type:
        await message.answer(
            "I couldn't read that proof. Please send a screenshot or forward the original message again.",
            parse_mode=None,
        )
        return

    result = await submit_growth_proof(
        telegram_user_id=message.from_user.id,
        username=message.from_user.username,
        source_chat_id=message.chat.id,
        source_message_id=message.message_id,
        proof_type=proof_type,
        proof_hash=proof_hash,
        proof_file_id=proof_file_id,
    )
    if result["status"] == "closed":
        await message.answer("There is no open Growth Challenge round right now.", parse_mode=None)
        return
    if result["status"] == "duplicate":
        await message.answer("That proof was already submitted. Please send a different proof.", parse_mode=None)
        return
    if result["status"] == "limit":
        await message.answer("You have already used all three proof submissions for this round.", parse_mode=None)
        return

    await message.answer(
        f"Proof received and sent for admin review. You have {result['remaining']} submission"
        f"{'' if result['remaining'] == 1 else 's'} left this round.",
        parse_mode=None,
    )
    await _notify_admins(message, {**result, "proof_type": proof_type})
    await refresh_growth_post(result["round_id"])
