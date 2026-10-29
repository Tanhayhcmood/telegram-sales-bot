"""Fail-closed customer outbound guard and abuse throttling."""
from __future__ import annotations
import base64
import ipaddress
import json
import re
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)
SAFE_FALLBACK = "I've passed this to our team, someone will contact you shortly"
SUPPORT_HANDOFF_FA = "پیامت رو به تیم پشتیبانی ارجاع دادم؛ به‌زودی باهات تماس می‌گیرن."

def support_handoff(language: str) -> str:
    return SUPPORT_HANDOFF_FA if language == "fa" else SAFE_FALLBACK
FREE_DECLINE_EN = "Free or trial servers are announced only in our channel; we do not offer private free servers."
FREE_DECLINE_FA = "سرور رایگان یا آزمایشی فقط در کانال اعلام می‌شود؛ سرور رایگان خصوصی ارائه نمی‌کنیم."
_GUARD_KEY = "security:customer_outbound_guard"
_BLOCKS_KEY = "security:customer_outbound_blocks"
_SUSPICIOUS_KEY = "security:customer_suspicious_attempts"
_DELIVERY_BYPASS = object()

_SENSITIVE_PATTERNS = (
    ("credential_word", re.compile(r"\b(?:password|passcode|passphrase|pwd|secret|credential)\b|رمز(?:عبور)?|گذرواژه", re.I)),
    ("identity_field", re.compile(r"\b(?:username|user\s*name|login)\s*[:=]|\buser\s*[:=]\s*\S+\s*[/|;, ]+\s*pass(?:word)?\s*[:=]", re.I)),
    ("remote_access", re.compile(r"\b(?:ssh|rdp|mstsc|remote\s+desktop|vps\s+access|server\s+access)\b", re.I)),
    ("reset_or_provisioning_claim", re.compile(r"\breset\w*\b|\b(?:(?:i|we)\s+(?:have\s+|just\s+)?(?:reset|created|activated|gave|sent|provisioned)|(?:server|account|service)\s+(?:was\s+)?(?:created|activated|provisioned|reset))\b", re.I)),
    ("free_server_claim", re.compile(r"\b(?:free|trial|test)\s+(?:vps|server)\b|\b(?:gave|created|activated)\s+(?:you\s+)?(?:a\s+)?free\s+server\b|سرور.{0,16}(?:رایگان|تست)", re.I)),
    ("ip_address", re.compile(r"(?<![\w])(?:\d{1,3}\.){3}\d{1,3}(?![\w])|(?<![\w:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![\w:])", re.I)),
    ("hostname", re.compile(r"(?<![@\w-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}(?![\w-])", re.I)),
    ("encoded_secret", re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{32,}={0,2}(?![A-Za-z0-9+/=])|\b[0-9a-f]{32,}\b", re.I)),
    ("long_token", re.compile(r"\b[A-Za-z0-9_-]{24,}\b")),
)
_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions", re.I),
    re.compile(r"\b(?:system|developer)\s+(?:message|prompt|instruction)\b", re.I),
    re.compile(r"\b(?:i\s+am|i'm)\s+(?:the\s+)?(?:admin|owner|developer|operator)\b", re.I),
    re.compile(r"\badmin\s+(?:said|told\s+me|authorized|approved)\b", re.I),
    re.compile(r"\b(?:pretend|roleplay|act\s+as|override|bypass)\b", re.I),
    re.compile(r"دستور(?:های)? قبلی را نادیده|من مدیر(?:م)?|پیام سیستم|نقش بازی کن|دور زدن", re.I),
)
_SUPPORT_TERMS = re.compile(r"\b(?:password|passcode|pwd|login|log\s*in|access|credentials?|reset|activation|activate|refund|not\s+working|doesn.t\s+work|can.t\s+connect|server\s+down|rdp|ssh|panel)\b|رمز|ورود|دسترسی|بازنشانی|ریست|فعال(?:سازی|شدن)?|بازپرداخت|کار نمی.?کند|وصل نمی.?شود|مشکل سرور", re.I)
_FREE_TERMS = re.compile(r"\b(?:free|trial|test\s+server|test\s+vps|giveaway|discount(?:ed)?)\b|رایگان|تست|هدیه|تخفیف", re.I)


def outbound_reason(text: str) -> str | None:
    text = str(text or "")
    for reason, pattern in _SENSITIVE_PATTERNS:
        if pattern.search(text):
            return reason
    for match in _SENSITIVE_PATTERNS[5][1].finditer(text):
        try:
            ipaddress.ip_address(match.group(0))
        except ValueError:
            continue
        return "ip_address"
    return None


def filter_outbound_text(text: str) -> str:
    return SAFE_FALLBACK if outbound_reason(text) else str(text or "")


def is_prompt_injection(text: str, forwarded: bool = False) -> bool:
    value = str(text or "").replace("\u200c", " ")
    if forwarded or len(value) > 8000:
        return True
    if re.search(r"\b[A-Za-z0-9+/]{128,}={0,2}\b|\b[0-9a-f]{64,}\b", value, re.I):
        return True
    return any(pattern.search(value) for pattern in _INJECTION_PATTERNS)


def is_free_server_request(text: str) -> bool:
    value = str(text or "").casefold().replace("\u200c", " ")
    if not _FREE_TERMS.search(value):
        return False
    if re.search(r"\bfree\s+(?:setup|installation|install)\b|\b(?:setup|installation|install)\b.{0,18}\bfree\b|\bfree\b.{0,18}\b(?:setup|installation|install)\b|راه.?اندازی رایگان|نصب رایگان", value):
        return False
    return bool(re.search(r"\b(?:server|vps|host|hosting|machine)\b|سرور|هاست", value))


def is_support_request(text: str) -> bool:
    return bool(_SUPPORT_TERMS.search(str(text or "")))


def sanitize_history(messages: list[dict]) -> list[dict]:
    clean = []
    for message in messages or []:
        content = str(message.get("content", ""))
        if is_prompt_injection(content) or outbound_reason(content):
            content = "[untrusted or sensitive content omitted]"
        clean.append({"role": message.get("role", "user"), "content": content})
    return clean


def sanitize_model_context(text: str) -> str:
    value = str(text or "")
    if is_prompt_injection(value) or outbound_reason(value):
        return "[customer context omitted by security filter]"
    return value


def _redacted_excerpt(text: str) -> str:
    value = str(text or "")
    if outbound_reason(value) or is_prompt_injection(value):
        return "[sensitive or suspicious message redacted]"
    return re.sub(r"[\r\n\t]+", " ", value)[:240]


async def guard_enabled() -> bool:
    try:
        from app.cache.redis_client import get_redis
        value = await (await get_redis()).get(_GUARD_KEY)
        return value != "off"
    except Exception:
        return True


async def set_guard_enabled(enabled: bool, admin_id: int) -> bool:
    from app.core.config import settings
    if int(admin_id) not in set(settings.admin_ids):
        return False
    from app.cache.redis_client import get_redis
    await (await get_redis()).set(_GUARD_KEY, "on" if enabled else "off")
    logger.warning("customer_outbound_guard_changed enabled=%s admin_id=%s", enabled, int(admin_id))
    return True


async def claim_ai_reply_slot(user_id: int) -> bool:
    """Shared per-user cooldown and hourly cap; fail closed if Redis is unavailable."""
    try:
        from app.cache.redis_client import get_redis
        redis = await get_redis()
        cooldown = await redis.set(f"security:ai:cooldown:{int(user_id)}", "1", nx=True, ex=12)
        if not cooldown:
            return False
        key = f"security:ai:hour:{int(user_id)}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 3600)
        return count <= 30
    except Exception as error:
        logger.error("ai_rate_limit_failed_closed user_id=%s error=%s", int(user_id), type(error).__name__)
        return False


async def _store_event(key: str, event: dict) -> None:
    try:
        from app.cache.redis_client import get_redis
        redis = await get_redis()
        await redis.lpush(key, json.dumps(event, ensure_ascii=False))
        await redis.ltrim(key, 0, 999 if key == _SUSPICIOUS_KEY else 19)
    except Exception:
        pass


async def guard_log() -> list[dict]:
    try:
        from app.cache.redis_client import get_redis
        values = await (await get_redis()).lrange(_BLOCKS_KEY, 0, 19)
        return [json.loads(value) for value in values]
    except Exception:
        return []


async def notify_admins_once(user_id: int, text: str, reason: str, order_id: str | None = None) -> None:
    try:
        from app.cache.redis_client import get_redis
        redis = await get_redis()
        if not await redis.set(f"security:admin-summary:{int(user_id)}", "1", nx=True, ex=3600):
            return
        from app.core.config import settings
        from app.services.admin_bot.bot import get_bot
        bot = get_bot()
        if bot is None:
            return
        summary = f"Security handoff: user {int(user_id)}; reason={reason}; order={order_id or 'none'}; text={_redacted_excerpt(text)}"
        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(chat_id=admin_id, text=summary, parse_mode=None)
            except Exception as error:
                logger.warning("security_admin_notice_failed admin_id=%s error=%s", admin_id, type(error).__name__)
    except Exception as error:
        logger.warning("security_admin_notice_unavailable error=%s", type(error).__name__)


async def record_suspicious_attempt(user_id: int, text: str, reason: str, order_id: str | None = None) -> None:
    event = {"at": datetime.now(timezone.utc).isoformat(), "user_id": int(user_id), "reason": reason, "text": _redacted_excerpt(text)}
    await _store_event(_SUSPICIOUS_KEY, event)
    logger.warning("customer_suspicious_attempt %s", json.dumps(event, ensure_ascii=False))
    await notify_admins_once(user_id, text, reason, order_id)


async def filter_ai_outbound(user_id: int, text: str, order_id: str | None = None) -> str:
    # The sensitive-output filter is non-bypassable, even when AI replies are paused.
    reason = outbound_reason(text)
    if not reason:
        return text
    event = {"at": datetime.now(timezone.utc).isoformat(), "user_id": int(user_id), "reason": reason, "text": _redacted_excerpt(text)}
    await _store_event(_BLOCKS_KEY, event)
    logger.warning("customer_ai_outbound_blocked %s", json.dumps(event, ensure_ascii=False))
    await notify_admins_once(user_id, text, f"outbound:{reason}", order_id)
    return SAFE_FALLBACK


async def send_customer_message(sender, user_id: int, text: str, *, ai_generated: bool = False, delivery_authorization=None, order_id: str | None = None, **kwargs):
    """Single customer-text send gate. Only the delivery module owns its bypass token."""
    if ai_generated and delivery_authorization is not _DELIVERY_BYPASS:
        text = await filter_ai_outbound(user_id, text, order_id)
    await sender(text, **kwargs)


async def send_verified_delivery(sender, user_id: int, text: str, order_id: str):
    await send_customer_message(sender, user_id, text, delivery_authorization=_DELIVERY_BYPASS, order_id=order_id)
