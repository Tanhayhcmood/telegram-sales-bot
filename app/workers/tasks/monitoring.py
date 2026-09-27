from app.services.monitoring.alerting import check_system_thresholds, send_alert
from app.services.monitoring.metrics_collector import collect_system_metrics, increment_daily_stat
from app.services.monitoring.health import full_health_check
from app.core.logging import get_logger
from app.cache.redis_client import cache_get, cache_set
from datetime import date

logger = get_logger(__name__)

HEALTH_STATUS_KEY = "system:last_health_status"


async def task_system_health_check(ctx) -> dict:
    try:
        health = await full_health_check()
        status = health["status"]

        last_status = await cache_get(HEALTH_STATUS_KEY)

        if status == "critical":
            await send_alert(
                "critical", "system",
                f"System health CRITICAL: {_format_failed_services(health)}",
                {"services": health.get("services", {})},
            )
        elif status == "degraded" and last_status == "ok":
            await send_alert(
                "warning", "system",
                f"System health degraded: {_format_failed_services(health)}",
                {"services": health.get("services", {})},
            )
        elif status == "ok" and last_status in ("critical", "degraded"):
            await send_alert(
                "success", "system",
                "System health restored to OK ✅",
                cooldown=False,
            )

        await cache_set(HEALTH_STATUS_KEY, status, ttl=3600)
        return health
    except Exception as e:
        logger.error("health_check_task_failed", error=str(e))
        return {"status": "error", "error": str(e)}


async def task_collect_metrics(ctx) -> dict:
    try:
        metrics = await collect_system_metrics()
        await check_system_thresholds()
        await increment_daily_stat("ai_calls", 0)
        return {"status": "ok", "cpu": metrics["cpu_percent"], "ram": metrics["ram"]["percent"]}
    except Exception as e:
        logger.error("metrics_task_failed", error=str(e))
        return {"status": "error", "error": str(e)}


def _format_failed_services(health: dict) -> str:
    failed = [
        name for name, status in health.get("services", {}).items()
        if status.get("status") != "ok"
    ]
    return ", ".join(failed) if failed else "unknown"
