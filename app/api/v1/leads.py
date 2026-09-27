from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, desc
from app.api.deps import DBSession, APIKeyDep
from app.models.lead import Lead
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid

router = APIRouter(prefix="/leads", tags=["leads"])


class LeadOut(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    service_type: str
    budget_min: Optional[float]
    budget_max: Optional[float]
    recommended_plan: Optional[str]
    status: str
    score: float
    notes: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}


class LeadUpdateIn(BaseModel):
    status: Optional[str] = None
    recommended_plan: Optional[str] = None
    notes: Optional[str] = None
    score: Optional[float] = None


@router.get("", response_model=list[LeadOut])
async def list_leads(
    _: APIKeyDep,
    session: DBSession,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, le=100),
    status: Optional[str] = None,
):
    q = select(Lead).order_by(desc(Lead.created_at))
    if status:
        q = q.where(Lead.status == status)
    result = await session.execute(q.offset(skip).limit(limit))
    return result.scalars().all()


@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead(_: APIKeyDep, session: DBSession, lead_id: uuid.UUID):
    result = await session.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(_: APIKeyDep, session: DBSession, lead_id: uuid.UUID, body: LeadUpdateIn):
    result = await session.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(lead, field, value)
    await session.commit()
    await session.refresh(lead)
    return lead
