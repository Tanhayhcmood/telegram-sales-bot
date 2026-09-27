from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from app.core.config import settings
from app.core.logging import get_logger
from typing import Callable, Dict, Any, Awaitable

logger = get_logger(__name__)

# Commands that bypass admin check — anyone can use them
_PUBLIC_COMMANDS = {"/myid"}


class AdminOnlyMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, (Message, CallbackQuery)):
            user = event.from_user

        if not user:
            return

        # Allow public commands to pass through without admin check
        if isinstance(event, Message) and event.text:
            cmd = event.text.split()[0].split("@")[0].lower()
            if cmd in _PUBLIC_COMMANDS:
                data["admin_id"] = None
                return await handler(event, data)

        admin_ids = settings.admin_ids
        if user.id not in admin_ids:
            logger.warning(
                "unauthorized_admin_access",
                user_id=user.id,
                username=user.username,
                admin_ids_configured=admin_ids,
            )
            if isinstance(event, Message):
                try:
                    await event.answer(
                        f"⛔ Unauthorized.\n\n"
                        f"Your Telegram ID: `{user.id}`\n"
                        f"Send /myid to see your ID, then update "
                        f"`ADMIN_TELEGRAM_IDS` on Render.",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
            elif isinstance(event, CallbackQuery):
                try:
                    await event.answer("⛔ Unauthorized.", show_alert=True)
                except Exception:
                    pass
            return

        data["admin_id"] = user.id
        return await handler(event, data)
