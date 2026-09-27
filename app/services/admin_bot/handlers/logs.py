from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from app.db.session import AsyncSessionLocal
from app.models.alert import Alert
from sqlalchemy import select, desc
from app.services.admin_bot.keyboards import back_kb, logs_kb
from datetime import datetime, timezone, timedelta

router = Router()


@router.message(Command("logs"))
@router.callback_query(F.data == "logs")
async def show_logs_menu(event: Message | CallbackQuery):
    msg = event if isinstance(event, Message) else event.message
    await msg.answer("📋 *Log Center*\nSelect a log type:", parse_mode="Markdown", reply_markup=logs_kb())
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.callback_query(F.data == "logs_errors")
async def show_error_logs(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Alert)
            .where(Alert.severity.in_(["critical", "warning"]))
            .order_by(desc(Alert.created_at))
            .limit(15)
        )
        alerts = result.scalars().all()

    if not alerts:
        await callback.message.answer("✅ No recent errors.", reply_markup=back_kb())
        await callback.answer()
        return

    lines = ["❌ *Recent Error & Warning Logs*\n"]
    for a in alerts:
        emoji = "🔴" if a.severity == "critical" else "🟡"
        ts = a.created_at.strftime("%m/%d %H:%M") if a.created_at else "?"
        resolved = " ✅" if a.is_resolved else ""
        lines.append(f"{emoji} `{ts}` [{a.type}] {a.message[:80]}{resolved}")

    await callback.message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=back_kb())
    await callback.answer()


@router.callback_query(F.data == "logs_daily")
async def show_daily_report(callback: CallbackQuery):
    from app.services.monitoring.metrics_collector import get_daily_stats, get_cached_metrics
    stats = await get_daily_stats()
    metrics = await get_cached_metrics()

    msgs_in = stats.get("messages_received", 0)
    msgs_out = stats.get("messages_sent", 0)
    response_rate = f"{round(msgs_out / msgs_in * 100)}%" if msgs_in > 0 else "N/A"

    text = (
        f"📊 *Daily Report — {stats.get('date', 'Today')}*\n\n"
        f"📩 Messages received: `{msgs_in}`\n"
        f"📤 Messages sent: `{msgs_out}` (response rate: {response_rate})\n"
        f"👤 New customers: `{stats.get('new_customers', 0)}`\n"
        f"📢 Posts published: `{stats.get('posts_published', 0)}`\n"
        f"🎯 Leads created: `{stats.get('leads_created', 0)}`\n"
        f"📤 Follow-ups sent: `{stats.get('followups_sent', 0)}`\n"
        f"🤖 AI tokens used: `{stats.get('tokens_used', 0):,}`\n"
        f"❌ Errors: `{stats.get('errors', 0)}`\n\n"
        f"🖥 CPU: `{metrics.get('cpu_percent', 0):.1f}%` | RAM: `{metrics.get('ram', {}).get('percent', 0):.1f}%`"
    )

    await callback.message.answer(text, parse_mode="Markdown", reply_markup=back_kb())
    await callback.answer()


@router.callback_query(F.data == "logs_weekly")
async def show_weekly_report(callback: CallbackQuery):
    from app.services.monitoring.metrics_collector import get_weekly_stats
    weekly = await get_weekly_stats()

    total_msgs = sum(d.get("messages_received", 0) for d in weekly)
    total_leads = sum(d.get("leads_created", 0) for d in weekly)
    total_customers = sum(d.get("new_customers", 0) for d in weekly)

    lines = ["📅 *Weekly Performance Report*\n"]
    for day in weekly:
        d = day["date"]
        msgs = day.get("messages_received", 0)
        leads = day.get("leads_created", 0)
        customers = day.get("new_customers", 0)
        lines.append(f"`{d}` — 📩{msgs} 🎯{leads} 👤{customers}")

    lines.append(f"\n*Totals:* 📩 {total_msgs} msgs | 🎯 {total_leads} leads | 👤 {total_customers} customers")

    await callback.message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=back_kb())
    await callback.answer()
