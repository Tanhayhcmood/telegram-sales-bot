from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_
from app.models.customer import Customer
from app.models.lead import Lead
from app.core.logging import get_logger
from datetime import datetime, timezone, timedelta

logger = get_logger(__name__)

FOLLOWUP_STAGE_DELAYS = {
    "day_1": 24,
    "day_3": 72,
    "day_7": 168,
    "day_14": 336,
}


async def get_customers_for_followup(session: AsyncSession, limit: int = 20) -> list[Customer]:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(Customer).where(
            and_(
                Customer.follow_up_status == "pending",
                Customer.follow_up_at <= now,
                Customer.is_blocked == False,
                Customer.is_spam == False,
            )
        ).limit(limit)
    )
    return list(result.scalars().all())


async def schedule_followup(
    session: AsyncSession,
    customer_id,
    stage: str = "day_1",
    delay_hours: int = None,
) -> None:
    delay = delay_hours or FOLLOWUP_STAGE_DELAYS.get(stage, 24)
    follow_up_at = datetime.now(timezone.utc) + timedelta(hours=delay)

    await session.execute(
        update(Customer)
        .where(Customer.id == customer_id)
        .values(
            follow_up_status="pending",
            follow_up_at=follow_up_at,
        )
    )
    logger.info("followup_scheduled", customer_id=str(customer_id), stage=stage, follow_up_at=follow_up_at.isoformat())


async def mark_followup_done(session: AsyncSession, customer_id) -> None:
    await session.execute(
        update(Customer)
        .where(Customer.id == customer_id)
        .values(follow_up_status="none", follow_up_at=None)
    )


async def get_customer_lead(session: AsyncSession, customer_id) -> Lead | None:
    result = await session.execute(
        select(Lead).where(
            and_(
                Lead.customer_id == customer_id,
                Lead.status.notin_(["closed_won", "closed_lost"]),
            )
        ).order_by(Lead.score.desc())
    )
    return result.scalar_one_or_none()


async def get_followup_context(session: AsyncSession, customer: Customer) -> dict:
    lead = await get_customer_lead(session, customer.id)
    return {
        "name": customer.display_name or customer.username or "there",
        "language": customer.language_code or "en",
        "service_type": lead.service_type if lead else "VPS",
        "budget_max": lead.budget_max if lead else None,
        "lead_score": lead.score if lead else 0.0,
        "lead_status": lead.status if lead else None,
    }
