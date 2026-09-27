from app.services.anti_spam.rate_limiter import check_rate_limit
from app.cache.redis_client import cache_get, cache_set
from app.cache.keys import CacheKeys
from app.core.config import settings
from app.core.logging import get_logger
import re

logger = get_logger(__name__)

SPAM_PATTERNS = [
    r"(?i)(earn\s+\$?\d+|make\s+money\s+fast|click\s+here\s+to\s+win)",
    r"(?i)(crypto\s+investment|bitcoin\s+profit|forex\s+signal|pump\s+and\s+dump)",
    r"(?i)(free\s+followers|buy\s+subscribers|boost\s+views|buy\s+likes)",
    r"https?://[^\s]{1,}(?:\s+https?://[^\s]{1,}){2,}",
    r"(?i)(congratulations.*won|you\s+have\s+been\s+selected|claim\s+your\s+prize)",
    r"(?i)(send\s+me\s+\$|wire\s+transfer|western\s+union|moneygram)",
    r"(?i)(100%\s+guaranteed|risk\s+free\s+profit|double\s+your\s+money)",
    r"(?i)(adult|xxx|porn|OnlyFans\s+promo)",
    r"(?i)(buy\s+now\s+limited|act\s+now\s+only|expires\s+today\s+only)",
]

SPAM_PATTERNS_FA = [
    r"(کسب\s+درآمد\s+آسان|درآمد\s+دلاری\s+بدون\s+کار|سود\s+تضمینی)",
    r"(خرید\s+فالوور|فروش\s+ممبر|افزایش\s+بازدید\s+تضمینی)",
    r"(ارز\s+دیجیتال\s+سود\s+تضمین|سرمایه‌گذاری\s+مطمئن\s+فوری)",
]

COMPILED_PATTERNS = [re.compile(p) for p in SPAM_PATTERNS]
COMPILED_FA_PATTERNS = [re.compile(p) for p in SPAM_PATTERNS_FA]

SUSPICIOUS_THRESHOLD = 0.5
MAX_STRIKES = 3


async def is_blacklisted(user_id: int) -> bool:
    cached = await cache_get(CacheKeys.blacklist(user_id))
    if cached is not None:
        return bool(cached)
    return False


async def get_strike_count(user_id: int) -> int:
    key = f"spam_strikes:{user_id}"
    val = await cache_get(key)
    return int(val) if val else 0


async def add_strike(user_id: int) -> int:
    key = f"spam_strikes:{user_id}"
    current = await get_strike_count(user_id)
    new_count = current + 1
    await cache_set(key, new_count, ttl=86400 * 7)
    if new_count >= MAX_STRIKES:
        await cache_set(CacheKeys.blacklist(user_id), True, ttl=86400 * 30)
        logger.warning("user_auto_blacklisted", user_id=user_id, strikes=new_count)
    return new_count


async def calculate_spam_score(user_id: int, text: str) -> tuple[float, list[str]]:
    score = 0.0
    reasons = []

    for pattern in COMPILED_PATTERNS:
        if pattern.search(text):
            score += 0.3
            reasons.append(f"pattern_match:{pattern.pattern[:30]}")

    for pattern in COMPILED_FA_PATTERNS:
        if pattern.search(text):
            score += 0.3
            reasons.append("fa_spam_pattern")

    if len(text) > 1500:
        score += 0.1
        reasons.append("excessive_length")

    url_count = len(re.findall(r'https?://', text))
    if url_count > 2:
        score += 0.15 * (url_count - 2)
        reasons.append(f"multiple_urls:{url_count}")

    caps_ratio = sum(1 for c in text if c.isupper()) / max(len(text), 1)
    if caps_ratio > 0.6 and len(text) > 20:
        score += 0.15
        reasons.append("excessive_caps")

    repeated = re.search(r'(.)\1{5,}', text)
    if repeated:
        score += 0.1
        reasons.append("repeated_chars")

    ok, limit_type = await check_rate_limit(user_id)
    if not ok:
        score += 0.4
        reasons.append(f"rate_limit:{limit_type}")

    prev_score_raw = await cache_get(CacheKeys.spam_score(user_id))
    if prev_score_raw:
        prev_score = float(prev_score_raw) if not isinstance(prev_score_raw, dict) else 0
        if prev_score >= SUSPICIOUS_THRESHOLD:
            score += 0.1
            reasons.append("repeat_suspicious")

    return min(score, 1.0), reasons


async def should_block(user_id: int, text: str) -> tuple[bool, str]:
    if await is_blacklisted(user_id):
        return True, "blacklisted"

    score, reasons = await calculate_spam_score(user_id, text)

    score_key = CacheKeys.spam_score(user_id)
    await cache_set(score_key, score, ttl=86400)

    if score >= settings.SPAM_SCORE_THRESHOLD:
        strikes = await add_strike(user_id)
        logger.warning("spam_detected", user_id=user_id, score=score, reasons=reasons, strikes=strikes)
        return True, f"spam_score:{score:.2f}|reasons:{','.join(reasons[:3])}"

    return False, ""


async def whitelist_user(user_id: int) -> None:
    await cache_set(CacheKeys.blacklist(user_id), False, ttl=86400 * 365)
    await cache_set(f"spam_strikes:{user_id}", 0, ttl=86400 * 7)
    logger.info("user_whitelisted", user_id=user_id)
