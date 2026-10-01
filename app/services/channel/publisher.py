import io
import os
import random
import hashlib
import asyncio
import uuid
from pathlib import Path
from datetime import datetime, timezone
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.channel import TelegramChannel
from app.models.post import Post
from app.services.monitoring.metrics_collector import increment_daily_stat
from app.services.content.rdp_post_builder import fit_rdp_caption, rdp_caption_utf16_length
from app.core.logging import get_logger

logger = get_logger(__name__)

# publisher.py lives at app/services/channel/publisher.py → 3 parents up = repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FILE_MARKER = "FILE:"

_userbot_manager = None

MAX_CAPTION_LENGTH = 1024
MAX_TEXT_LENGTH    = 4090

_URL_SEPARATOR = "|||"

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".gif"}

# ── UPGRADE TEAM brand banner ─ always sent with every channel post ────────────────
_BANNER_REL_PATH = "app/assets/upgrade_team_banner.jpg"
_CHALLENGE_BANNER_REL_PATH = "app/assets/challenge_banner.jpg"

# Admin URL for inline URL buttons (added via Bot API after userbot posts)
_ADMIN_URL = "https://t.me/vps24h"


async def _add_contact_button(channel_id: str | int, message_id: int) -> None:
    """Edit the just-sent channel post to add a Contact Admin inline URL button.
    Requires the admin bot to have 'Edit Messages' admin rights in the channel."""
    from app.core.config import settings
    bot_token = settings.ADMIN_BOT_TOKEN
    if not bot_token:
        return
    try:
        async with httpx.AsyncClient(timeout=8) as http:
            resp = await http.post(
                f"https://api.telegram.org/bot{bot_token}/editMessageReplyMarkup",
                json={
                    "chat_id": channel_id,
                    "message_id": message_id,
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "📲 Contact Admin", "url": _ADMIN_URL}]
                        ]
                    },
                },
            )
            data = resp.json()
            if not data.get("ok"):
                reason = data.get("description") or "telegram_api_error"
                # The userbot may still publish successfully when the admin bot
                # cannot edit a channel message. Treat that optional button as
                # non-fatal and avoid repeating noisy warnings for stale access.
                event = "add_contact_button_skipped" if any(
                    marker in reason.lower()
                    for marker in ("chat not found", "message to edit not found", "not enough rights")
                ) else "add_contact_button_failed"
                logger.info(event, channel_id=str(channel_id), reason=reason)
    except Exception as exc:
        logger.info("add_contact_button_skipped", channel_id=str(channel_id), reason=repr(exc))

# ── Admin signatures ─────────────────────────────────────────────────────
ADMIN_SIGNATURES = [
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n🇦️  Channel Admin  ›  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n👑  Official Admin  |  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n⚜️  Verified Admin  ·  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n🔱  Director & Admin  ›  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n💠  Channel Manager  |  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n🛡️  Head of Operations  ›  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n🏆  Authorized Admin  ·  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n📡  Admin & Publisher  |  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n🔐  Certified Admin  ›  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n⚙️  System Admin  |  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n🌐  Network Admin  ·  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n🚀  Channel Lead  ›  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n💎  Senior Admin  |  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n🎯  Operations Lead  ·  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n🔮  Channel Director  ›  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n⚡  Chief Admin  |  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n🌟  Verified Publisher  ·  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n🏅  Admin Authority  ›  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n🛰️  Broadcast Admin  |  @VPS24H",
    "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n🦥  Executive Admin  ·  @VPS24H",
]

CHANNEL_TAG_FORMATS = [
    "\n\n📢  @{username}  —  Join Our Channel",
    "\n\n📡  @{username}  |  Official Channel",
    "\n\n🔔  @{username}  ·  Subscribe Now",
    "\n\n💬  @{username}  —  Our Channel",
    "\n\n🌐  @{username}  |  Follow Us",
    "\n\n⭐  @{username}  ·  Stay Updated",
    "\n\n🚀  @{username}  —  Channel Link",
    "\n\n📣  @{username}  |  Official Feed",
    "\n\n🔗  @{username}  ·  Tap to Follow",
    "\n\n💡  @{username}  —  Main Channel",
]


def _get_admin_signature() -> str:
    return random.choice(ADMIN_SIGNATURES)


def _get_channel_tag(username: str) -> str:
    fmt = random.choice(CHANNEL_TAG_FORMATS)
    return fmt.format(username=username)


def set_userbot_manager(manager) -> None:
    global _userbot_manager
    _userbot_manager = manager


def _is_video_url(url: str) -> bool:
    lower = url.lower().split("?")[0]
    return any(lower.endswith(ext) for ext in _VIDEO_EXTENSIONS)


def _parse_image_urls(image_url: str) -> list[str]:
    if not image_url:
        return []
    return [u.strip() for u in image_url.split(_URL_SEPARATOR) if u.strip()]


def _read_local_file(rel_path: str) -> bytes | None:
    """Read a file from disk relative to the repo root. Returns None on any error."""
    try:
        full_path = _REPO_ROOT / rel_path
        return full_path.read_bytes()
    except Exception as e:
        logger.warning("local_file_read_failed", path=rel_path, error=str(e))
        return None


def _truncate_body(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    truncated = text[:limit - 3]
    last_newline = truncated.rfind("\n")
    if last_newline > limit // 2:
        truncated = truncated[:last_newline]
    return truncated + "…"


def _split_body_and_hashtags(content: str) -> tuple[str, str]:
    parts = content.rsplit("\n\n", 1)
    if len(parts) == 2 and parts[1].strip().startswith("#"):
        return parts[0], "\n\n" + parts[1].strip()
    return content, ""


def _build_post_text(
    content: str,
    channel_username: str | None,
    max_length: int,
) -> str:
    # RDP posts already contain a complete footer (@VPS24H) — don't duplicate sig
    if "@VPS24H" in content:
        return content[:max_length]
    body, hashtags = _split_body_and_hashtags(content)
    channel_tag = _get_channel_tag(channel_username) if channel_username else ""
    admin_sig = _get_admin_signature()
    footer = hashtags + channel_tag + admin_sig
    available = max(max_length - len(footer), 100)
    truncated_body = _truncate_body(body, available)
    return truncated_body + footer


async def _refresh_channel_info(client, channel: TelegramChannel) -> None:
    try:
        entity = await client.client.get_entity(channel.telegram_channel_id)
        changed = False
        username = getattr(entity, "username", None)
        if username and channel.username != username:
            channel.username = username
            changed = True
        title = getattr(entity, "title", None)
        if title and channel.display_name != title:
            channel.display_name = title
            changed = True
        if changed:
            logger.info("channel_info_refreshed", channel_id=str(channel.id),
                        username=channel.username, display_name=channel.display_name)
    except Exception as e:
        logger.warning("channel_info_refresh_failed", channel_id=str(channel.id), error=str(e))


async def _download_media_bytes(url: str, attempt: int = 1, timeout: int = 90) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            logger.info("media_download_start", url=url[:80], attempt=attempt)
            response = await client.get(url)
            response.raise_for_status()
            data = response.content
            if len(data) < 1024:
                logger.warning("media_download_too_small", size=len(data), attempt=attempt)
                return None
            logger.info("media_download_done", size_kb=len(data) // 1024,
                        content_type=response.headers.get("content-type", ""), attempt=attempt)
            return data
    except Exception as e:
        logger.warning("media_download_failed", url=url[:80], error=str(e), attempt=attempt)
        return None


async def _download_with_fallbacks(urls: list[str]) -> bytes | None:
    for i, url in enumerate(urls, start=1):
        data = await _download_media_bytes(url, attempt=i)
        if data:
            logger.info("media_download_success_on_attempt", attempt=i, total=len(urls))
            return data
        if i < len(urls):
            logger.info("media_download_trying_next_fallback", next_attempt=i + 1)
            await asyncio.sleep(2)
    logger.warning("all_media_fallbacks_failed", total_urls=len(urls))
    return None


async def _send_with_flood_retry(send_fn, *args, max_retries: int = 3, **kwargs):
    """
    Call a Telethon send function and transparently handle FloodWaitError.

    When Telegram returns FLOOD_WAIT_X (too many requests), Telethon raises
    FloodWaitError with a `.seconds` attribute indicating how long to wait.
    Without this handler, the exception propagates up, the channel gets no
    post, and — worse — all subsequent channels in the same batch also fail
    because the client remains in a flood-limited state.

    Strategy:
      - Retry up to `max_retries` times after sleeping the required wait.
      - Cap each individual wait at 120 seconds to avoid blocking too long.
      - If the flood wait exceeds 120 s, raise so the caller can record the
        failure and move on to the next channel rather than stalling the loop.
    """
    MAX_FLOOD_WAIT = 120  # seconds — refuse to wait longer than this

    for attempt in range(1, max_retries + 1):
        try:
            return await send_fn(*args, **kwargs)
        except Exception as exc:
            exc_name = type(exc).__name__
            # Telethon's FloodWaitError carries a .seconds attribute
            wait_seconds = getattr(exc, "seconds", None)
            if wait_seconds is not None:
                # This IS a FloodWaitError
                if wait_seconds > MAX_FLOOD_WAIT:
                    logger.warning(
                        "flood_wait_too_long_giving_up",
                        required_wait=wait_seconds,
                        max_allowed=MAX_FLOOD_WAIT,
                        attempt=attempt,
                    )
                    raise
                logger.warning(
                    "flood_wait_sleeping_before_retry",
                    wait_seconds=wait_seconds,
                    attempt=attempt,
                    max_retries=max_retries,
                )
                await asyncio.sleep(wait_seconds + 2)  # +2 s safety margin
                continue  # retry
            # Not a FloodWaitError — re-raise immediately
            raise
    # Exhausted retries
    raise RuntimeError(f"_send_with_flood_retry: exhausted {max_retries} retries")


async def _get_channel_client(default_client, channel: TelegramChannel, session_string: str | None):
    """
    Return (client, is_temp) where:
    - client      : a UserBotClient to use for this channel
    - is_temp     : True if we created a temporary proxied client that must be
                    disconnected after the send

    If the channel has no proxy, or the proxy is dead, falls back to
    default_client (is_temp=False).
    """
    if not channel.proxy or not channel.proxy.is_active or not channel.proxy.is_alive:
        return default_client, False

    if not session_string:
        logger.warning(
            "proxy_assigned_but_no_session_string",
            channel_id=str(channel.id),
        )
        return default_client, False

    from app.services.proxy.checker import build_telethon_proxy
    from app.services.userbot.client import UserBotClient

    proxy_tuple = build_telethon_proxy(channel.proxy)
    if not proxy_tuple:
        return default_client, False

    try:
        temp_client = UserBotClient(
            phone="proxy_temp",
            session_string=session_string,
            account_id=None,
            proxy=proxy_tuple,
        )
        connected = await temp_client.connect()
        if connected:
            logger.info(
                "proxy_client_connected",
                channel_id=str(channel.id),
                proxy_host=channel.proxy.host,
                proxy_port=channel.proxy.port,
            )
            return temp_client, True
        else:
            await temp_client.disconnect()
            logger.warning(
                "proxy_client_connect_failed_falling_back",
                channel_id=str(channel.id),
                proxy_host=channel.proxy.host,
            )
            return default_client, False
    except Exception as exc:
        logger.warning(
            "proxy_client_exception_falling_back",
            channel_id=str(channel.id),
            proxy_host=channel.proxy.host,
            error=str(exc),
        )
        return default_client, False


async def publish_post(
    session: AsyncSession,
    post: Post,
    *,
    require_media: bool = False,
) -> dict:
    """Publish a post to all of its channels.

    ``require_media`` is used by branded campaigns such as Flash Sale.  Those
    posts must never silently degrade to a text-only message: if the image
    cannot be loaded or Telegram rejects the photo, the channel is reported as
    failed instead.
    """
    if not _userbot_manager:
        logger.error("publisher_no_userbot_manager")
        return {}

    from app.cache.redis_client import cache_get
    posting_paused = await cache_get("system:posting_paused")
    if posting_paused:
        logger.info("publishing_paused_skipping")
        return {}

    results = {}
    # Bug 5 fix: normalize channel_ids from DB — JSONB may return a scalar, dict,
    # or malformed UUID string; iterate only a proper list/tuple and skip invalid entries.
    raw_ids = post.channel_ids
    if not isinstance(raw_ids, (list, tuple)):
        if raw_ids is not None:
            logger.warning("channel_ids_not_a_list", post_id=str(post.id), type=type(raw_ids).__name__)
        raw_ids = []

    channel_ids_resolved: list[uuid.UUID] = []
    for raw_id in raw_ids:
        try:
            channel_ids_resolved.append(
                uuid.UUID(raw_id) if isinstance(raw_id, str) else uuid.UUID(str(raw_id))
            )
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning("invalid_channel_id_skipped", post_id=str(post.id), raw_id=repr(raw_id), error=str(exc))

    rdp_image_path: str | None = None
    if post.content_type == "rdp":
        from app.services.content.desktop_image_generator import generate_desktop_image

        try:
            rdp_image_path = await generate_desktop_image(
                "Windows VPS desktop preview for a scheduled Telegram post",
            )
            if not rdp_image_path:
                logger.warning(
                    "rdp_desktop_image_unavailable",
                    post_id=str(post.id),
                    reason="desktop_image_generation_returned_empty_path",
                )
        except Exception as exc:
            # The image is an enhancement; never stop a scheduled text post.
            logger.error("rdp_desktop_image_generation_failed", post_id=str(post.id), error=repr(exc))

    for channel_id in channel_ids_resolved:
        result = await session.execute(
            select(TelegramChannel).where(TelegramChannel.id == channel_id)
        )
        channel = result.scalar_one_or_none()

        if not channel or not channel.is_active:
            results[str(channel_id)] = {"status": "skipped", "reason": "channel_not_found_or_inactive"}
            continue

        content = post.languages.get(channel.language) or post.content
        if not content:
            results[str(channel_id)] = {"status": "skipped", "reason": "no_content_for_language"}
            continue

        temp_client = None
        try:
            # Use channel's own account_id — not post.account_id — so channels
            # belonging to different accounts each use the correct userbot client.
            default_client = _userbot_manager.get_client(str(channel.account_id))
            if not (default_client and default_client.is_connected):
                results[str(channel_id)] = {"status": "error", "reason": "no_connected_client"}
                continue

            if not channel.username or not channel.display_name:
                await _refresh_channel_info(default_client, channel)

            # ── Resolve per-channel proxy client ─────────────────────────────────
            # eagerly load proxy relationship if it hasn't been loaded yet
            if channel.proxy_id and channel.proxy is None:
                from app.models.proxy import Proxy
                proxy_result = await session.execute(
                    select(Proxy).where(Proxy.id == channel.proxy_id)
                )
                channel.proxy = proxy_result.scalar_one_or_none()

            client, is_temp = await _get_channel_client(
                default_client,
                channel,
                default_client.session_string,
            )
            if is_temp:
                temp_client = client

            media_sent = False

            # ── Image selection (priority order) ─────────────────────────────────
            # 1. Fresh RDP desktop screenshot generated immediately before sending
            # 2. post.image_url FILE: path (e.g. flash-sale logo, uploaded image)
            # 3. Default Upgrade Team banner
            # 4. post.image_url http URL (download from web)
            # 5. Text-only fallback
            media_bytes: bytes | None = None
            media_file_name = "image.jpg"
            media_is_video = False

            if post.content_type == "rdp" and rdp_image_path:
                try:
                    media_bytes = _read_local_file(rdp_image_path)
                    media_file_name = Path(rdp_image_path).name
                    if not media_bytes:
                        raise FileNotFoundError(rdp_image_path)
                    logger.info(
                        "rdp_desktop_screenshot_generated",
                        channel_id=str(channel_id),
                        size_kb=len(media_bytes) // 1024,
                        source="pillow-local-assets",
                    )
                except Exception as exc:
                    logger.error(
                        "rdp_desktop_screenshot_failed",
                        channel_id=str(channel_id),
                        error=repr(exc),
                    )

            if (
                not media_bytes
                and post.content_type != "rdp"
                and post.image_url
                and post.image_url.startswith(_FILE_MARKER)
            ):
                rel_path = post.image_url[len(_FILE_MARKER):]
                media_bytes = _read_local_file(rel_path)
                if media_bytes:
                    media_file_name = Path(rel_path).name
                    logger.info("media_loaded_from_post_file", path=rel_path,
                                size_kb=len(media_bytes) // 1024)
                else:
                    logger.warning("post_file_image_not_found_falling_back_to_banner",
                                   path=rel_path, channel_id=str(channel_id))

            if not media_bytes and post.content_type != "rdp":
                banner_path = _CHALLENGE_BANNER_REL_PATH if post.content_type == "challenge" else _BANNER_REL_PATH
                banner_name = "challenge_banner.jpg" if post.content_type == "challenge" else "upgrade_team_banner.jpg"
                media_bytes = _read_local_file(banner_path)
                if media_bytes:
                    media_file_name = banner_name
                    logger.info("media_loaded_from_banner", size_kb=len(media_bytes) // 1024)

            if (
                not media_bytes
                and post.content_type != "rdp"
                and post.image_url
                and not post.image_url.startswith(_FILE_MARKER)
            ):
                image_urls = _parse_image_urls(post.image_url)
                media_bytes = await _download_with_fallbacks(image_urls)
                if media_bytes:
                    media_is_video = _is_video_url(image_urls[0])
                    media_file_name = "video.mp4" if media_is_video else "image.jpg"

            if media_bytes:
                compacted_chars = 0
                if post.content_type == "challenge":
                    caption = content[:MAX_CAPTION_LENGTH]
                elif post.content_type == "rdp":
                    caption, compacted_chars = fit_rdp_caption(
                        content, MAX_CAPTION_LENGTH
                    )
                    if compacted_chars:
                        logger.info(
                            "rdp_caption_decorations_compacted",
                            channel_id=str(channel_id),
                            characters_removed=compacted_chars,
                            caption_utf16_length=rdp_caption_utf16_length(caption),
                        )
                else:
                    caption = _build_post_text(content, channel.username, MAX_CAPTION_LENGTH)
                file_obj = io.BytesIO(media_bytes)
                file_obj.name = media_file_name
                post_parse_mode = (
                    None if post.content_type == "challenge"
                    else "html" if post.content_type == "rdp"
                    else "md"
                )
                if media_is_video:
                    msg = await _send_with_flood_retry(
                        client.send_file,
                        channel.telegram_channel_id,
                        file_obj,
                        caption=caption,
                        parse_mode=post_parse_mode,
                        supports_streaming=True,
                    )
                else:
                    msg = await _send_with_flood_retry(
                        client.send_file,
                        channel.telegram_channel_id,
                        file_obj,
                        caption=caption,
                        parse_mode=post_parse_mode,
                    )
                await _add_contact_button(channel.telegram_channel_id, msg.id)
                if post.content_type == "rdp":
                    logger.info(
                        "rdp_post_single_message_sent",
                        channel_id=str(channel_id),
                        msg_id=msg.id,
                        caption_utf16_length=rdp_caption_utf16_length(caption),
                        has_image=True,
                        followup_message=False,
                    )
                results[str(channel_id)] = {
                    "status": "published",
                    "message_id": msg.id,
                    "has_media": True,
                    "media_type": "video" if media_is_video else "image",
                }
                media_sent = True
                logger.info(
                    "post_published_with_media",
                    channel_id=str(channel_id),
                    msg_id=msg.id,
                    file_name=media_file_name,
                    size_kb=len(media_bytes) // 1024,
                )
            else:
                media_required = require_media or post.content_type == "rdp"
                reason = "required_media_unavailable" if media_required else "all_media_sources_failed"
                logger.error(
                    "required_media_unavailable" if media_required else "all_media_sources_failed",
                    channel_id=str(channel_id),
                    image_url=post.image_url or "",
                )
                if media_required:
                    results[str(channel_id)] = {
                        "status": "error",
                        "reason": reason,
                        "has_media": False,
                        "media_type": None,
                    }
                    continue

            if not media_sent:
                text = (
                    content[:MAX_TEXT_LENGTH]
                    if post.content_type == "challenge"
                    else _build_post_text(content, channel.username, MAX_TEXT_LENGTH)
                )
                post_parse_mode = (
                    None if post.content_type == "challenge"
                    else "html" if post.content_type == "rdp"
                    else "md"
                )
                msg = await _send_with_flood_retry(
                    client.send_message,
                    channel.telegram_channel_id,
                    text,
                    parse_mode=post_parse_mode,
                )
                await _add_contact_button(channel.telegram_channel_id, msg.id)
                results[str(channel_id)] = {
                    "status": "published",
                    "message_id": msg.id,
                    "has_media": False,
                    "media_type": None,
                }
                logger.info("post_published_text_only", channel_id=str(channel_id), msg_id=msg.id)

            channel.post_count = (channel.post_count or 0) + 1
            await increment_daily_stat("posts_published")
            await asyncio.sleep(1)

        except Exception as e:
            logger.error("publish_failed", channel_id=str(channel_id), error=str(e))
            results[str(channel_id)] = {"status": "error", "reason": str(e)[:200]}
        finally:
            # Always disconnect temp proxy clients to free resources
            if temp_client is not None:
                try:
                    await temp_client.disconnect()
                except Exception:
                    pass
                temp_client = None

    published_count = sum(1 for r in results.values() if r.get("status") == "published")
    post.publish_log = results
    post.status = "published" if published_count > 0 else "failed"
    post.published_at = datetime.now(timezone.utc)

    logger.info("post_publish_complete", post_id=str(post.id),
                published=published_count, total=len(channel_ids_resolved))
    return results

