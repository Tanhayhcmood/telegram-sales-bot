from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, desc
from app.api.deps import DBSession, APIKeyDep
from app.models.conversation import Conversation, Message
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationOut(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    account_id: uuid.UUID
    status: str
    summary: Optional[str]
    sentiment: str
    intent: str
    language: str
    started_at: datetime
    closed_at: Optional[datetime]
    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: uuid.UUID
    direction: str
    content: str
    ai_generated: bool
    tokens_used: int
    sent_at: datetime
    model_config = {"from_attributes": True}


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    _: APIKeyDep,
    session: DBSession,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, le=100),
    status: Optional[str] = None,
    customer_id: Optional[uuid.UUID] = None,
):
    q = select(Conversation).order_by(desc(Conversation.started_at))
    if status:
        q = q.where(Conversation.status == status)
    if customer_id:
        q = q.where(Conversation.customer_id == customer_id)
    result = await session.execute(q.offset(skip).limit(limit))
    return result.scalars().all()


@router.get("/{conv_id}/messages", response_model=list[MessageOut])
async def get_messages(_: APIKeyDep, session: DBSession, conv_id: uuid.UUID):
    result = await session.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.sent_at)
    )
    return result.scalars().all()


@router.patch("/{conv_id}/close")
async def close_conversation(_: APIKeyDep, session: DBSession, conv_id: uuid.UUID):
    from datetime import timezone
    result = await session.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.status = "closed"
    conv.closed_at = datetime.now(timezone.utc)
    await session.commit()
    return {"status": "closed"}
