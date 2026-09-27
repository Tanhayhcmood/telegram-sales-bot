"""
port_scanner.py — Smart RDP finder using Shodan InternetDB pre-filter.

Instead of blind TCP scanning (low hit rate on random country IPs),
we query Shodan InternetDB (free, no key) to check if port 3389 is listed
for each sampled IP. This avoids ~99.9% of useless TCP timeouts.
"""
import asyncio
import ipaddress
import random
from typing import List, Optional

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

# Shodan InternetDB — free, no API key, pre-scanned internet data
_SHODAN_URL = "https://internetdb.shodan.io/{ip}"

# Concurrent Shodan HTTP requests (safe limit to avoid hammering)
_SHODAN_CONCURRENCY = 80

# Concurrent TCP verifications (only for IPs Shodan confirmed)
_TCP_CONCURRENCY = 60


async def _shodan_has_port(
    ip: str,
    port: int,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
) -> Optional[str]:
    """Return ip if Shodan InternetDB says the port is open, else None."""
    async with sem:
        try:
            resp = await client.get(_SHODAN_URL.format(ip=ip))
            if resp.status_code == 200:
                data = resp.json()
                if port in data.get("ports", []):
                    return ip
        except Exception:
            pass
    return None


async def _tcp_connect(
    ip: str,
    port: int,
    timeout: float,
    sem: asyncio.Semaphore,
) -> Optional[str]:
    """Verify TCP connection. Returns ip on success."""
    async with sem:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=timeout
            )
            try:
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), timeout=0.5)
            except Exception:
                pass
            return ip
        except Exception:
            return None


def _sample_ips(cidrs: List[str], max_ips: int) -> List[str]:
    """Sample up to max_ips unique IPs from the given CIDR list."""
    pool: List[str] = []
    for cidr in cidrs:
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            # Skip huge blocks to avoid memory blow-up — but do sample them
            if net.num_addresses > 65536:
                # Sample proportionally from large blocks
                hosts = list(net.hosts())
                sample_count = min(200, max_ips // max(len(cidrs), 1) + 1)
                pool.extend(random.sample(hosts, min(sample_count, len(hosts))))
            else:
                pool.extend(str(h) for h in net.hosts())
            if len(pool) >= max_ips * 3:
                break
        except Exception:
            continue

    random.shuffle(pool)
    # Deduplicate while preserving shuffle order
    seen = set()
    result = []
    for ip in pool:
        if ip not in seen:
            seen.add(ip)
            result.append(ip)
            if len(result) >= max_ips:
                break
    return result


async def scan_port(
    cidrs: List[str],
    port: int = 3389,
    max_ips: int = 8_000,
    timeout: float = 1.5,
) -> List[str]:
    """
    Find IPs with an open port using Shodan InternetDB pre-filter + TCP verify.

    Steps:
    1. Sample up to max_ips IPs from the given CIDRs.
    2. Query Shodan InternetDB for each IP to check if the port is listed.
    3. TCP-verify the Shodan-confirmed IPs for live confirmation.

    Returns a list of live IPs with the port open.
    """
    sampled = _sample_ips(cidrs, max_ips)
    if not sampled:
        return []

    logger.info(
        "scan_port_start",
        cidrs=len(cidrs),
        sampled=len(sampled),
        port=port,
    )

    # ── Step 1: Shodan pre-filter ────────────────────────────────────────────
    shodan_sem = asyncio.Semaphore(_SHODAN_CONCURRENCY)
    shodan_confirmed: List[str] = []

    async with httpx.AsyncClient(timeout=6, follow_redirects=False) as client:
        tasks = [_shodan_has_port(ip, port, client, shodan_sem) for ip in sampled]
        # Process in batches to avoid building a huge coroutine list
        batch = 500
        for i in range(0, len(tasks), batch):
            results = await asyncio.gather(*tasks[i : i + batch])
            shodan_confirmed.extend(r for r in results if r is not None)

    logger.info(
        "scan_port_shodan_done",
        sampled=len(sampled),
        confirmed=len(shodan_confirmed),
        port=port,
    )

    if not shodan_confirmed:
        return []

    # ── Step 2: TCP verify Shodan-confirmed IPs ──────────────────────────────
    tcp_sem = asyncio.Semaphore(_TCP_CONCURRENCY)
    tcp_tasks = [_tcp_connect(ip, port, timeout, tcp_sem) for ip in shodan_confirmed]
    tcp_results = await asyncio.gather(*tcp_tasks)
    found = [r for r in tcp_results if r is not None]

    logger.info("scan_port_done", found=len(found), port=port)
    return found
