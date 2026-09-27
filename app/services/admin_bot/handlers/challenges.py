from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import desc, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.challenge import Challenge
from app.services.challenges.public_bot import get_public_bot_username
from app.services.challenges.service import challenge_summary, create_and_publish_challenge

logger = get_logger(__name__)
router = Router()


@router.message(Command("challenge"))
async def create_challenge_command(message: Message):
    topic = (message.text or "").partition(" ")[2].strip() or "RDP security, VPS reliability, and server protection"
    status_message = await message.answer("Building and publishing an English challenge to all active channels...")
    try:
        async with AsyncSessionLocal() as session:
            challenge, results = await create_and_publish_challenge(
                session,
                topic=topic[:500],
                language="en",
                public_bot_username=get_public_bot_username(),
            )
        published = sum(1 for result in results.values() if result.get("status") == "published")
        await status_message.edit_text(
            f"✅ Challenge created and published.\n\n"
            f"Title: {challenge.title}\n"
            f"Successful channels: {published}/{len(results)}\n"
            f"Bot link: `/start challenge_{challenge.slug}`\n\n"
            "View the report with /challenge_stats",
        )
    except Exception as exc:
        logger.error("manual_challenge_failed", error=str(exc))
        await status_message.edit_text(
            "❌ Challenge creation failed. Make sure at least one active channel and one connected account are available."
        )


@router.message(Command("challenge_stats"))
async def challenge_stats_command(message: Message):
    async with AsyncSessionLocal() as session:
        challenge = await session.scalar(select(Challenge).order_by(desc(Challenge.created_at)).limit(1))
        if not challenge:
            await message.answer("No challenge has been created yet.")
            return
        summary = await challenge_summary(session, challenge)
    await message.answer(
        f"📊 Latest challenge report\n\n"
        f"Title: {summary['title']}\n"
        f"Status: {summary['status']}\n"
        f"Participants: {summary['participants']}\n"
        f"Correct answers: {summary['correct_answers']}\n"
        f"Channels: {summary['channels']}\n"
        f"Ends: {summary['ends_at']}"
    )