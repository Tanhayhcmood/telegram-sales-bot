from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from app.db.session import AsyncSessionLocal
from app.models.conversation import Conversation, Message as ConvMessage
from app.models.customer import Customer
from sqlalchemy import select, func, and_, desc
from app.services.admin_bot.keyboards import back_kb
from datetime import datetime, timezone, timedelta

router = Router()


@router.message(Command("conversations"))
@router.callback_query(F.data == "conversations")
async def show_conversations(event: Message | CallbackQuery):
    msg = event if isinstance(event, Message) else event.message

    async with AsyncSessionLocal() as session:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)

        active_count = (await session.execute(
            select(func.count(Conversation.id)).where(Conversation.status == "active")
        )).scalar() or 0

        today_count = (await session.execute(
            select(func.count(Conversation.id)).where(Conversation.started_at >= today)
        )).scalar() or 0

        week_count = (await session.execute(
            select(func.count(Conversation.id)).where(Conversation.started_at >= week_ago)
        )).scalar() or 0

        total_count = (await session.execute(select(func.count(Conversation.id)))).scalar() or 0
        customer_count = (await session.execute(select(func.count(Customer.id)))).scalar() or 0

        positive_count = (await session.execute(
            select(func.count(Conversation.id)).where(
                and_(Conversation.sentiment == "positive", Conversation.started_at >= week_ago)
            )
        )).scalar() or 0

        negative_count = (await session.execute(
            select(func.count(Conversation.id)).where(
                and_(Conversation.sentiment == "negative", Conversation.started_at >= week_ago)
            )
        )).scalar() or 0

        total_tokens = (await session.execute(
            select(func.sum(ConvMessage.tokens_used))
        )).scalar() or 0

        ai_msgs = (await session.execute(
            select(func.count(ConvMessage.id)).where(ConvMessage.ai_generated == True)
        )).scalar() or 0

    satisfaction_score = "N/A"
    if week_count > 0:
        pos_pct = round(positive_count / week_count * 100)
        satisfaction_score = f"{pos_pct}% positive"

    text = (
        "💬 *Conversations Dashboard*\n\n"
        f"🟢 Active now: `{active_count}`\n"
        f"📅 Started today: `{today_count}`\n"
        f"📆 This week: `{week_count}`\n"
        f"📚 All-time: `{total_count}`\n"
        f"👥 Total customers: `{customer_count}`\n\n"
        f"😊 *Sentiment (this week)*\n"
        f"  Positive: `{positive_count}` | Negative: `{negative_count}`\n"
        f"  Satisfaction: `{satisfaction_score}`\n\n"
        f"🤖 *AI Stats (all-time)*\n"
        f"  AI messages: `{ai_msgs:,}`\n"
        f"  Total tokens: `{total_tokens:,}`\n"
    )

    await msg.answer(text, parse_mode="Markdown", reply_markup=back_kb())
    if isinstance(event, CallbackQuery):
        await event.answer()
