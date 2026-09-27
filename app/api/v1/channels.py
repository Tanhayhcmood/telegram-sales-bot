from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from app.api.deps import DBSession, APIKeyDep
from app.models.channel import TelegramChannel
from app.services.userbot.manager import userbot_manager
from pydantic import BaseModel
from typing import Optional
import uuid

router = APIRouter(prefix="/channels", tags=["channels"])


class ChannelIn(BaseModel):
    account_id: uuid.UUID
    telegram_channel_id: int
    username: Optional[str] = None
    display_name: Optional[str] = None
    language: str = "en"


class ChannelOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    telegram_channel_id: int
    username: Optional[str]
    display_name: Optional[str]
    language: str
    is_active: bool
    post_count: int
    model_config = {"from_attributes": True}


@router.get("", response_model=list[ChannelOut])
async def list_channels(_: APIKeyDep, session: DBSession):
    result = await session.execute(select(TelegramChannel))
    return result.scalars().all()


@router.post("", response_model=ChannelOut)
async def create_channel(_: APIKeyDep, session: DBSession, body: ChannelIn):
    channel = TelegramChannel(**body.model_dump())
    session.add(channel)
    await session.commit()
    await session.refresh(channel)
    return channel


@router.post("/discover/{account_id}")
async def discover_channels(_: APIKeyDep, account_id: uuid.UUID):
    """کانال‌های اکانت رو خودکار پیدا و ثبت می‌کنه"""
    from app.services.channel.auto_discover import discover_and_register_channels
    result = await discover_and_register_channels(userbot_manager, str(account_id))
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/{channel_id}")
async def deactivate_channel(_: APIKeyDep, session: DBSession, channel_id: uuid.UUID):
    result = await session.execute(select(TelegramChannel).where(TelegramChannel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    channel.is_active = False
    await session.commit()
    return {"status": "deactivated"}
