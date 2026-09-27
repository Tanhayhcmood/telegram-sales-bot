from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.models.admin import Blacklist
from app.cache.redis_client import cache_set, cache_delete
from app.cache.keys import CacheKeys
from app.core.logging import get_logger
import uuid
from datetime import datetime, timezone

logger = get_logger(__name__)


async def add_to_blacklist(session: AsyncSession, telegram_id: int, reason: str, blocked_by: uuid.UUID = None) -> None:
    existing = await session.execute(select(Blacklist).where(Blacklist.telegram_id == telegram_id))
    if not existing.scalar_one_or_none():
        session.add(Blacklist(telegram_id=telegram_id, reason=reason, blocked_by=blocked_by))
        await session.commit()
    await cache_set(CacheKeys.blacklist(telegram_id), True, ttl=86400 * 30)
    logger.info("user_blacklisted", telegram_id=telegram_id, reason=reason)


async def remove_from_blacklist(session: AsyncSession, telegram_id: int) -> None:
    await session.execute(delete(Blacklist).where(Blacklist.telegram_id == telegram_id))
    await session.commit()
    await cache_delete(CacheKeys.blacklist(telegram_id))
    logger.info("user_unblacklisted", telegram_id=telegram_id)


async def is_blacklisted_db(session: AsyncSession, telegram_id: int) -> bool:
    result = await session.execute(select(Blacklist).where(Blacklist.telegram_id == telegram_id))
    return result.scalar_one_or_none() is not None
