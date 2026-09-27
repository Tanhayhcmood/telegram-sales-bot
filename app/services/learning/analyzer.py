from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.models.admin import LearningSample
from app.models.conversation import Conversation, Message
from app.services.ai.summarizer import summarize_conversation, score_conversation_quality
from app.core.config import settings
from app.core.logging import get_logger
from datetime import datetime, timezone

logger = get_logger(__name__)


async def analyze_successful_conversations(session: AsyncSession, limit: int = 15) -> int:
    result = await session.execute(
        select(Conversation).where(
            and_(
                Conversation.status == "closed",
                Conversation.sentiment.in_(["positive", "very_positive"]),
            )
        ).order_by(Conversation.started_at.desc()).limit(limit)
    )
    conversations = result.scalars().all()

    samples_created = 0
    for conv in conversations:
        existing = await session.execute(
            select(LearningSample).where(LearningSample.conversation_id == conv.id)
        )
        if existing.scalar_one_or_none():
            continue

        msg_result = await session.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.sent_at)
        )
        messages = msg_result.scalars().all()

        if len(messages) < 4:
            continue

        msg_dicts = [
            {"role": "user" if m.direction == "inbound" else "assistant", "content": m.content}
            for m in messages
        ]

        quality_score, quality_reason = await score_conversation_quality(msg_dicts)

        if quality_score < 0.4:
            logger.info("conversation_skipped_low_quality", conv_id=str(conv.id), score=quality_score)
            continue

        summary = await summarize_conversation(msg_dicts)

        inbound = [m for m in messages if m.direction == "inbound"]
        outbound = [m for m in messages if m.direction == "outbound" and m.ai_generated]

        if not (inbound and outbound):
            continue

        best_pair = _find_best_exchange(inbound, outbound)
        if not best_pair:
            continue

        user_msg, ai_msg = best_pair

        session.add(LearningSample(
            conversation_id=conv.id,
            prompt=user_msg.content,
            response=ai_msg.content,
            quality_score=quality_score,
            is_approved=quality_score >= settings.LEARNING_AUTO_APPROVE_THRESHOLD,
        ))
        samples_created += 1

    await session.commit()
    logger.info("learning_samples_created", count=samples_created)
    return samples_created


def _find_best_exchange(inbound: list, outbound: list) -> tuple | None:
    if not inbound or not outbound:
        return None

    best_user = max(inbound, key=lambda m: len(m.content))

    if best_user.sent_at:
        candidates = [
            m for m in outbound
            if m.sent_at and m.sent_at > best_user.sent_at
        ]
        if candidates:
            ai_response = min(candidates, key=lambda m: abs((m.sent_at - best_user.sent_at).total_seconds()))
            return best_user, ai_response

    return best_user, outbound[-1]


async def analyze_failed_conversations(session: AsyncSession, limit: int = 10) -> list[dict]:
    result = await session.execute(
        select(Conversation).where(
            and_(
                Conversation.status == "closed",
                Conversation.sentiment.in_(["negative", "very_negative"]),
            )
        ).order_by(Conversation.started_at.desc()).limit(limit)
    )
    conversations = result.scalars().all()

    patterns = []
    for conv in conversations:
        msg_result = await session.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.sent_at)
        )
        messages = msg_result.scalars().all()
        if len(messages) >= 2:
            inbound = [m for m in messages if m.direction == "inbound"]
            if inbound:
                patterns.append({
                    "conversation_id": str(conv.id),
                    "language": conv.language,
                    "message_count": len(messages),
                    "last_customer_message": inbound[-1].content[:200],
                })

    return patterns
