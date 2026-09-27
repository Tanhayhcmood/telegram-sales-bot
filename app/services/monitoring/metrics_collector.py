import psutil
from app.cache.redis_client import cache_set, cache_get, cache_incr
from app.core.logging import get_logger
from datetime import datetime, timezone, date

logger = get_logger(__name__)

METRICS_CACHE_KEY = "system:metrics"
METRICS_TTL = 30


async def collect_system_metrics() -> dict:
    cpu_percent = psutil.cpu_percent(interval=0.5)
    cpu_count = psutil.cpu_count()
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    net = psutil.net_io_counters()
    boot_time = psutil.boot_time()
    uptime_seconds = (datetime.now(timezone.utc).timestamp() - boot_time)

    process = psutil.Process()
    proc_mem = process.memory_info()

    metrics = {
        "cpu_percent": cpu_percent,
        "cpu_count": cpu_count,
        "ram": {
            "total_gb": round(ram.total / (1024 ** 3), 2),
            "used_gb": round(ram.used / (1024 ** 3), 2),
            "available_gb": round(ram.available / (1024 ** 3), 2),
            "percent": ram.percent,
        },
        "disk": {
            "total_gb": round(disk.total / (1024 ** 3), 2),
            "used_gb": round(disk.used / (1024 ** 3), 2),
            "free_gb": round(disk.free / (1024 ** 3), 2),
            "percent": disk.percent,
        },
        "network": {
            "bytes_sent_mb": round(net.bytes_sent / (1024 ** 2), 2),
            "bytes_recv_mb": round(net.bytes_recv / (1024 ** 2), 2),
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        },
        "process": {
            "rss_mb": round(proc_mem.rss / (1024 ** 2), 2),
            "vms_mb": round(proc_mem.vms / (1024 ** 2), 2),
        },
        "uptime_hours": round(uptime_seconds / 3600, 2),
        "uptime_days": round(uptime_seconds / 86400, 2),
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }

    await cache_set(METRICS_CACHE_KEY, metrics, ttl=METRICS_TTL)
    return metrics


async def get_cached_metrics() -> dict:
    cached = await cache_get(METRICS_CACHE_KEY)
    if cached:
        return cached
    return await collect_system_metrics()


async def get_daily_stats() -> dict:
    today = date.today().isoformat()
    base_key = f"stats:daily:{today}"

    keys = [
        "messages_received", "messages_sent", "new_customers",
        "active_conversations", "posts_published", "leads_created",
        "errors", "tokens_used", "followups_sent", "ai_calls",
    ]

    stats = {"date": today}
    for key in keys:
        val = await cache_get(f"{base_key}:{key}")
        stats[key] = int(val) if val else 0

    return stats


async def get_weekly_stats() -> list[dict]:
    from datetime import timedelta
    results = []
    today = date.today()
    for i in range(7):
        day = (today - timedelta(days=i)).isoformat()
        base_key = f"stats:daily:{day}"
        day_stats = {"date": day}
        for key in ["messages_received", "messages_sent", "new_customers", "leads_created"]:
            val = await cache_get(f"{base_key}:{key}")
            day_stats[key] = int(val) if val else 0
        results.append(day_stats)
    return list(reversed(results))


async def increment_daily_stat(key: str, amount: int = 1) -> None:
    today = date.today().isoformat()
    await cache_incr(f"stats:daily:{today}:{key}", amount=amount, ttl=86400 * 2)


async def track_token_cost(tokens: int, model: str = "gpt-4o") -> None:
    cost_per_1k = {"gpt-4o": 0.005, "gpt-4o-mini": 0.00015, "gpt-4": 0.03}
    cost = (tokens / 1000) * cost_per_1k.get(model, 0.005)

    await increment_daily_stat("tokens_used", tokens)
    today = date.today().isoformat()
    await cache_incr(f"stats:daily:{today}:cost_cents", amount=int(cost * 100), ttl=86400 * 2)
