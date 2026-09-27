from app.cache.redis_client import get_redis
from app.db.base import engine
from app.services.ai.engine import check_ai_health
from app.core.config import settings
from app.core.logging import get_logger
from sqlalchemy import text
import asyncio

logger = get_logger(__name__)


async def check_database() -> dict:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        logger.error("db_health_failed", error=str(e))
        return {"status": "error", "error": str(e)}


async def check_redis() -> dict:
    try:
        r = await get_redis()
        await r.ping()
        return {"status": "ok"}
    except Exception as e:
        logger.error("redis_health_failed", error=str(e))
        return {"status": "error", "error": str(e)}


async def check_ai() -> dict:
    # AI generation is optional: challenge generation has a safe fallback,
    # so an unset provider must not make the whole service look unhealthy.
    if not (settings.GROQ_API_KEY or settings.OPENAI_API_KEY):
        return {"status": "disabled", "reason": "no_ai_provider_configured"}
    healthy = await check_ai_health()
    return {"status": "ok" if healthy else "error"}


async def full_health_check() -> dict:
    db_task = check_database()
    redis_task = check_redis()
    ai_task = check_ai()

    db_result, redis_result, ai_result = await asyncio.gather(db_task, redis_task, ai_task)

    overall = "ok"
    if any(r.get("status") == "error" for r in [db_result, redis_result]):
        overall = "critical"
    elif ai_result.get("status") == "error":
        overall = "degraded"

    return {
        "status": overall,
        "services": {
            "database": db_result,
            "redis": redis_result,
            "ai": ai_result,
        },
    }
