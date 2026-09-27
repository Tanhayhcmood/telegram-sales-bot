from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from app.models.customer import Customer, CustomerMemory
from app.models.conversation import Conversation, Message
from app.cache.redis_client import cache_get, cache_set, cache_delete
from app.core.logging import get_logger
from datetime import datetime, timezone
import uuid
import json

logger = get_logger(__name__)


async def get_customer_memory(session: AsyncSession, customer_id: uuid.UUID) -> dict:
    cache_key = f"customer_memory:{customer_id}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    result = await session.execute(
        select(CustomerMemory).where(CustomerMemory.customer_id == customer_id)
    )
    entries = result.scalars().all()
    memory = {e.key: {"value": e.value, "confidence": e.confidence} for e in entries}
    await cache_set(cache_key, memory, ttl=3600)
    return memory


async def upsert_memory(
    session: AsyncSession,
    customer_id: uuid.UUID,
    key: str,
    value: str,
    confidence: float = 1.0,
) -> None:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(CustomerMemory).where(
            CustomerMemory.customer_id == customer_id,
            CustomerMemory.key == key,
        )
    )
    entry = result.scalar_one_or_none()

    if entry:
        entry.value = value
        entry.confidence = confidence
        entry.updated_at = now
    else:
        session.add(CustomerMemory(
            customer_id=customer_id,
            key=key,
            value=value,
            confidence=confidence,
            updated_at=now,
        ))

    cache_key = f"customer_memory:{customer_id}"
    await cache_delete(cache_key)


async def upsert_memory_bulk(
    session: AsyncSession,
    customer_id: uuid.UUID,
    facts: dict,
) -> None:
    for key, value in facts.items():
        if value is not None and value != "" and value != [] and value != "null":
            str_value = json.dumps(value) if isinstance(value, (list, dict)) else str(value)
            await upsert_memory(session, customer_id, key, str_value, confidence=0.9)


async def get_recent_messages(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    limit: int = 20,
) -> list[dict]:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.sent_at.desc())
        .limit(limit)
    )
    messages = result.scalars().all()
    messages.reverse()
    return [
        {"role": "user" if m.direction == "inbound" else "assistant", "content": m.content}
        for m in messages
    ]


async def build_context_prompt(
    session: AsyncSession,
    customer: Customer,
    conversation_id: uuid.UUID,
) -> str:
    memory = await get_customer_memory(session, customer.id)

    parts = [
        f"Customer: {customer.display_name or customer.username or 'Unknown'}",
        f"Language: {customer.language_code}",
    ]

    if memory:
        priority_keys = ["use_case", "budget_max", "budget_min", "tech_level", "current_provider", "pain_points", "timeline", "preferred_os", "team_size"]
        memory_lines = []

        for key in priority_keys:
            if key in memory:
                memory_lines.append(f"  - {key}: {memory[key]['value']}")

        for key, val in memory.items():
            if key not in priority_keys:
                memory_lines.append(f"  - {key}: {val['value']}")

        if memory_lines:
            parts.append("Known Customer Facts:\n" + "\n".join(memory_lines))

    if customer.purchase_history:
        parts.append(f"Purchase History: {json.dumps(customer.purchase_history)}")

    if customer.notes:
        parts.append(f"Agent Notes: {customer.notes}")

    total_result = await session.execute(
        select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
    )
    total_msgs = total_result.scalar() or 0
    parts.append(f"Messages in this conversation: {total_msgs}")

    return "\n".join(parts)


async def get_conversation_summary(
    session: AsyncSession,
    conversation_id: uuid.UUID,
) -> str | None:
    result = await session.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = result.scalar_one_or_none()
    if conv and conv.summary:
        return conv.summary
    return None
