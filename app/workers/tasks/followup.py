from app.db.session import AsyncSessionLocal
from app.services.sales.followup import (
    get_customers_for_followup,
    mark_followup_done,
    get_followup_context,
    schedule_followup,
)
from app.services.userbot.manager import userbot_manager
from app.services.ai.engine import generate_reply
from app.services.ai.prompts import get_followup_message
from app.services.ai.memory import get_recent_messages, get_customer_memory
from app.models.conversation import Conversation, Message
from sqlalchemy import select, and_
from app.core.logging import get_logger
import asyncio

logger = get_logger(__name__)


async def _build_personalized_followup(customer, context: dict, session) -> str:
    language = context.get("language", "en")
    name = context.get("name", "there")
    service_type = context.get("service_type", "VPS")
    stage = "day_1"

    memory = await get_customer_memory(session, customer.id)
    memory_str = ""
    if memory:
        items = [f"- {k}: {v['value']}" for k, v in list(memory.items())[:5]]
        memory_str = "\n".join(items)

    last_conv_result = await session.execute(
        select(Conversation)
        .where(Conversation.customer_id == customer.id)
        .order_by(Conversation.started_at.desc())
        .limit(1)
    )
    last_conv = last_conv_result.scalar_one_or_none()

    recent_history = []
    if last_conv:
        recent_history = await get_recent_messages(session, last_conv.id, limit=6)

    if recent_history:
        system = f"""You are a friendly sales assistant following up with a customer.
Write a SHORT, warm, personalized follow-up message (2-3 sentences max).
Language: {language}
Customer name: {name}
Service they were interested in: {service_type}
Known facts about customer:
{memory_str}

The message must feel natural and personal. Do NOT be pushy. Do NOT repeat the exact previous offer.
Just check in warmly and offer to help."""

        recent_text = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in recent_history])
        messages = [{"role": "user", "content": f"Recent conversation:\n{recent_text}\n\nWrite the follow-up now."}]

        try:
            reply, _ = await generate_reply(messages, system, temperature=0.8, max_tokens=150)
            if reply and len(reply) > 10:
                return reply
        except Exception as e:
            logger.warning("ai_followup_generation_failed", error=str(e))

    return get_followup_message(stage, language, name=name, service_type=service_type)


async def task_process_followups(ctx) -> dict:
    try:
        async with AsyncSessionLocal() as session:
            customers = await get_customers_for_followup(session, limit=15)

        sent = 0
        failed = 0

        for customer in customers:
            accounts = userbot_manager.list_accounts()
            if not accounts:
                logger.warning("no_accounts_for_followup")
                break

            client = userbot_manager.get_client(accounts[0]["account_id"])
            if not (client and client.is_connected):
                continue

            async with AsyncSessionLocal() as session:
                context = await get_followup_context(session, customer)
                message = await _build_personalized_followup(customer, context, session)

            try:
                await client.send_message(customer.telegram_id, message)

                async with AsyncSessionLocal() as session:
                    await mark_followup_done(session, customer.id)
                    await session.commit()

                sent += 1
                logger.info("followup_sent", customer_id=str(customer.id), language=context.get("language"))
                await asyncio.sleep(2)

            except Exception as e:
                failed += 1
                logger.error("followup_send_failed", customer_id=str(customer.id), error=str(e))

        return {"status": "ok", "sent": sent, "failed": failed}
    except Exception as e:
        logger.error("followup_task_failed", error=str(e))
        return {"status": "error", "error": str(e)}
