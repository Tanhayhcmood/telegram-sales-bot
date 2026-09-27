import redis.asyncio as aioredis
from app.core.config import settings
from app.core.logging import get_logger
from typing import Optional, Any
import json
import time as _time

logger = get_logger(__name__)

_redis_client: Optional[aioredis.Redis] = None
_redis_is_real: bool = False          # True when _redis_client is a live server connection
_redis_last_attempt: float = 0.0      # monotonic timestamp of the last connection attempt
_REDIS_RETRY_COOLDOWN: float = 30.0   # seconds between retries when on fakeredis


def _build_redis_kwargs() -> dict:
    kwargs: dict = dict(
        encoding="utf-8",
        decode_responses=True,
        max_connections=50,
        socket_connect_timeout=5,   # up from 2 s — TLS handshake needs breathing room
    )
    # Disable SSL certificate verification for managed TLS Redis endpoints
    # (Render Keyvalue uses internal certs that can fail strict verification)
    url = settings.REDIS_URL or ""
    if url.startswith("rediss://"):
        kwargs["ssl_cert_reqs"] = None
    return kwargs


async def get_redis() -> aioredis.Redis:
    """
    Return a Redis client, preferring a real server connection.

    On first call (or after close_redis()), attempt to connect to the configured
    Redis server.  If that fails, fall back to an in-process FakeRedis instance
    so the app keeps running.

    The fallback is NOT permanent: every 30 s the next call transparently retries
    the real server.  Once the server becomes reachable (e.g. after a cold-start
    TLS handshake settles) all subsequent calls automatically switch over.
    """
    global _redis_client, _redis_is_real, _redis_last_attempt

    # Fast path: already have a working real connection
    if _redis_client is not None and _redis_is_real:
        return _redis_client

    now = _time.monotonic()
    should_attempt = (
        _redis_client is None                                           # very first call
        or (not _redis_is_real and now - _redis_last_attempt >= _REDIS_RETRY_COOLDOWN)
    )

    if not should_attempt:
        # Still within cooldown — return existing fakeredis
        return _redis_client  # type: ignore[return-value]

    _redis_last_attempt = now

    # Render deployments may intentionally omit Redis. Use the in-process
    # fallback directly instead of attempting localhost:6379 and logging a
    # misleading connection-refused error on every cold start.
    if not (settings.REDIS_URL or "").strip():
        import fakeredis.aioredis as fakeredis_mod
        _redis_client = fakeredis_mod.FakeRedis(decode_responses=True)
        _redis_is_real = False
        logger.info("redis_not_configured_using_fakeredis")
        return _redis_client

    try:
        client = aioredis.from_url(settings.REDIS_URL or "", **_build_redis_kwargs())
        await client.ping()
        if _redis_client is not None and not _redis_is_real:
            logger.info("redis_reconnected_real")
        else:
            logger.info("redis_connected")
        _redis_client = client
        _redis_is_real = True
    except Exception as e:
        logger.warning("redis_unavailable_using_fakeredis", error=str(e))
        if _redis_client is None or _redis_is_real:
            # First failure or real connection just dropped — create a fresh fakeredis
            import fakeredis.aioredis as fakeredis_mod
            _redis_client = fakeredis_mod.FakeRedis(decode_responses=True)
            _redis_is_real = False

    return _redis_client  # type: ignore[return-value]


async def close_redis() -> None:
    global _redis_client, _redis_is_real, _redis_last_attempt
    if _redis_client:
        try:
            await _redis_client.aclose()
        except Exception:
            pass
        _redis_client = None
        _redis_is_real = False
        _redis_last_attempt = 0.0


async def cache_set(key: str, value: Any, ttl: int = None) -> None:
    r = await get_redis()
    ttl = ttl or settings.REDIS_CACHE_TTL
    if value is None:
        serialized = "null"
    elif isinstance(value, str):
        serialized = value
    else:
        serialized = json.dumps(value)
    await r.setex(key, ttl, serialized)


async def cache_get(key: str) -> Optional[Any]:
    r = await get_redis()
    value = await r.get(key)
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


async def cache_delete(key: str) -> None:
    r = await get_redis()
    await r.delete(key)


async def cache_delete_pattern(pattern: str) -> int:
    r = await get_redis()
    keys = await r.keys(pattern)
    if keys:
        return await r.delete(*keys)
    return 0


async def cache_incr(key: str, amount: int = 1, ttl: int = 3600) -> int:
    r = await get_redis()
    pipe = r.pipeline()
    if amount == 1:
        pipe.incr(key)
    else:
        pipe.incrby(key, amount)
    pipe.expire(key, ttl)
    results = await pipe.execute()
    return results[0]


async def cache_get_int(key: str) -> int:
    r = await get_redis()
    value = await r.get(key)
    return int(value) if value else 0


async def cache_exists(key: str) -> bool:
    r = await get_redis()
    return bool(await r.exists(key))


async def cache_ttl(key: str) -> int:
    r = await get_redis()
    return await r.ttl(key)
