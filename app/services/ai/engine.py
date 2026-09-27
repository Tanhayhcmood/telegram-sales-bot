"""
AI engine — wraps Groq (primary) and OpenAI (fallback).
When Groq quota is exhausted, sets a cooldown flag so auto_poster
pauses gracefully without crashing the process or the userbot.
"""
from openai import AsyncOpenAI, RateLimitError, AuthenticationError
from app.core.config import settings
from app.core.logging import get_logger
from typing import Optional, List, AsyncIterator
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
import asyncio
import math
import re
import time

logger = get_logger(__name__)

# Bug 2 fix: track a fingerprint of the active provider/key so the client is
# recreated whenever the API key or provider changes (e.g. key rotation,
# Groq ↔ OpenAI switch) — previously the singleton would serve the old key
# until process restart.
_client: Optional[AsyncOpenAI] = None
_client_fingerprint: str = ""
_request_gate = asyncio.Semaphore(1)


def _get_client_fingerprint() -> str:
    """Stable string that changes whenever the active provider or key changes."""
    if settings.GROQ_API_KEY:
        return f"groq:{settings.GROQ_API_KEY[:16]}:{settings.GROQ_BASE_URL}"
    return f"openai:{settings.OPENAI_API_KEY[:16]}"


# ── Groq failure handling ────────────────────────────────────────────────────
# A transient 429 is common on shared/free model limits.  It must be retried
# with tenacity, not treated as a one-hour outage for every conversation.
# Only an explicit hard-quota/auth failure enters this short safety cooldown.
QUOTA_COOLDOWN = 300  # 5 minutes for a hard quota/auth failure
_quota_exhausted_until: float = 0.0


def _is_quota_exhausted() -> bool:
    return time.monotonic() < _quota_exhausted_until


def _mark_quota_exhausted() -> None:
    global _quota_exhausted_until
    _quota_exhausted_until = time.monotonic() + QUOTA_COOLDOWN
    logger.warning(
        "ai_hard_failure_cooling_down",
        cooldown_seconds=QUOTA_COOLDOWN,
        provider="groq" if settings.GROQ_API_KEY else "openai",
        model=get_model(),
    )


def is_ai_available() -> bool:
    """Returns False when quota is in cooldown — callers should skip AI work."""
    return not _is_quota_exhausted()


def get_ai_client() -> AsyncOpenAI:
    global _client, _client_fingerprint
    fp = _get_client_fingerprint()
    # Bug 2 fix: recreate client when provider/key changes, not only when None
    if _client is None or fp != _client_fingerprint:
        _client_fingerprint = fp
        if settings.GROQ_API_KEY:
            _client = AsyncOpenAI(
                api_key=settings.GROQ_API_KEY,
                base_url=settings.GROQ_BASE_URL,
                timeout=60.0,
                max_retries=0,
            )
            logger.info("ai_provider_groq", model=settings.GROQ_MODEL)
        else:
            _client = AsyncOpenAI(
                api_key=settings.OPENAI_API_KEY,
                timeout=60.0,
                max_retries=0,
            )
            logger.info("ai_provider_openai", model=settings.OPENAI_MODEL)
    return _client


def get_model() -> str:
    return settings.GROQ_MODEL if settings.GROQ_API_KEY else settings.OPENAI_MODEL


def _status_code(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )


def _is_rate_limit_error(exc: Exception) -> bool:
    """Return True for temporary request/model throttling."""
    if isinstance(exc, RateLimitError) or _status_code(exc) == 429:
        return True
    msg = str(exc).lower()
    return any(k in msg for k in ("rate limit", "rate_limit", "too many requests", "429"))


def _retry_after_seconds(exc: Exception) -> float | None:
    """Extract the provider's suggested retry delay when it supplies one."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    header_value = headers.get("retry-after") or headers.get("Retry-After")
    if header_value:
        try:
            return max(1.0, float(header_value))
        except (TypeError, ValueError):
            pass

    match = re.search(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", str(exc), re.IGNORECASE)
    if match:
        return max(1.0, float(match.group(1)))
    return None


def _wait_for_retry(retry_state) -> float:
    """Wait long enough for a temporary Groq TPM window to recover."""
    outcome = retry_state.outcome
    exc = outcome.exception() if outcome and outcome.failed else None
    if exc is not None and _is_rate_limit_error(exc):
        suggested = _retry_after_seconds(exc)
        if suggested is not None:
            # Add a small buffer so the next request does not land on the
            # exact edge of the provider's rolling window.
            return min(math.ceil(suggested) + 1, 30.0)

    attempt = max(retry_state.attempt_number, 1)
    return min(float(2 ** attempt), 8.0)


def _is_quota_error(exc: Exception) -> bool:
    """True only for hard quota/auth failures that a retry cannot repair.

    Groq uses 429 for both short-lived RPM/TPM throttling and exhausted
    quotas.  Treating every 429 as exhausted was the reason one temporary
    throttle forced all later customer messages into the canned fallback.
    """
    if _is_rate_limit_error(exc):
        msg = str(exc).lower()
        hard_quota_markers = (
            "insufficient_quota",
            "quota exceeded",
            "billing",
            "tokens per day",
            "daily limit",
            "monthly limit",
        )
        if not any(marker in msg for marker in hard_quota_markers):
            return False
    if isinstance(exc, AuthenticationError) or _status_code(exc) == 401:
        return True
    msg = str(exc).lower()
    return any(k in msg for k in (
        "invalid api key",
        "unauthorized",
        "authentication failed",
        "401",
    ))


def _is_retryable(exc: Exception) -> bool:
    """Only retry transient network/server errors. Never retry quota/auth errors."""
    if _is_quota_error(exc):
        return False
    return True


@retry(
    stop=stop_after_attempt(3),
    wait=_wait_for_retry,
    retry=retry_if_exception(_is_retryable),   # never retry quota/auth errors
    reraise=True,
)
async def generate_reply(
    messages: List[dict],
    system_prompt: str,
    temperature: float = None,
    max_tokens: int = None,
    tools: List[dict] = None,
) -> tuple[str, int]:
    # Check quota cooldown FIRST — bail immediately, no retries
    if _is_quota_exhausted():
        raise RuntimeError("AI quota cooldown active — skipping")

    client = get_ai_client()
    temperature = temperature if temperature is not None else settings.OPENAI_TEMPERATURE
    max_tokens = max_tokens or settings.AI_REPLY_MAX_TOKENS

    full_messages = [{"role": "system", "content": system_prompt}] + messages

    kwargs = dict(
        model=get_model(),
        messages=full_messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    try:
        async with _request_gate:
            response = await client.chat.completions.create(**kwargs)
        # Bug 4 fix: guard against None/empty response — provider can return empty choices
        # or null message content, which caused AttributeError/IndexError downstream.
        if not response or not response.choices:
            raise ValueError("AI returned an empty response (no choices)")
        msg = response.choices[0].message
        if msg is None or msg.content is None:
            raise ValueError("AI response message or content is None")
        content = msg.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        logger.info("ai_reply_generated", tokens=tokens, model=get_model())
        return content, tokens
    except Exception as e:
        if _is_quota_error(e):
            # Mark only hard quota/auth failures.  Temporary 429s remain
            # retryable and are handled by tenacity below.
            _mark_quota_exhausted()
            raise RuntimeError(f"AI quota/auth error — cooldown started: {e}") from e
        if _is_rate_limit_error(e):
            logger.warning(
                "ai_rate_limited_retrying",
                provider="groq" if settings.GROQ_API_KEY else "openai",
                model=get_model(),
                status_code=_status_code(e),
            )
        else:
            logger.error(
                "ai_generation_failed",
                error=str(e),
                error_type=type(e).__name__,
                status_code=_status_code(e),
            )
        raise


async def generate_content(prompt: str, system: str = "", temperature: float = 0.8) -> str:
    """
    Single-call AI content generation.
    Raises RuntimeError immediately when quota is exhausted (no retries).
    Callers should check is_ai_available() before calling if they want to skip silently.
    """
    if _is_quota_exhausted():
        raise RuntimeError("AI quota cooldown active — skipping content generation")

    client = get_ai_client()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        async with _request_gate:
            response = await client.chat.completions.create(
                model=get_model(),
                messages=messages,
                temperature=temperature,
                max_tokens=1200,
            )
        # Bug 4 fix: guard against None/empty response in generate_content too
        if not response or not response.choices:
            raise ValueError("AI returned an empty response (no choices)")
        msg = response.choices[0].message
        if msg is None or msg.content is None:
            raise ValueError("AI response message or content is None")
        return msg.content or ""
    except Exception as e:
        if _is_quota_error(e):
            _mark_quota_exhausted()
        raise


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=5))
async def generate_embedding(text: str) -> List[float]:
    if settings.GROQ_API_KEY and not settings.OPENAI_API_KEY:
        logger.warning("embeddings_not_supported_on_groq_returning_empty")
        return []
    if _is_quota_exhausted():
        return []
    client = get_ai_client()
    text = text.replace("\n", " ")[:8000]
    try:
        async with _request_gate:
            response = await client.embeddings.create(
                model="text-embedding-3-small",
                input=text,
            )
        return response.data[0].embedding
    except Exception as e:
        if _is_quota_error(e):
            _mark_quota_exhausted()
        logger.error("embedding_generation_failed", error=str(e))
        return []


async def generate_reply_streaming(
    messages: List[dict],
    system_prompt: str,
    temperature: float = None,
    max_tokens: int = None,
) -> AsyncIterator[str]:
    if _is_quota_exhausted():
        raise RuntimeError("AI quota cooldown active")
    client = get_ai_client()
    temperature = temperature if temperature is not None else settings.OPENAI_TEMPERATURE
    max_tokens = max_tokens or settings.OPENAI_MAX_TOKENS

    full_messages = [{"role": "system", "content": system_prompt}] + messages

    try:
        async with _request_gate:
            stream = await client.chat.completions.create(
                model=get_model(),
                messages=full_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except Exception as e:
        if _is_quota_error(e):
            _mark_quota_exhausted()
        logger.error("ai_streaming_failed", error=str(e))
        raise


async def extract_facts_from_conversation(messages: List[dict], language: str = "en") -> dict:
    if _is_quota_exhausted():
        return {}
    system = """Extract key facts about the customer from this conversation.
Return ONLY valid JSON with these keys:
- budget_min: number or null
- budget_max: number or null  
- use_case: string or null (e.g. "wordpress", "game server", "e-commerce")
- tech_level: one of ["beginner", "intermediate", "expert"] or null
- team_size: number or null
- current_provider: string or null
- pain_points: list of strings
- preferred_os: string or null
- location_mentioned: string or null
- timeline: string or null (e.g. "urgent", "within a week", "exploring")
"""
    try:
        conv_text = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in messages[-20:]])
        result, _ = await generate_reply(
            [{"role": "user", "content": conv_text}],
            system,
            temperature=0.1,
            max_tokens=400,
        )
        import json, re
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        logger.warning("fact_extraction_failed", error=str(e))
    return {}


async def check_ai_health() -> bool:
    if _is_quota_exhausted():
        return False
    try:
        client = get_ai_client()
        async with _request_gate:
            await client.chat.completions.create(
                model=get_model(),
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
        return True
    except Exception as e:
        if _is_quota_error(e):
            _mark_quota_exhausted()
        logger.error("ai_health_check_failed", error=str(e))
        return False
