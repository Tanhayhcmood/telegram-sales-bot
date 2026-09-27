import asyncio
import ipaddress
from typing import List

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Source URLs ──────────────────────────────────────────────────────────────
_IPDENY_AGG  = "https://www.ipdeny.com/ipblocks/data/aggregated/{cc}-aggregated.zone"
_IPDENY_BASE = "https://www.ipdeny.com/ipblocks/data/countries/{cc}.zone"
# RIPE NCC Stat — free, no key, covers all RIR regions
_RIPE_URL    = "https://stat.ripe.net/data/country-resource-list/data.json?resource={CC}&v4_format=prefix"

# ── In-process cache (resets on restart, avoids repeat fetches in same run) ──
_cache: dict[str, List[str]] = {}


def _parse_ripe_ipv4(entries: list) -> List[str]:
    """Convert RIPE NCC IPv4 entries (CIDR or a.b.c.d-e.f.g.h) to CIDR list."""
    cidrs: List[str] = []
    for entry in entries:
        entry = entry.strip()
        if "/" in entry:
            cidrs.append(entry)
        elif "-" in entry:
            try:
                start, end = entry.split("-", 1)
                nets = ipaddress.summarize_address_range(
                    ipaddress.IPv4Address(start.strip()),
                    ipaddress.IPv4Address(end.strip()),
                )
                cidrs.extend(str(n) for n in nets)
            except Exception:
                pass
    return cidrs


async def _fetch_ipdeny(client: httpx.AsyncClient, cc: str) -> List[str]:
    """Try ipdeny.com aggregated → basic. Returns [] on any failure."""
    for url_tmpl in [_IPDENY_AGG, _IPDENY_BASE]:
        url = url_tmpl.format(cc=cc)
        try:
            resp = await client.get(url)
            if resp.status_code == 200 and resp.text.strip():
                cidrs = [
                    line.strip()
                    for line in resp.text.strip().split("\n")
                    if line.strip() and "/" in line
                ]
                if cidrs:
                    logger.info("ip_ranges_ipdeny_ok", cc=cc.upper(), count=len(cidrs))
                    return cidrs
        except Exception as exc:
            logger.warning("ip_ranges_ipdeny_err", cc=cc.upper(), url=url, error=str(exc))
    return []


async def _fetch_ripe(client: httpx.AsyncClient, cc: str) -> List[str]:
    """Try RIPE NCC Stat API as fallback. Returns [] on any failure."""
    url = _RIPE_URL.format(CC=cc.upper())
    try:
        resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            ipv4_list = data.get("data", {}).get("resources", {}).get("ipv4", [])
            cidrs = _parse_ripe_ipv4(ipv4_list)
            if cidrs:
                logger.info("ip_ranges_ripe_ok", cc=cc.upper(), count=len(cidrs))
                return cidrs
    except Exception as exc:
        logger.warning("ip_ranges_ripe_err", cc=cc.upper(), error=str(exc))
    return []


async def get_country_cidr_blocks(country_code: str) -> List[str]:
    """Fetch IPv4 CIDR blocks for a country code.

    Strategy (in order):
    1. In-memory cache  — instant, avoids duplicate fetches
    2. ipdeny.com aggregated zone
    3. ipdeny.com basic zone
    Retry once with a 1.5-second pause between attempts.
    4. RIPE NCC Stat API — covers all regions, very reliable
    Raises ValueError if all sources fail.
    """
    cc = country_code.lower().strip()

    # 1. Cache hit
    if cc in _cache:
        logger.info("ip_ranges_cache_hit", cc=cc.upper(), count=len(_cache[cc]))
        return _cache[cc]

    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        # 2+3. ipdeny with one retry
        cidrs: List[str] = []
        for attempt in range(2):
            cidrs = await _fetch_ipdeny(client, cc)
            if cidrs:
                break
            if attempt == 0:
                await asyncio.sleep(1.5)  # brief pause before retry

        # 4. RIPE NCC fallback
        if not cidrs:
            logger.info("ip_ranges_ipdeny_failed_trying_ripe", cc=cc.upper())
            cidrs = await _fetch_ripe(client, cc)

    if not cidrs:
        raise ValueError(
            f"No IP ranges found for '{cc.upper()}'. "
            "Check it's a valid 2-letter ISO code (e.g. US, DE, NL, IR, GB)."
        )

    _cache[cc] = cidrs
    return cidrs
