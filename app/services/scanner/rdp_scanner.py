"""
RDP Scanner — async TCP port-3389 scanner targeting Azure/AWS/cloud Windows VM ranges.

Confirmed working: Azure range 20.115.x.x has open RDP (tested 20.115.100.39:3389).

Architecture:
  - run_rdp_pool_builder() : background task started at app startup; continuously
    scans cloud ranges via async TCP and stores verified IPs in Redis pool.
  - scan_for_rdp()         : pops a verified IP from the Redis pool. If the pool
    is empty (first run), falls back to an inline scan so the button always works.
"""
import asyncio
import random
import string
import json
from typing import Optional, TypedDict

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

# ── IP ranges to scan ────────────────────────────────────────────────────────
# Azure and cloud ranges where Windows VMs with exposed RDP are common.
# Format: (a, b_min, b_max) → scan a.b.*.* randomly
SCAN_RANGES: list[tuple[int, int, int]] = [
    # Azure Public
    (20,  33,  35),  (20,  42,  45),  (20,  64,  68),
    (20,  98, 101),  (20, 112, 120),  (20, 150, 155),
    (20, 185, 192),  (20, 196, 202),  (20, 218, 225),
    (40,  64,  70),  (40,  74,  80),  (40,  86,  92),
    (40, 112, 118),  (40, 120, 125),
    (52, 140, 145),  (52, 148, 155),  (52, 160, 165),
    (52, 183, 190),  (52, 224, 232),
    (104, 40,  48),  (104, 208, 215),
    (13,  64,  72),  (13,  86,  92),  (13, 104, 110),
    # AWS Windows (EC2)
    (54,  67,  75),  (54, 152, 160),  (54, 184, 192),
    (18, 116, 120),  (18, 188, 196),
    (34, 195, 205),  (34, 215, 225),
    # Google Cloud Windows
    (34,  64,  72),  (34,  80,  90),  (35, 184, 200),
    # Linode/Akamai Windows VMs
    (170, 187, 188),
    # Contabo DE (popular cheap Windows VPS)
    (173, 212, 213),
    # OVH FR (Windows VPS product)
    (51,  38,  40),  (51,  68,  70),
    # Various Eastern EU (M247, DataCamp, etc.)
    (185, 181, 182), (185, 246, 247),
]

# Common Windows RDP usernames
_USERNAMES = ["Administrator", "Admin", "admin", "User", "user", "windows"]

_POOL_KEY     = "rdp_pool:verified"
_USED_KEY     = "rdp_pool:used"
_POOL_MIN     = 15   # keep at least this many in pool
_POOL_MAX     = 60   # stop scanning when pool this full
_SCAN_BATCH   = 300  # IPs per scan round
_CONCURRENCY  = 80   # parallel TCP connections
_TCP_TIMEOUT  = 3.0  # seconds per connect attempt
_POOL_TTL     = 6 * 3600        # 6 hours — IPs go stale fast; never keep longer
_USED_TTL     = 7 * 24 * 3600  # 7 days dedup window
_POOL_MAX_POP = 6   # max pool pop attempts before falling back to inline scan
                    # keeps worst-case pool-check latency under ~20s (6 × 3s)


class RDPResult(TypedDict):
    ip: str
    port: int
    username: str
    password: str
    country_name: str
    country_flag: str
    country_code: str


# ── Country data ─────────────────────────────────────────────────────────────
_COUNTRIES = {
    "US": ("United States",  "🇺🇸"),
    "DE": ("Germany",        "🇩🇪"),
    "NL": ("Netherlands",    "🇳🇱"),
    "FR": ("France",         "🇫🇷"),
    "GB": ("United Kingdom", "🇬🇧"),
    "CA": ("Canada",         "🇨🇦"),
    "JP": ("Japan",          "🇯🇵"),
    "SG": ("Singapore",      "🇸🇬"),
    "AU": ("Australia",      "🇦🇺"),
    "IE": ("Ireland",        "🇮🇪"),
    "SE": ("Sweden",         "🇸🇪"),
    "FI": ("Finland",        "🇫🇮"),
    "RO": ("Romania",        "🇷🇴"),
    "PL": ("Poland",         "🇵🇱"),
    "TR": ("Turkey",         "🇹🇷"),
    "RU": ("Russia",         "🇷🇺"),
    "BR": ("Brazil",         "🇧🇷"),
    "KR": ("South Korea",    "🇰🇷"),
}
_DEFAULT_COUNTRY = ("Unknown", "🌐", "XX")


def generate_rdp_password(length: int = 14) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%&*"
    required = [
        random.choice(string.ascii_uppercase),
        random.choice(string.ascii_lowercase),
        random.choice(string.digits),
        random.choice("!@#$%&*"),
    ]
    extra = [random.choice(chars) for _ in range(length - 4)]
    pool = required + extra
    random.shuffle(pool)
    return "".join(pool)


def _random_ip() -> str:
    a, b_min, b_max = random.choice(SCAN_RANGES)
    b = random.randint(b_min, b_max)
    c = random.randint(1, 254)
    d = random.randint(2, 253)
    return f"{a}.{b}.{c}.{d}"


async def _tcp_open(ip: str, port: int = 3389, timeout: float = _TCP_TIMEOUT) -> bool:
    """Return True if TCP connect to ip:port succeeds within timeout."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout
        )
        try:
            writer.close()
            await asyncio.wait_for(writer.wait_closed(), timeout=0.5)
        except Exception:
            pass
        return True
    except Exception:
        return False


async def _geo_lookup(ip: str) -> tuple[str, str, str]:
    """
    Get (country_name, flag, country_code) for an IP via ip-api.com (free, no key).
    Falls back to Unknown on any error.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"http://ip-api.com/json/{ip}?fields=status,country,countryCode",
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == "success":
                    cc = data.get("countryCode", "XX")
                    name, flag = _COUNTRIES.get(cc, (data.get("country", "Unknown"), "🌐"))
                    return name, flag, cc
    except Exception:
        pass
    return _DEFAULT_COUNTRY


async def _scan_batch_for_rdp(count: int = _SCAN_BATCH) -> list[tuple[str, str, str, str]]:
    """
    Scan `count` random IPs from cloud ranges. Return list of
    (ip, country_name, flag, country_code) for IPs with port 3389 open.
    """
    sem = asyncio.Semaphore(_CONCURRENCY)
    ips = [_random_ip() for _ in range(count)]

    async def check(ip: str) -> Optional[str]:
        async with sem:
            return ip if await _tcp_open(ip) else None

    results = await asyncio.gather(*[check(ip) for ip in ips], return_exceptions=True)
    found: list[str] = [r for r in results if isinstance(r, str)]

    if not found:
        return []

    logger.info("rdp_tcp_found", count=len(found), ips=found[:5])

    # Geo-lookup all found IPs in parallel
    geo_tasks = [_geo_lookup(ip) for ip in found]
    geo_results = await asyncio.gather(*geo_tasks, return_exceptions=True)

    out = []
    for ip, geo in zip(found, geo_results):
        if isinstance(geo, tuple) and len(geo) == 3:
            name, flag, cc = geo
        else:
            name, flag, cc = _DEFAULT_COUNTRY
        out.append((ip, name, flag, cc))

    return out


async def _pool_size(r) -> int:
    try:
        return await r.scard(_POOL_KEY)
    except Exception:
        return 0


async def _add_to_pool(r, ip: str, name: str, flag: str, cc: str) -> None:
    entry = json.dumps({"ip": ip, "country_name": name, "country_flag": flag, "country_code": cc})
    await r.sadd(_POOL_KEY, entry)
    await r.expire(_POOL_KEY, _POOL_TTL)


async def _pop_from_pool(r) -> Optional[dict]:
    entry = await r.spop(_POOL_KEY)
    if entry is None:
        return None
    try:
        return json.loads(entry)
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

async def scan_for_rdp() -> Optional[RDPResult]:
    """
    Return a verified RDPResult (port 3389 confirmed open via TCP).

    1. Tries to pop a pre-verified IP from the Redis pool (instant).
    2. If pool is empty, falls back to an inline scan (takes up to ~30s).
    3. Attaches random RDP credentials for the post.
    """
    from app.cache.redis_client import get_redis

    r = None
    try:
        r = await get_redis()
    except Exception as redis_err:
        logger.warning("rdp_redis_unavailable", error=str(redis_err)[:60])

    # ── 1. Try Redis pool — with live re-verification ────────────────────────
    # CRITICAL: An IP verified hours ago may now be offline.
    # We MUST re-check TCP before publishing or users get dead servers.
    if r is not None:
        for _pop_attempt in range(_POOL_MAX_POP):
            try:
                entry = await _pop_from_pool(r)
                if entry is None:
                    break  # pool exhausted — fall through to inline scan

                ip = entry["ip"]

                # Re-verify the IP is still reachable RIGHT NOW
                # _tcp_open already applies _TCP_TIMEOUT internally — no extra wrap needed
                try:
                    still_alive = await _tcp_open(ip)
                except Exception:
                    still_alive = False

                if not still_alive:
                    logger.info("rdp_pool_ip_dead_discarding", ip=ip,
                                country=entry.get("country_name"),
                                attempt=_pop_attempt + 1)
                    continue  # try next entry in pool

                logger.info("rdp_from_pool_verified", ip=ip,
                            country=entry.get("country_name"),
                            attempts_needed=_pop_attempt + 1)

                # Mark as recently used for dedup — errors here must NOT discard
                # a live IP we already verified; return it regardless
                try:
                    await r.sadd(_USED_KEY, ip)
                    await r.expire(_USED_KEY, _USED_TTL)
                except Exception as dedup_err:
                    logger.warning("rdp_dedup_write_failed", ip=ip, error=str(dedup_err)[:60])

                return RDPResult(
                    ip=ip,
                    port=3389,
                    username=random.choice(_USERNAMES),
                    password=generate_rdp_password(),
                    country_name=entry["country_name"],
                    country_flag=entry["country_flag"],
                    country_code=entry["country_code"],
                )
            except Exception as e:
                logger.warning("rdp_pool_pop_error", error=str(e)[:80])
                # transient Redis error — skip this iteration, don't abort the loop
                continue

    # ── 2. Inline scan fallback ──────────────────────────────────────────────
    logger.info("rdp_pool_empty_scanning_inline")
    try:
        found = await asyncio.wait_for(_scan_batch_for_rdp(400), timeout=40.0)
    except asyncio.TimeoutError:
        found = []

    if found:
        # Store extras in pool for next time
        if r is not None:
            for item in found[1:]:
                try:
                    await _add_to_pool(r, *item)
                except Exception:
                    pass

        ip, name, flag, cc = found[0]
        logger.info("rdp_inline_scan_success", ip=ip, country=name)
        return RDPResult(
            ip=ip,
            port=3389,
            username=random.choice(_USERNAMES),
            password=generate_rdp_password(),
            country_name=name,
            country_flag=flag,
            country_code=cc,
        )

    # ── 3. Nothing found — pool empty and scan failed ────────────────────────
    # This should be very rare since Azure has millions of Windows VMs.
    logger.warning("rdp_scan_no_result")
    return None


async def run_rdp_pool_builder() -> None:
    """
    Background task: keep the Redis pool filled with verified RDP IPs.
    Runs continuously, scanning batches every few minutes.
    """
    logger.info("rdp_pool_builder_started")
    await asyncio.sleep(60)  # let the app finish startup first

    from app.cache.redis_client import get_redis

    while True:
        try:
            r = await get_redis()
            size = await _pool_size(r)
            logger.info("rdp_pool_check", pool_size=size)

            if size < _POOL_MIN:
                needed = _POOL_MAX - size
                logger.info("rdp_pool_refilling", needed=needed)

                found = await asyncio.wait_for(
                    _scan_batch_for_rdp(_SCAN_BATCH), timeout=50.0
                )
                added = 0
                for ip, name, flag, cc in found:
                    try:
                        # Skip recently used IPs
                        if await r.sismember(_USED_KEY, ip):
                            continue
                        await _add_to_pool(r, ip, name, flag, cc)
                        added += 1
                        if added >= needed:
                            break
                    except Exception:
                        pass

                logger.info("rdp_pool_refill_done",
                            added=added, found=len(found), pool_size=await _pool_size(r))
            else:
                logger.info("rdp_pool_sufficient", size=size)

            # Check again in 5 minutes
            await asyncio.sleep(300)

        except asyncio.CancelledError:
            logger.info("rdp_pool_builder_cancelled")
            break
        except Exception as e:
            logger.error("rdp_pool_builder_error", error=str(e)[:120])
            await asyncio.sleep(120)
