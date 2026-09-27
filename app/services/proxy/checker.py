"""
Proxy liveness checker.

Uses asyncio to attempt a TCP connection through the proxy to
Telegram's IP (149.154.167.51:443).  Returns True if the proxy
is reachable within the timeout.
"""
import asyncio
import socket
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.proxy import Proxy
from app.core.logging import get_logger

logger = get_logger(__name__)

_TELEGRAM_HOST = "149.154.167.51"
_TELEGRAM_PORT = 443
_TIMEOUT = 8.0  # seconds


async def _check_socks5(host: str, port: int, username: Optional[str], password: Optional[str]) -> bool:
    """Open a SOCKS5 tunnel to _TELEGRAM_HOST:_TELEGRAM_PORT."""
    try:
        import socks  # PySocks — installed as PySocks in requirements
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, host, port, True, username or "", password or "")
        s.settimeout(_TIMEOUT)
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: s.connect((_TELEGRAM_HOST, _TELEGRAM_PORT)),
        )
        s.close()
        return True
    except Exception as exc:
        logger.debug("proxy_socks5_check_failed", host=host, port=port, error=str(exc))
        return False


async def _check_http(host: str, port: int, username: Optional[str], password: Optional[str]) -> bool:
    """CONNECT-tunnel check for HTTP proxies."""
    try:
        import socks
        s = socks.socksocket()
        s.set_proxy(socks.HTTP, host, port, True, username or "", password or "")
        s.settimeout(_TIMEOUT)
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: s.connect((_TELEGRAM_HOST, _TELEGRAM_PORT)),
        )
        s.close()
        return True
    except Exception as exc:
        logger.debug("proxy_http_check_failed", host=host, port=port, error=str(exc))
        return False


async def check_proxy(proxy: Proxy) -> bool:
    """Return True if the proxy can reach Telegram."""
    if proxy.proxy_type == "socks5":
        alive = await _check_socks5(proxy.host, proxy.port, proxy.username, proxy.password)
    elif proxy.proxy_type == "http":
        alive = await _check_http(proxy.host, proxy.port, proxy.username, proxy.password)
    else:
        logger.warning("proxy_unknown_type", proxy_type=proxy.proxy_type)
        alive = False
    logger.info("proxy_liveness_check", host=proxy.host, port=proxy.port, alive=alive)
    return alive


async def check_and_update_proxy(session: AsyncSession, proxy: Proxy) -> bool:
    """Check liveness and persist the result to DB."""
    alive = await check_proxy(proxy)
    await session.execute(
        update(Proxy)
        .where(Proxy.id == proxy.id)
        .values(is_alive=alive, last_checked_at=datetime.now(timezone.utc))
    )
    await session.commit()
    return alive


async def check_all_proxies(session: AsyncSession) -> dict:
    """Background task: check every active proxy and update DB."""
    result = await session.execute(select(Proxy).where(Proxy.is_active == True))
    proxies = result.scalars().all()

    alive_count = 0
    dead_count = 0
    for proxy in proxies:
        alive = await check_and_update_proxy(session, proxy)
        if alive:
            alive_count += 1
        else:
            dead_count += 1

    logger.info("proxy_bulk_check_done", alive=alive_count, dead=dead_count)
    return {"alive": alive_count, "dead": dead_count, "total": len(proxies)}


def build_telethon_proxy(proxy: Proxy) -> tuple | None:
    """
    Return a Telethon-compatible proxy tuple, or None if the proxy is dead.

    Telethon uses PySocks format:
        (socks.SOCKS5, host, port, rdns, username, password)
    """
    try:
        import socks
        if proxy.proxy_type == "socks5":
            ptype = socks.SOCKS5
        elif proxy.proxy_type == "http":
            ptype = socks.HTTP
        else:
            return None

        return (
            ptype,
            proxy.host,
            proxy.port,
            True,
            proxy.username or "",
            proxy.password or "",
        )
    except ImportError:
        logger.error("pysocks_not_installed")
        return None
