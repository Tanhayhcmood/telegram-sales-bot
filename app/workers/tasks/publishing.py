from app.db.session import AsyncSessionLocal
from app.services.channel.scheduler import process_scheduled_posts
from app.cache.redis_client import cache_get
from app.core.logging import get_logger

logger = get_logger(__name__)


async def task_process_scheduled_posts(ctx) -> dict:
    paused = await cache_get("system:posting_paused")
    if paused:
        logger.info("posting_paused_skipping")
        return {"status": "paused"}

    try:
        async with AsyncSessionLocal() as session:
            count = await process_scheduled_posts(session)
        logger.info("scheduled_posts_processed", count=count)
        return {"status": "ok", "published": count}
    except Exception as e:
        logger.error("publishing_task_failed", error=str(e))
        return {"status": "error", "error": str(e)}
