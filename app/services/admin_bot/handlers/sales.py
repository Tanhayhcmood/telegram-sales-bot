from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from app.db.session import AsyncSessionLocal
from app.models.lead import Lead
from app.models.customer import Customer
from sqlalchemy import select, func, and_, desc
from app.services.admin_bot.keyboards import back_kb, sales_kb
from datetime import datetime, timezone, timedelta

router = Router()


@router.message(Command("sales"))
@router.callback_query(F.data == "sales")
async def show_sales(event: Message | CallbackQuery):
    msg = event if isinstance(event, Message) else event.message

    async with AsyncSessionLocal() as session:
        total = (await session.execute(select(func.count(Lead.id)))).scalar() or 0
        # FIX: always pass a column to func.count() to avoid ambiguous SELECT count(*) in SQLAlchemy 2.x
        new = (await session.execute(select(func.count(Lead.id)).where(Lead.status == "new"))).scalar() or 0
        qualified = (await session.execute(select(func.count(Lead.id)).where(Lead.status == "qualified"))).scalar() or 0
        negotiating = (await session.execute(select(func.count(Lead.id)).where(Lead.status == "negotiating"))).scalar() or 0
        won = (await session.execute(select(func.count(Lead.id)).where(Lead.status == "closed_won"))).scalar() or 0
        lost = (await session.execute(select(func.count(Lead.id)).where(Lead.status == "closed_lost"))).scalar() or 0

        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        week_leads = (await session.execute(
            select(func.count(Lead.id)).where(Lead.created_at >= week_ago)
        )).scalar() or 0

        hot_leads = (await session.execute(
            select(func.count(Lead.id)).where(
                and_(Lead.score >= 0.6, Lead.status.notin_(["closed_won", "closed_lost"]))
            )
        )).scalar() or 0

    conversion = round((won / (won + lost) * 100), 1) if (won + lost) > 0 else 0
    pipeline_active = new + qualified + negotiating

    funnel = _draw_funnel(new, qualified, negotiating, won)

    text = (
        "🎯 *Sales Pipeline*\n\n"
        f"🔥 Hot leads (score ≥ 60%): `{hot_leads}`\n"
        f"📅 New leads this week: `{week_leads}`\n\n"
        f"*Pipeline:*\n{funnel}\n\n"
        f"📊 *Summary*\n"
        f"📋 Total leads: `{total}`\n"
        f"🟢 Active pipeline: `{pipeline_active}`\n"
        f"🏆 Closed won: `{won}`\n"
        f"❌ Closed lost: `{lost}`\n"
        f"📊 Conversion rate: `{conversion}%`\n"
    )

    await msg.answer(text, parse_mode="Markdown", reply_markup=sales_kb())
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.callback_query(F.data == "sales_hot")
async def show_hot_leads(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Lead, Customer)
            .join(Customer, Lead.customer_id == Customer.id)
            .where(
                and_(
                    Lead.score >= 0.6,
                    Lead.status.notin_(["closed_won", "closed_lost"]),
                )
            )
            .order_by(desc(Lead.score))
            .limit(10)
        )
        rows = result.all()

    if not rows:
        await callback.message.answer("😔 No hot leads right now.", reply_markup=back_kb())
        await callback.answer()
        return

    lines = ["🔥 *Hot Leads (Score ≥ 60%)*\n"]
    for lead, customer in rows:
        name = customer.display_name or customer.username or f"ID:{customer.telegram_id}"
        score_bar = "🔴" if lead.score >= 0.85 else ("🟠" if lead.score >= 0.7 else "🟡")
        budget = f"${lead.budget_max:.0f}" if lead.budget_max else "?"
        lines.append(
            f"{score_bar} *{name}*\n"
            f"   Service: {lead.service_type} | Budget: {budget}/mo\n"
            f"   Score: {lead.score:.0%} | Status: {lead.status}\n"
        )

    await callback.message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=back_kb())
    await callback.answer()


@router.callback_query(F.data == "sales_pipeline")
async def show_pipeline(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        # FIX: always specify Lead.id in func.count()
        vps = (await session.execute(select(func.count(Lead.id)).where(
            and_(Lead.service_type == "vps", Lead.status.notin_(["closed_won", "closed_lost"]))
        ))).scalar() or 0
        cloud = (await session.execute(select(func.count(Lead.id)).where(
            and_(Lead.service_type == "cloud", Lead.status.notin_(["closed_won", "closed_lost"]))
        ))).scalar() or 0
        dedicated = (await session.execute(select(func.count(Lead.id)).where(
            and_(Lead.service_type == "dedicated", Lead.status.notin_(["closed_won", "closed_lost"]))
        ))).scalar() or 0
        general = (await session.execute(select(func.count(Lead.id)).where(
            and_(Lead.service_type == "general", Lead.status.notin_(["closed_won", "closed_lost"]))
        ))).scalar() or 0

        avg_score = (await session.execute(
            select(func.avg(Lead.score)).where(Lead.status.notin_(["closed_won", "closed_lost"]))
        )).scalar() or 0

    text = (
        "📊 *Pipeline by Service*\n\n"
        f"🖥 VPS: `{vps}` leads\n"
        f"☁️ Cloud: `{cloud}` leads\n"
        f"⚡ Dedicated: `{dedicated}` leads\n"
        f"❓ General: `{general}` leads\n\n"
        f"📈 Average lead score: `{avg_score:.0%}`\n"
    )

    await callback.message.answer(text, parse_mode="Markdown", reply_markup=back_kb())
    await callback.answer()


def _draw_funnel(new: int, qualified: int, negotiating: int, won: int) -> str:
    stages = [
        ("🆕 New", new),
        ("✔️ Qualified", qualified),
        ("🤝 Negotiating", negotiating),
        ("🏆 Won", won),
    ]
    lines = []
    for label, count in stages:
        bar = "▓" * min(count, 20)
        lines.append(f"{label}: {bar} `{count}`")
    return "\n".join(lines)
