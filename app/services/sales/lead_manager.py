from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.lead import Lead
from app.models.customer import Customer
from app.cache.redis_client import cache_set, cache_get
from app.core.logging import get_logger
import uuid
from datetime import datetime, timezone

logger = get_logger(__name__)


async def get_or_create_lead(
    session: AsyncSession,
    customer: Customer,
    account_id: uuid.UUID,
    classification: dict,
) -> Lead:
    cache_key = f"lead:active:{customer.id}"
    cached_id = await cache_get(cache_key)

    if cached_id:
        result = await session.execute(select(Lead).where(Lead.id == uuid.UUID(cached_id)))
        lead = result.scalar_one_or_none()
        if lead and lead.status not in ("closed_won", "closed_lost"):
            new_score = _calculate_lead_score(classification)
            if new_score > lead.score:
                lead.score = new_score
                lead.requirements = {**(lead.requirements or {}), **classification}
                if classification.get("service_interest") not in ("none", "general", None):
                    lead.service_type = classification["service_interest"]
                if classification.get("budget_max") and (not lead.budget_max or classification["budget_max"] > lead.budget_max):
                    lead.budget_max = classification["budget_max"]
                if classification.get("budget_min"):
                    lead.budget_min = classification["budget_min"]
            return lead

    lead = Lead(
        customer_id=customer.id,
        account_id=account_id,
        service_type=classification.get("service_interest", "general"),
        budget_min=classification.get("budget_min"),
        budget_max=classification.get("budget_max"),
        requirements=classification,
        status="new",
        score=_calculate_lead_score(classification),
    )
    session.add(lead)
    await session.flush()
    await cache_set(cache_key, str(lead.id), ttl=86400 * 7)
    logger.info("lead_created", lead_id=str(lead.id), customer_id=str(customer.id), score=lead.score)
    return lead


async def update_lead_score(
    session: AsyncSession,
    lead_id: uuid.UUID,
    delta: float = 0.05,
) -> None:
    result = await session.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if lead:
        lead.score = min(1.0, (lead.score or 0.0) + delta)


async def update_lead_status(
    session: AsyncSession,
    lead_id: uuid.UUID,
    status: str,
    notes: str = None,
) -> None:
    result = await session.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if lead:
        lead.status = status
        if notes:
            lead.notes = notes
        if status in ("closed_won", "closed_lost"):
            lead.closed_at = datetime.now(timezone.utc)


def _calculate_lead_score(classification: dict) -> float:
    score = 0.0

    readiness_scores = {
        "ready_to_buy": 0.40,
        "considering": 0.25,
        "exploring": 0.10,
        "not_interested": 0.0,
    }
    score += readiness_scores.get(classification.get("purchase_readiness", "exploring"), 0.10)

    if classification.get("budget_mentioned"):
        score += 0.15

    service = classification.get("service_interest", "general")
    if service == "dedicated":
        score += 0.15
    elif service == "cloud":
        score += 0.12
    elif service == "vps":
        score += 0.08

    urgency_scores = {"critical": 0.20, "high": 0.15, "medium": 0.08, "low": 0.0}
    score += urgency_scores.get(classification.get("urgency", "low"), 0.0)

    sentiment = classification.get("sentiment", "neutral")
    if sentiment in ("very_positive", "positive"):
        score += 0.05
    elif sentiment in ("negative", "very_negative"):
        score -= 0.05

    if classification.get("use_case"):
        score += 0.05

    if classification.get("tech_level") == "expert":
        score += 0.05

    if classification.get("competitor_mentioned"):
        score += 0.08

    intent = classification.get("intent", "inquiry")
    if intent == "negotiation":
        score += 0.10
    elif intent == "sales":
        score += 0.07
    elif intent == "comparison":
        score += 0.05

    return round(min(score, 1.0), 3)
