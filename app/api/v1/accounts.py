from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from app.api.deps import DBSession, APIKeyDep
from app.models.account import TelegramAccount
from app.services.userbot.manager import userbot_manager
from pydantic import BaseModel
from typing import Optional
import uuid

router = APIRouter(prefix="/accounts", tags=["accounts"])


class AccountIn(BaseModel):
    phone: str
    session_string: Optional[str] = None
    display_name: Optional[str] = None


class AccountOut(BaseModel):
    id: uuid.UUID
    phone: str
    display_name: Optional[str]
    is_active: bool
    model_config = {"from_attributes": True}


@router.get("", response_model=list[AccountOut])
async def list_accounts(_: APIKeyDep, session: DBSession):
    result = await session.execute(select(TelegramAccount))
    return result.scalars().all()


@router.post("", response_model=AccountOut)
async def add_account(_: APIKeyDep, session: DBSession, body: AccountIn):
    existing = await session.execute(select(TelegramAccount).where(TelegramAccount.phone == body.phone))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Account already exists")

    account = TelegramAccount(
        phone=body.phone,
        session_string=body.session_string,
        display_name=body.display_name,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)

    if body.session_string:
        await userbot_manager.add_account(str(account.id), body.phone, body.session_string)

    return account


@router.get("/status")
async def accounts_status(_: APIKeyDep):
    return {"accounts": userbot_manager.list_accounts()}


@router.patch("/{account_id}/toggle")
async def toggle_account(_: APIKeyDep, session: DBSession, account_id: uuid.UUID):
    result = await session.execute(select(TelegramAccount).where(TelegramAccount.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account.is_active = not account.is_active
    await session.commit()
    return {"is_active": account.is_active}
