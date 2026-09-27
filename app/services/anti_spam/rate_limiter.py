from app.cache.redis_client import cache_incr, cache_get_int
from app.cache.keys import CacheKeys
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def check_rate_limit(user_id: int) -> tuple[bool, str]:
    minute_key = CacheKeys.rate_minute(user_id)
    hour_key = CacheKeys.rate_hour(user_id)

    minute_count = await cache_incr(minute_key, ttl=60)
    hour_count = await cache_incr(hour_key, ttl=3600)

    if minute_count > settings.SPAM_MAX_MESSAGES_PER_MINUTE:
        logger.warning("rate_limit_exceeded_minute", user_id=user_id, count=minute_count)
        return False, "minute"

    if hour_count > settings.SPAM_MAX_MESSAGES_PER_HOUR:
        logger.warning("rate_limit_exceeded_hour", user_id=user_id, count=hour_count)
        return False, "hour"

    return True, ""


async def get_message_counts(user_id: int) -> dict:
    minute_count = await cache_get_int(CacheKeys.rate_minute(user_id))
    hour_count = await cache_get_int(CacheKeys.rate_hour(user_id))
    return {"per_minute": minute_count, "per_hour": hour_count}
