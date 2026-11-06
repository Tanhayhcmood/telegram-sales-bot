"""Auto-poster for localized VPS promotions.

Public posts are generic marketing copy and never use scanner results or
contain server addresses, usernames, passwords, or connection instructions.
"""
import asyncio
import os
import hashlib
import io
import random
import time as _time
import uuid
from collections import deque
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, func
from app.db.session import AsyncSessionLocal
from app.models.channel import TelegramChannel
from app.models.post import Post
from app.services.channel.publisher import publish_post
from app.cache.redis_client import get_redis
from app.core.logging import get_logger

logger = get_logger(__name__)

TEHRAN = ZoneInfo("Asia/Tehran")

# Publish one synchronized batch every six hours after a successful cycle.
AUTO_POST_INTERVAL_HOURS = 6
MIN_INTERVAL_SECONDS = AUTO_POST_INTERVAL_HOURS * 3600
COOLDOWN_SECONDS = MIN_INTERVAL_SECONDS

# If any channel's cooldown expires within this window, wait for it so all
# channels post in a single synchronised batch instead of drifting apart.
SYNC_WINDOW_SECONDS = 300    # 5 minutes — reduced from 20 min to prevent post bunching


def _cooldown_key(channel_id: str) -> str:
    return f"autoposter:cooldown:{channel_id}"


async def _get_db_auto_post_remaining(channel_id: str) -> int:
    """Read the authoritative last VPS post time from PostgreSQL.

    This deliberately does not depend on Redis, which may be fakeredis on Render."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(
                    Post.published_at, Post.channel_ids, Post.content_type, Post.image_url,
                )
                .where(
                    Post.status == "published",
                    Post.published_at.is_not(None),
                )
                .order_by(Post.published_at.desc())
                .limit(1000)
            )
            now = _time.time()
            for published_at, channel_ids, content_type, image_url in result.all():
                ids = {str(value) for value in (channel_ids or [])}
                image_marker = str(image_url or "").lower()
                is_auto_post = content_type == "rdp" or "rdp" in image_marker
                if not is_auto_post or channel_id not in ids:
                    continue
                remaining = max(0, int(COOLDOWN_SECONDS - (now - published_at.timestamp())))
                if remaining > 0:
                    return remaining
                return 0
    except Exception as exc:
        logger.warning("autoposter_db_cooldown_read_failed", channel_id=channel_id, error=str(exc)[:160])
    return 0


async def get_cooldown_remaining(channel_id: str) -> int:
    # PostgreSQL is authoritative. Redis can only add a conservative delay,
    # never make a channel eligible earlier than its database timestamp.
    db_remaining = await _get_db_auto_post_remaining(channel_id)
    if db_remaining > 0:
        return db_remaining
    try:
        from app.cache.redis_client import cache_get
        val = await cache_get(_cooldown_key(channel_id))
        if val:
            posted_at = float(val)
            return max(0, int(COOLDOWN_SECONDS - (_time.time() - posted_at)))
    except Exception as exc:
        logger.warning("autoposter_cache_cooldown_read_failed", channel_id=channel_id, error=str(exc)[:120])
    return 0

def _lock_key(channel_id: str) -> str:
    return f"autoposter:lock:{channel_id}"


async def acquire_channel_lock(channel_id: str, ttl: int = 60) -> bool:
    """
    Try to acquire a short-lived distributed lock for a channel post.
    Returns True if the lock was acquired (caller may post).
    Returns False if another process is already posting to this channel.
    Uses Redis SET NX (atomic) to prevent duplicate concurrent posts.
    """
    try:
        r = await get_redis()
        acquired = await r.set(_lock_key(channel_id), "1", nx=True, ex=ttl)
        return bool(acquired)
    except Exception as e:
        logger.warning("channel_lock_acquire_failed", channel_id=channel_id, error=str(e)[:60])
        # If Redis fails, allow posting (better than silent drop)
        return True


async def release_channel_lock(channel_id: str) -> None:
    try:
        r = await get_redis()
        await r.delete(_lock_key(channel_id))
    except Exception:
        pass


async def mark_channel_posted(channel_id: str) -> None:
    from app.cache.redis_client import cache_set
    await cache_set(_cooldown_key(channel_id), str(_time.time()), ttl=COOLDOWN_SECONDS + 300)
    _last_post_time[channel_id] = asyncio.get_running_loop().time()


_recent_hashes: deque = deque(maxlen=300)
_last_post_time: dict[str, float] = {}
_post_mode: dict[str, str] = {}


def _toggle_post_mode(channel_id: str) -> None:
    """Toggle next post mode between 'text' and 'media' for a channel."""
    current = _post_mode.get(channel_id, "text")
    _post_mode[channel_id] = "media" if current == "text" else "text"


def _content_hash(text: str) -> str:
    return hashlib.sha1(text.strip().lower().encode()).hexdigest()[:16]


def _is_duplicate(content: str) -> bool:
    return _content_hash(content) in _recent_hashes


def _record_hash(content: str) -> None:
    _recent_hashes.append(_content_hash(content))


async def _post_to_channel(userbot_manager, channel: TelegramChannel) -> bool:
    """Post a generic VPS promotion without scanning or publishing access data."""
    del userbot_manager
    return await _post_vps_promo_to_channel(channel)


async def _post_rdp_result_to_channel(rdp_result: dict, channel: TelegramChannel) -> bool:
    """Legacy adapter that intentionally discards scanner results."""
    del rdp_result
    return await _post_vps_promo_to_channel(channel)


async def _post_vps_promo_to_channel(channel: TelegramChannel) -> bool:
    """Publish a localized, redacted VPS promotion to one channel."""
    ch_id = str(channel.id)
    if not await acquire_channel_lock(ch_id, ttl=90):
        logger.info("vps_promo_skipped_locked", channel=channel.display_name)
        return False

    try:
        from app.core.config import settings
        from app.services.content.rdp_post_builder import build_vps_promo_post

        language = channel.language or "en"
        promo_content, promo_image_url = build_vps_promo_post(
            language=language,
            location=settings.VPS_PROMO_LOCATION,
            admin_username=settings.POST_ADMIN_USERNAME,
            seed=random.randint(0, 9_999_999),
        )
        if _is_duplicate(promo_content):
            logger.info("vps_promo_duplicate_skipping", channel=channel.display_name)
            return False

        async with AsyncSessionLocal() as session:
            post = Post(
                account_id=channel.account_id,
                channel_ids=[ch_id],
                content=promo_content,
                languages={language: promo_content},
                image_url=promo_image_url,
                content_type="rdp",
                status="scheduled",
                scheduled_at=datetime.now(timezone.utc),
            )
            session.add(post)
            await session.flush()
            try:
                pub_results = await publish_post(session, post)
                published_count = sum(
                    1 for result in pub_results.values()
                    if result.get("status") == "published"
                )
                await session.commit()
                if not published_count:
                    logger.warning(
                        "vps_promo_publish_no_success",
                        channel=channel.display_name,
                        results=pub_results,
                    )
                    return False

                _record_hash(promo_content)
                logger.info("vps_promo_post_sent", channel=channel.display_name, language=language)
                return True
            except Exception as exc:
                post.status = "failed"
                await session.commit()
                logger.error("vps_promo_send_failed", channel=channel.display_name, error=str(exc))
                return False
    finally:
        await release_channel_lock(ch_id)


async def reset_all_cooldowns() -> int:
    """
    Delete every autoposter:cooldown:* key from Redis.
    Call this when channels are stuck because cooldowns were set erroneously
    (e.g. by the old bug that marked channels as posted even when nothing was sent).
    Returns the number of keys deleted.
    """
    try:
        r = await get_redis()
        pattern = "autoposter:cooldown:*"
        keys = []
        async for key in r.scan_iter(pattern):
            keys.append(key)
        if keys:
            await r.delete(*keys)
        logger.info("all_cooldowns_reset", deleted=len(keys))
        return len(keys)
    except Exception as e:
        logger.error("reset_all_cooldowns_failed", error=str(e))
        return 0


async def _get_active_channels(account_id=None):
    """
    Return all active channels in randomised order.

    ORDER BY RANDOM() ensures that no channel is consistently at the end of
    the posting queue across cycles. Without this, the last channels in heap
    order always absorb flood-wait errors and drift out of phase over time.
    """
    async with AsyncSessionLocal() as session:
        q = (
            select(TelegramChannel)
            .where(TelegramChannel.is_active == True)
            .order_by(func.random())
        )
        if account_id:
            q = q.where(TelegramChannel.account_id == uuid.UUID(str(account_id)))
        result = await session.execute(q)
        return result.scalars().all()


async def _compute_cooldowns(channels) -> dict[str, int]:
    """Return {channel_id: seconds_remaining} for every channel."""
    cooldowns = {}
    for ch in channels:
        cooldowns[str(ch.id)] = await get_cooldown_remaining(str(ch.id))
    return cooldowns



GLOBAL_COOLDOWN_KEY = "autoposter:global:last_posted"


async def _get_global_cooldown_remaining() -> int:
    """Return seconds until the next global auto-poster cycle is allowed.

    Uses Redis for fast lookup; falls back to PostgreSQL for persistence
    across process restarts (Redis may be ephemeral on Render free tier).
    """
    try:
        from app.cache.redis_client import cache_get
        val = await cache_get(GLOBAL_COOLDOWN_KEY)
        if val:
            last_posted = float(val)
            remaining = max(0, int(MIN_INTERVAL_SECONDS - (_time.time() - last_posted)))
            if remaining > 0:
                return remaining
    except Exception as exc:
        logger.warning("autoposter_global_redis_read_failed", error=str(exc)[:120])

    # PostgreSQL fallback — most recent published RDP post across ALL channels
    try:
        async with AsyncSessionLocal() as session:
            row = await session.scalar(
                select(Post.published_at)
                .where(
                    Post.status == "published",
                    Post.published_at.is_not(None),
                    Post.content_type == "rdp",
                )
                .order_by(Post.published_at.desc())
                .limit(1)
            )
            if row:
                return max(0, int(MIN_INTERVAL_SECONDS - (_time.time() - row.timestamp())))
    except Exception as exc:
        logger.warning("autoposter_global_db_read_failed", error=str(exc)[:160])

    return 0


async def mark_global_posted() -> None:
    """Set the global six-hour cooldown after a successful posting cycle."""
    try:
        from app.cache.redis_client import cache_set
        await cache_set(GLOBAL_COOLDOWN_KEY, str(_time.time()), ttl=MIN_INTERVAL_SECONDS + 300)
        logger.info("auto_poster_global_cooldown_set", interval_hours=MIN_INTERVAL_SECONDS // 3600)
    except Exception as exc:
        logger.warning("autoposter_global_mark_failed", error=str(exc)[:120])


async def run_auto_poster(userbot_manager):
    """
    Main auto-poster loop with a single global six-hour cooldown for ALL channels.

    When the six-hour timer expires, ALL active channels post simultaneously.
    A single global timer replaces the old per-channel timers that caused
    posts to be staggered and appear every 15-30 minutes.
    """
    if os.getenv("AUTO_POSTER_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        logger.warning("auto_poster_disabled_by_config")
        return

    logger.info("auto_poster_started", mode="global_6h_cooldown")
    await asyncio.sleep(30)

    while True:
        try:
            from app.cache.redis_client import cache_get
            if await cache_get("system:posting_paused"):
                logger.info("auto_poster_paused_sleeping_60s")
                await asyncio.sleep(60)
                continue

            # ── Global six-hour cooldown ────────────────────────────────────────
            # All channels share ONE timer. When it expires every channel posts
            # simultaneously — no per-channel drift, no staggered spamming.
            global_remaining = await _get_global_cooldown_remaining()
            if global_remaining > 0:
                sleep_secs = min(global_remaining, 900)  # wake up at most every 15 min
                logger.info(
                    "auto_poster_global_cooldown_active",
                    remaining_minutes=round(global_remaining / 60, 1),
                    sleeping_minutes=round(sleep_secs / 60, 1),
                )
                await asyncio.sleep(sleep_secs)
                continue

            # ── Cooldown expired — collect all active channels ─────────────────
            channels = await _get_active_channels()
            if not channels:
                logger.info("auto_poster_no_active_channels_sleeping_5min")
                await asyncio.sleep(300)
                continue

            logger.info("auto_poster_cycle_starting", channels=len(channels))

            # Publish a generic VPS promotion to active channels; no scanner results
            # are used as post content or as a trigger for publication.
            posted = 0
            for channel in channels:
                success = await _post_vps_promo_to_channel(channel)
                if success:
                    await mark_channel_posted(str(channel.id))
                    posted += 1
                    await asyncio.sleep(random.randint(8, 15))

            logger.info("vps_promo_cycle_done", posted=posted, total=len(channels))
            if posted > 0:
                await mark_global_posted()

            # Sleep 15 min then re-check (global cooldown blocks early posts)
            await asyncio.sleep(900)

        except asyncio.CancelledError:
            logger.info("auto_poster_cancelled")
            break
        except Exception as e:
            logger.error("auto_poster_error", error=str(e))
            await asyncio.sleep(120)
