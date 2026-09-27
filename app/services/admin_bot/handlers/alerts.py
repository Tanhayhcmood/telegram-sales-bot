from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from app.db.session import AsyncSessionLocal
from app.models.alert import Alert
from sqlalchemy import select, update, desc, func, and_
from app.services.admin_bot.keyboards import back_kb
from datetime import datetime, timezone, timedelta

router = Router()
_bot = None


def set_bot(bot) -> None:
    global _bot
    _bot = bot


async def broadcast_alert(text: str) -> None:
    from app.core.config import settings
    if not _bot:
        return
    for admin_id in settings.admin_ids:
        try:
            await _bot.send_message(admin_id, text, parse_mode="Markdown")
        except Exception:
            pass


@router.message(Command("alerts"))
@router.callback_query(F.data == "alerts_menu")
async def show_alerts(event: Message | CallbackQuery):
    msg = event if isinstance(event, Message) else event.message

    async with AsyncSessionLocal() as session:
        unresloved_result = await session.execute(
            select(Alert)
            .where(Alert.is_resolved == False)
            .order_by(desc(Alert.created_at))
            .limit(15)
        )
        alerts = unresloved_result.scalars().all()

        critical_count = sum(1 for a in alerts if a.severity == "critical")
        warning_count = sum(1 for a in alerts if a.severity == "warning")

        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        total_week = (await session.execute(
            select(func.count(Alert.id)).where(Alert.created_at >= week_ago)
        )).scalar() or 0

    if not alerts:
        text = "✅ *No unresolved alerts!*\n\nSystem is running normally."
    else:
        lines = [
            f"🔔 *Active Alerts* (`{len(alerts)}` unresolved | {total_week} this week)\n",
            f"🔴 Critical: {critical_count} | 🟡 Warning: {warning_count}\n",
        ]
        for a in alerts[:10]:
            emoji = {"critical": "🔴", "warning": "🟡", "info": "🔵", "success": "🟢"}.get(a.severity, "⚪")
            ts = a.created_at.strftime("%m/%d %H:%M") if a.created_at else "?"
            lines.append(f"{emoji} `{ts}` [{a.type}] {a.message[:70]}")

        if len(alerts) > 10:
            lines.append(f"\n_...and {len(alerts) - 10} more_")

        text = "\n".join(lines)

    await msg.answer(text, parse_mode="Markdown", reply_markup=back_kb())
    if isinstance(event, CallbackQuery):
        await event.answer()
