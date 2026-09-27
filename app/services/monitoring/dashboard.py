from app.services.monitoring.metrics_collector import get_cached_metrics, get_daily_stats
from app.services.monitoring.health import full_health_check
from app.cache.redis_client import cache_get
from app.core.logging import get_logger
import asyncio

logger = get_logger(__name__)


async def get_dashboard_data() -> dict:
    metrics_task = get_cached_metrics()
    health_task = full_health_check()
    stats_task = get_daily_stats()

    metrics, health, stats = await asyncio.gather(metrics_task, health_task, stats_task)

    active_conversations = await cache_get("stats:active_conversations") or 0

    return {
        "system": metrics,
        "health": health,
        "daily_stats": stats,
        "active_conversations": active_conversations,
    }
