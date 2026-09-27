from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, func
from app.api.deps import DBSession, APIKeyDep
from app.models.customer import Customer, CustomerMemory
from app.models.conversation import Conversation
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid

router = APIRouter(prefix="/customers", tags=["customers"])


class CustomerOut(BaseModel):
    id: uuid.UUID
    telegram_id: int
    username: Optional[str]
    display_name: Optional[str]
    language_code: str
    notes: Optional[str]
    interests: list
    follow_up_status: str
    is_blocked: bool
    is_spam: bool
    spam_score: float
    tags: list
    created_at: datetime
    model_config = {"from_attributes": True}


class CustomerUpdateIn(BaseModel):
    notes: Optional[str] = None
    interests: Optional[list[str]] = None
    follow_up_status: Optional[str] = None
    tags: Optional[list[str]] = None
    is_blocked: Optional[bool] = None


@router.get("", response_model=list[CustomerOut])
async def list_customers(
    _: APIKeyDep,
    session: DBSession,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, le=100),
    is_spam: Optional[bool] = None,
    is_blocked: Optional[bool] = None,
):
    q = select(Customer)
    if is_spam is not None:
        q = q.where(Customer.is_spam == is_spam)
    if is_blocked is not None:
        q = q.where(Customer.is_blocked == is_blocked)
    q = q.offset(skip).limit(limit)
    result = await session.execute(q)
    return result.scalars().all()


@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(_: APIKeyDep, session: DBSession, customer_id: uuid.UUID):
    result = await session.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.patch("/{customer_id}", response_model=CustomerOut)
async def update_customer(_: APIKeyDep, session: DBSession, customer_id: uuid.UUID, body: CustomerUpdateIn):
    result = await session.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(customer, field, value)
    await session.commit()
    await session.refresh(customer)
    return customer


@router.get("/{customer_id}/memory")
async def get_customer_memory(_: APIKeyDep, session: DBSession, customer_id: uuid.UUID):
    result = await session.execute(select(CustomerMemory).where(CustomerMemory.customer_id == customer_id))
    entries = result.scalars().all()
    return {e.key: {"value": e.value, "confidence": e.confidence} for e in entries}
