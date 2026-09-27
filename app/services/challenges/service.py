import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.account import TelegramAccount
from app.models.challenge import Challenge, ChallengeParticipant
from app.models.channel import TelegramChannel
from app.models.post import Post
from app.models.public_user import PublicUser
from app.services.challenges.generator import generate_challenge_content, pick_next_topic

logger = get_logger(__name__)


def _slugify(value: str) -> str:
    # Telegram deep-link payloads are ASCII-only in practice and capped at 64
    # bytes. Keep the identifier short regardless of the topic language.
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    prefix = (normalized[:24] or "rdp-challenge").strip("-")
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _public_start_link(slug: str, username: str | None) -> str:
    if username:
        return f"https://t.me/{username.lstrip('@')}?start=challenge_{slug}"
    return f"/start challenge_{slug}"


def _referral_code() -> str:
    return f"U{uuid.uuid4().hex[:10].upper()}"


def public_referral_link(referral_code: str, username: str | None) -> str:
    if username:
        return f"https://t.me/{username.lstrip('@')}?start=ref_{referral_code}"
    return f"/start ref_{referral_code}"


async def get_or_create_public_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    display_name: str | None,
    referral_code: str | None = None,
) -> tuple[PublicUser, bool]:
    now = datetime.now(timezone.utc)
    user = await session.scalar(select(PublicUser).where(PublicUser.telegram_id == telegram_id))
    created = False
    if user is None:
        referred_by = None
        if referral_code:
            referred_by = await session.scalar(
                select(PublicUser).where(PublicUser.referral_code == referral_code, PublicUser.telegram_id != telegram_id)
            )
        user = PublicUser(
            telegram_id=telegram_id,
            username=username,
            display_name=display_name,
            referral_code=_referral_code(),
            referred_by_id=referred_by.id if referred_by else None,
            is_active=True,
            total_points=0,
            challenge_count=0,
            correct_answers=0,
            referral_count=0,
            referral_points=0,
            last_seen_at=now,
            metadata_={"referral_code_used": referral_code} if referred_by else {},
        )
        session.add(user)
        await session.flush()
        created = True
    else:
        user.username = username
        user.display_name = display_name
        user.last_seen_at = now
    return user, created


async def accept_terms(
    session: AsyncSession,
    user: PublicUser,
) -> None:
    if user.terms_accepted_at is not None:
        return
    user.terms_accepted_at = datetime.now(timezone.utc)
    if user.referred_by_id and not (user.metadata_ or {}).get("referral_rewarded"):
        referrer = await session.scalar(select(PublicUser).where(PublicUser.id == user.referred_by_id))
        if referrer:
            referrer.referral_count += 1
            referrer.referral_points += settings.CHALLENGE_REFERRAL_POINTS
            referrer.total_points += settings.CHALLENGE_REFERRAL_POINTS
            user.metadata_ = {
                **(user.metadata_ or {}),
                "referral_rewarded": True,
                "referral_rewarded_at": datetime.now(timezone.utc).isoformat(),
            }
    await session.commit()
    await session.refresh(user)


def build_announcement(content: dict[str, Any], slug: str, username: str | None, ends_at: datetime) -> str:
    end_text = ends_at.strftime("%b %d, %H:%M UTC")
    hashtags = " ".join(content.get("hashtags", []))
    link = _public_start_link(slug, username)
    answers = content.get("answers", [])
    answer_labels = ["A", "B", "C", "D"]

    # Hard-cap lengths so the message never exceeds Telegram's 4096-char limit.
    # The link is placed BOTH near the top and at the bottom — so it's visible
    # even when users don't scroll, and survives any edge-case truncation.
    question_text = str(content.get("question", ""))[:600]
    options_block = "\n".join(
        f"   {answer_labels[i]}. {str(ans)[:90]}"
        for i, ans in enumerate(answers[:4])
    )
    reward_text = str(content.get("reward", ""))[:120]

    return (
        "⚡ NEW CHALLENGE IS LIVE — UPGRADE TEAM\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔥 {content['title']}\n\n"
        f"👉 ANSWER HERE: {link}\n\n"
        "─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─\n\n"
        f"📌 {question_text}\n\n"
        f"Choose your answer:\n{options_block}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 Prize: {reward_text}\n"
        f"⏳ Closes: {end_text}  |  One attempt per user\n"
        f"🚀 Speed matters — fastest correct wins!\n\n"
        f"{hashtags}"
    )


async def create_challenge(
    session: AsyncSession,
    topic: str = "RDP security and server performance",
    language: str = "en",
    public_bot_username: str | None = None,
) -> Challenge:
    # Force-subscription channels can be added manually without a userbot
    # account. They are valid membership-gate targets, but cannot receive
    # channel posts. Only include channels backed by an active publishing
    # account in an automatic challenge.
    channel_result = await session.execute(
        select(TelegramChannel)
        .join(TelegramAccount, TelegramAccount.id == TelegramChannel.account_id)
        .where(
            TelegramChannel.is_active.is_(True),
            TelegramAccount.is_active.is_(True),
        )
        .order_by(TelegramChannel.created_at)
    )
    channels = list(channel_result.scalars().all())

    # ── Bot-API fallback ────────────────────────────────────────────────────
    # When no userbot account/channel is set up, publish via Bot API directly
    # to every channel listed in REQUIRED_CHANNELS (the bot must be an admin
    # of those channels with "Post Messages" permission).
    use_bot_api = False
    bot_api_channels: list[str] = []
    if not channels:
        raw = (settings.REQUIRED_CHANNELS or "").strip()
        bot_api_channels = [c.strip() for c in raw.split(",") if c.strip()]
        if not bot_api_channels:
            raise RuntimeError(
                "No active publishable Telegram channels are available for a challenge. "
                "Add a channel via the admin bot OR make the public bot an admin of a channel "
                "and list it in REQUIRED_CHANNELS."
            )
        use_bot_api = True
        logger.info("challenge_using_bot_api_fallback", channels=bot_api_channels)

    # Fetch recent challenge titles to pass as anti-repetition context to the AI
    recent_rows = await session.execute(
        select(Challenge.title)
        .order_by(desc(Challenge.created_at))
        .limit(20)
    )
    recent_titles = [row[0] for row in recent_rows.all() if row[0]]

    content = await generate_challenge_content(topic, "en", recent_titles=recent_titles)
    now = datetime.now(timezone.utc)
    ends_at = now + timedelta(hours=settings.CHALLENGE_DURATION_HOURS)
    slug = _slugify(topic)

    if use_bot_api:
        challenge = Challenge(
            slug=slug,
            title=content["title"],
            topic=topic,
            announcement="",
            question=content["question"],
            learning_note=content.get("learning_note"),
            answers=content["answers"],
            correct_answer=content["correct_answer"],
            hashtags=content["hashtags"],
            seo_keywords=content["seo_keywords"],
            reward=content["reward"],
            channel_ids=bot_api_channels,
            language="en",
            status="active",
            starts_at=now,
            ends_at=ends_at,
            winner_count=3,
            metadata_={
                "account_id": "bot_api",
                "generated_by": "xai",
                "bot_api_channels": bot_api_channels,
            },
        )
    else:
        account_result = await session.execute(
            select(TelegramAccount).where(
                TelegramAccount.id == channels[0].account_id,
                TelegramAccount.is_active.is_(True),
            )
        )
        account = account_result.scalar_one_or_none()
        if not account:
            raise RuntimeError("No active Telegram account owns the configured channels")

        challenge = Challenge(
            slug=slug,
            title=content["title"],
            topic=topic,
            announcement="",
            question=content["question"],
            learning_note=content.get("learning_note"),
            answers=content["answers"],
            correct_answer=content["correct_answer"],
            hashtags=content["hashtags"],
            seo_keywords=content["seo_keywords"],
            reward=content["reward"],
            channel_ids=[str(channel.id) for channel in channels],
            language="en",
            status="active",
            starts_at=now,
            ends_at=ends_at,
            winner_count=3,
            metadata_={"account_id": str(account.id), "generated_by": "xai"},
        )

    challenge.announcement = build_announcement(content, slug, public_bot_username, ends_at)
    session.add(challenge)
    await session.flush()
    return challenge


async def _publish_via_bot_api(session: AsyncSession, challenge: Challenge) -> dict:
    """Publish a challenge announcement directly via Bot API (no userbot needed).

    The bot (public bot token, or admin bot as fallback) must be an admin of
    each target channel with the 'Post Messages' permission.
    """
    import httpx

    bot_api_channels: list[str] = (challenge.metadata_ or {}).get(
        "bot_api_channels", challenge.channel_ids or []
    )
    token = settings.TELEGRAM_PUBLIC_BOT_TOKEN or settings.ADMIN_BOT_TOKEN
    if not token:
        raise RuntimeError("No Bot API token available for challenge publishing")

    results: dict[str, Any] = {}
    published = 0

    async with httpx.AsyncClient(timeout=30) as http:
        for channel_id in bot_api_channels:
            try:
                resp = await http.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": channel_id,
                        "text": challenge.announcement,
                        "disable_web_page_preview": True,
                    },
                )
                data = resp.json()
                if data.get("ok"):
                    results[channel_id] = {
                        "status": "published",
                        "message_id": data["result"]["message_id"],
                    }
                    published += 1
                    logger.info("bot_api_challenge_sent", channel=channel_id)
                else:
                    err = data.get("description", "unknown error")
                    results[channel_id] = {"status": "failed", "error": err}
                    logger.warning("bot_api_publish_failed", channel=channel_id, error=err)
            except Exception as exc:
                results[channel_id] = {"status": "error", "error": str(exc)}
                logger.error("bot_api_publish_error", channel=channel_id, error=str(exc))

    challenge.published_at = datetime.now(timezone.utc)
    challenge.metadata_ = {
        **(challenge.metadata_ or {}),
        "published_channels": published,
    }
    if published == 0:
        challenge.status = "publish_failed"
    await session.commit()
    logger.info(
        "challenge_published_via_bot_api",
        challenge_id=str(challenge.id),
        published_channels=published,
    )
    return results


async def publish_challenge(session: AsyncSession, challenge: Challenge) -> dict:
    channel_ids = challenge.channel_ids or []
    if not channel_ids:
        raise RuntimeError("Challenge has no target channels")
    account_id = (challenge.metadata_ or {}).get("account_id")
    if not account_id:
        raise RuntimeError("Challenge has no publishing account")

    # ── Bot-API path (no userbot) ───────────────────────────────────────────
    if account_id == "bot_api":
        return await _publish_via_bot_api(session, challenge)

    # ── Userbot path ────────────────────────────────────────────────────────
    from app.services.channel.publisher import publish_post

    post = Post(
        account_id=uuid.UUID(account_id),
        content=challenge.announcement,
        content_type="challenge",
        languages={challenge.language: challenge.announcement},
        channel_ids=channel_ids,
        status="publishing",
        publish_log={"challenge_id": str(challenge.id)},
    )
    session.add(post)
    await session.flush()
    results = await publish_post(session, post)
    published = sum(1 for result in results.values() if result.get("status") == "published")
    challenge.published_at = datetime.now(timezone.utc)
    challenge.metadata_ = {**(challenge.metadata_ or {}), "post_id": str(post.id), "published_channels": published}
    if published == 0:
        challenge.status = "publish_failed"
    await session.commit()
    logger.info("challenge_published", challenge_id=str(challenge.id), published_channels=published)
    return results


async def create_and_publish_challenge(
    session: AsyncSession,
    topic: str = "RDP security and server performance",
    language: str = "en",
    public_bot_username: str | None = None,
) -> tuple[Challenge, dict]:
    challenge = await create_challenge(session, topic, language, public_bot_username)
    results = await publish_challenge(session, challenge)
    return challenge, results


async def get_active_challenge(session: AsyncSession) -> Challenge | None:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(Challenge)
        .where(
            Challenge.status == "active",
            Challenge.language == "en",
            Challenge.starts_at <= now,
            Challenge.ends_at > now,
        )
        .order_by(desc(Challenge.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def register_participant(
    session: AsyncSession,
    challenge: Challenge,
    telegram_id: int,
    username: str | None,
    display_name: str | None,
    public_user: PublicUser | None = None,
) -> ChallengeParticipant:
    result = await session.execute(
        select(ChallengeParticipant).where(
            ChallengeParticipant.challenge_id == challenge.id,
            ChallengeParticipant.telegram_id == telegram_id,
        )
    )
    participant = result.scalar_one_or_none()
    if participant is None:
        participant = ChallengeParticipant(
            challenge_id=challenge.id,
            telegram_id=telegram_id,
            username=username,
            display_name=display_name,
            joined_at=datetime.now(timezone.utc),
            public_user_id=public_user.id if public_user else None,
        )
        session.add(participant)
        if public_user:
            public_user.challenge_count += 1
        await session.commit()
        await session.refresh(participant)
    elif public_user and participant.public_user_id is None:
        participant.public_user_id = public_user.id
        await session.commit()
    return participant


async def submit_answer(
    session: AsyncSession,
    challenge: Challenge,
    participant: ChallengeParticipant,
    answer_index: int,
) -> bool:
    if participant.answer_submitted:
        return participant.answer_correct
    participant.answer_submitted = True
    participant.answer_correct = answer_index == challenge.correct_answer
    participant.points = 10 if participant.answer_correct else 0
    participant.metadata_ = {
        **(participant.metadata_ or {}),
        "answer_index": answer_index,
        "answered_at": datetime.now(timezone.utc).isoformat(),
    }
    if participant.public_user_id:
        user = await session.scalar(select(PublicUser).where(PublicUser.id == participant.public_user_id))
        if user:
            user.total_points += participant.points
            if participant.answer_correct:
                user.correct_answers += 1
    await session.commit()
    return participant.answer_correct


async def leaderboard(session: AsyncSession, challenge_id: uuid.UUID, limit: int = 10) -> list[ChallengeParticipant]:
    result = await session.execute(
        select(ChallengeParticipant)
        .where(ChallengeParticipant.challenge_id == challenge_id)
        .order_by(desc(ChallengeParticipant.points), ChallengeParticipant.created_at)
        .limit(limit)
    )
    return list(result.scalars().all())


async def challenge_summary(session: AsyncSession, challenge: Challenge) -> dict[str, Any]:
    participants = await session.scalar(
        select(func.count(ChallengeParticipant.id)).where(ChallengeParticipant.challenge_id == challenge.id)
    )
    correct = await session.scalar(
        select(func.count(ChallengeParticipant.id)).where(
            ChallengeParticipant.challenge_id == challenge.id,
            ChallengeParticipant.answer_correct.is_(True),
        )
    )
    return {
        "slug": challenge.slug,
        "title": challenge.title,
        "status": challenge.status,
        "learning_note": challenge.learning_note,
        "participants": participants or 0,
        "correct_answers": correct or 0,
        "channels": len(challenge.channel_ids or []),
        "ends_at": challenge.ends_at.isoformat(),
    }


async def run_challenge_scheduler() -> None:
    import asyncio
    from app.db.session import AsyncSessionLocal
    from app.services.challenges.public_bot import get_public_bot_username

    process_started_at = datetime.now(timezone.utc)
    startup_publish_pending = False  # Do not create a new challenge on every service restart

    logger.info(
        "challenge_scheduler_started",
        interval_hours=settings.CHALLENGE_INTERVAL_HOURS,
        duration_hours=settings.CHALLENGE_DURATION_HOURS,
        enabled=settings.CHALLENGE_AUTO_ENABLED,
        startup_publish=True,
    )

    while True:
        try:
            if settings.CHALLENGE_AUTO_ENABLED:
                async with AsyncSessionLocal() as session:
                    active = await get_active_challenge(session)
                    # The product contract requires a fresh challenge on every
                    # process start, including when the previous challenge is still active.
                    # The normal 10-hour cadence remains enforced after this startup run
                    # by the active challenge's ends_at and the due check below.
                    startup_due = bool(startup_publish_pending)

                    if startup_due:
                        # Expire the previous active challenge before publishing the
                        # startup challenge so only the new challenge accepts answers.
                        if active is not None:
                            active.status = "expired"
                            await session.flush()
                            logger.info(
                                "automatic_challenge_expired_on_startup",
                                challenge_id=str(active.id),
                            )

                        recent_rows = await session.execute(
                            select(Challenge.title).order_by(desc(Challenge.created_at)).limit(20)
                        )
                        recent_titles_for_topic = [r[0] for r in recent_rows.all() if r[0]]
                        auto_topic = pick_next_topic(recent_titles_for_topic)
                        challenge, results = await create_and_publish_challenge(
                            session,
                            topic=auto_topic,
                            language="en",
                            public_bot_username=get_public_bot_username(),
                        )
                        published = sum(
                            1 for result in results.values() if result.get("status") == "published"
                        )
                        startup_publish_pending = published == 0
                        logger.info(
                            "automatic_challenge_created_on_startup",
                            challenge_id=str(challenge.id),
                            published_channels=published,
                            retry_pending=startup_publish_pending,
                        )
                    elif not active:
                        latest = await session.scalar(select(Challenge).order_by(desc(Challenge.created_at)).limit(1))
                        due = (
                            latest is None
                            or (
                                latest.status == "publish_failed"
                                and latest.created_at
                                < datetime.now(timezone.utc) - timedelta(hours=1)
                            )
                            or latest.created_at
                            < datetime.now(timezone.utc) - timedelta(hours=settings.CHALLENGE_INTERVAL_HOURS)
                            or latest.language != "en"
                        )
                        if due:
                            # Fetch recent titles so pick_next_topic can avoid repetition
                            recent_rows = await session.execute(
                                select(Challenge.title).order_by(desc(Challenge.created_at)).limit(20)
                            )
                            recent_titles_for_topic = [r[0] for r in recent_rows.all() if r[0]]
                            auto_topic = pick_next_topic(recent_titles_for_topic)
                            challenge, _ = await create_and_publish_challenge(
                                session,
                                topic=auto_topic,
                                language="en",
                                public_bot_username=get_public_bot_username(),
                            )
                            logger.info("automatic_challenge_created", challenge_id=str(challenge.id))
                        else:
                            logger.info(
                                "automatic_challenge_not_due",
                                latest_challenge_id=str(latest.id) if latest else None,
                            )
                    else:
                        logger.info("automatic_challenge_active", challenge_id=str(active.id))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("challenge_scheduler_failed", error=str(exc))
        await asyncio.sleep(600)
