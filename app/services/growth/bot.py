import asyncio
import hashlib
import hmac
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_bot: Bot | None = None
_dispatcher: Dispatcher | None = None
_username: str | None = None
_polling_task: asyncio.Task | None = None


def get_growth_bot() -> Bot | None:
    return _bot


def get_growth_bot_username() -> str | None:
    return _username


def _webhook_secret() -> str:
    # Telegram only accepts a restricted character set for secret_token. Derive
    # a stable, valid token from the existing application SECRET_KEY.
    return hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).hexdigest()


def verify_growth_webhook_secret(candidate: str | None) -> bool:
    return bool(candidate) and hmac.compare_digest(candidate, _webhook_secret())


async def setup_growth_bot() -> None:
    global _bot, _dispatcher, _username, _polling_task
    if not settings.GROWTH_BOT_TOKEN:
        logger.warning("growth_bot_token_not_set")
        return
    _bot = Bot(
        token=settings.GROWTH_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    _dispatcher = Dispatcher(storage=MemoryStorage())
    from app.services.growth.public_handlers import router
    _dispatcher.include_router(router)
    me = await _bot.get_me()
    _username = me.username
    logger.info(f"growth bot username=@{_username or 'unknown'}")
    base = os.environ.get("WEBHOOK_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    if base:
        url = base.rstrip("/") + "/tg-api/growth-bot/webhook"
        await _bot.set_webhook(
            url=url,
            secret_token=_webhook_secret(),
            drop_pending_updates=False,
            allowed_updates=["message", "chat_member"],
        )
        logger.info("growth_bot_webhook_set", url=url)
        return
    await _bot.delete_webhook(drop_pending_updates=False)
    _polling_task = asyncio.create_task(
        _bot.get_updates() if False else _dispatcher.start_polling(
            _bot, allowed_updates=["message", "chat_member"]
        )
    )
    logger.info("growth_bot_polling_started")


async def process_update(update_data: dict) -> None:
    if not _bot or not _dispatcher:
        return
    try:
        update = Update.model_validate(update_data)
        await _dispatcher.feed_update(_bot, update)
    except Exception as exc:
        logger.error("growth_bot_update_processing_failed", error=str(exc)[:240])


async def shutdown_growth_bot() -> None:
    global _polling_task, _bot
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
            logger.error("growth_bot_shutdown_failed", error=str(exc)[:160])
        _bot = None
