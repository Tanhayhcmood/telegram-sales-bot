from telethon import events
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.customer import Customer
from app.models.conversation import Conversation, Message
from app.services.ai.engine import generate_reply, extract_facts_from_conversation
from app.services.ai.language import detect_language
from app.services.ai.prompts import get_system_prompt, get_objection_handler, get_objection_label
from app.services.ai.memory import (
    get_recent_messages,
    build_context_prompt,
    get_customer_memory,
    upsert_memory,
    upsert_memory_bulk,
)
from app.services.ai.classifier import classify_message
from app.services.anti_spam.detector import should_block
from app.services.sales.lead_manager import get_or_create_lead
from app.services.sales.direct_questions import (
    get_discount_reply,
    get_direct_sales_reply,
    has_customer_context_hint,
)
from app.services.sales.payment import get_payment_reply
from app.services.monitoring.metrics_collector import increment_daily_stat
from app.cache.redis_client import cache_get, cache_set
from app.cache.keys import CacheKeys
from app.core.config import settings
from app.core.logging import get_logger
from datetime import datetime, timezone
import asyncio
from difflib import SequenceMatcher
import re
import uuid
import random

logger = get_logger(__name__)

TYPING_DELAYS = {
    "short": (0.5, 1.5),
    "medium": (1.5, 3.0),
    "long": (2.5, 4.5),
}

GREETING_TRIGGERS = {
    "hi", "hello", "hey", "سلام", "درود", "مرحبا", "مرحباً",
    "merhaba", "привет", "bonjour", "hola", "hallo", "ciao", "salut",
    "olá", "ola", "你好", "こんにちは", "안녕하세요", "नमस्ते",
}

GREETING_REPLIES = {
    "fa": "سلام! سرور رو برای چی می‌خوای؛ گیم، بات یا سایت؟",
    "ar": "مرحباً! لأي استخدام تحتاج الخادم؛ لعبة أم بوت أم موقع؟",
    "tr": "Merhaba! Sunucuyu ne için kullanacaksın: oyun, bot veya site mi?",
    "ru": "Привет! Для чего нужен сервер: для игры, бота или сайта?",
    "de": "Hallo! Wofür brauchst du den Server: für ein Spiel, einen Bot oder eine Website?",
    "fr": "Salut ! Tu veux le serveur pour quoi : un jeu, un bot ou un site ?",
    "es": "¡Hola! ¿Para qué necesitas el servidor: un juego, un bot o una web?",
    "it": "Ciao! Ti serve il server per un gioco, un bot o un sito?",
    "pt": "Olá! Você precisa do servidor para um jogo, um bot ou um site?",
    "en": "Hi! What do you need the server for: a game, a bot, or a website?",
}

FALLBACK_MESSAGES = {
    "fa": (
        "پیامت رسید. برای اینکه دقیق راهنمایی‌ت کنم، سرور رو برای سایت، بات یا گیم می‌خوای؟",
        "متوجه شدم. فقط بگو چه کاری می‌خوای روی سرور انجام بدی تا گزینه مناسب رو پیشنهاد بدم.",
        "دارم درخواستت رو بررسی می‌کنم؛ استفاده اصلیت از سرور چیه؟",
    ),
    "ar": "شكراً لرسالتك 🙏 سيرد عليك أحد زملائي قريباً.",
    "tr": "Mesajınız için teşekkürler 🙏 Ekibimizden biri kısa sürede size dönecek.",
    "ru": "Спасибо за ваше сообщение 🙏 Один из наших сотрудников свяжется с вами в ближайшее время.",
    "de": "Danke für Ihre Nachricht 🙏 Ein Teammitglied wird sich bald bei Ihnen melden.",
    "fr": "Merci pour votre message 🙏 Un membre de notre équipe vous répondra bientôt.",
    "es": "Gracias por su mensaje 🙏 Un miembro de nuestro equipo le responderá pronto.",
    "it": "Grazie per il messaggio 🙏 Ti risponderò a breve.",
    "pt": "Obrigado pela mensagem 🙏 Já te respondo.",
    "nl": "Bedankt voor je bericht 🙏 Ik kom zo bij je terug.",
    "pl": "Dziękuję za wiadomość 🙏 Wkrótce odpowiem.",
    "uk": "Дякую за повідомлення 🙏 Я скоро відповім.",
    "id": "Terima kasih atas pesannya 🙏 Saya akan segera membalas.",
    "vi": "Cảm ơn bạn đã nhắn 🙏 Mình sẽ trả lời bạn sớm.",
    "ja": "メッセージありがとう 🙏 すぐに返信します。",
    "ko": "메시지 고마워요 🙏 곧 답변드릴게요.",
    "zh-cn": "谢谢你的消息 🙏 我很快回复你。",
    "zh-tw": "謝謝你的訊息 🙏 我很快回覆你。",
    "hi": "मैसेज के लिए धन्यवाद 🙏 मैं जल्द ही जवाब दूंगी।",
    "en": (
        "I got your message. What are you planning to run on the server?",
        "Got it. Is the server for a website, bot, or game?",
        "Understood. Tell me the main use case and I’ll point you to the right option.",
    ),
}


def _fallback_reply(language: str, user_id: int, text: str) -> str:
    """Keep a provider outage from producing the same canned sentence forever."""
    options = FALLBACK_MESSAGES.get(language, FALLBACK_MESSAGES["en"])
    if isinstance(options, str):
        return options
    seed = sum(ord(char) for char in text) + int(user_id)
    return options[seed % len(options)]


_GREETING_PREFIXES = (
    "سلام", "درود", "مرحبا", "مرحباً", "اهلا", "أهلا", "أهلاً",
    "hi", "hello", "hey", "hola", "bonjour", "salut", "hallo",
    "merhaba", "привет", "здравствуйте", "ciao", "olá", "ola",
    "你好", "こんにちは", "안녕하세요", "नमस्ते",
)


def _remove_repeated_greeting(reply: str, is_first_reply: bool) -> str:
    """Guarantee that a follow-up never starts with another greeting."""
    if is_first_reply or not reply:
        return reply

    alternatives = "|".join(re.escape(prefix) for prefix in _GREETING_PREFIXES)
    cleaned = re.sub(
        rf"^\s*(?:{alternatives})(?=\s|[!؟?.,:؛،\-]|$)[!؟?.,:؛،\-\s]*",
        "",
        reply,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or reply


def _repeat_tokens(text: str) -> list[str]:
    return re.findall(r"\w+", (text or "").casefold(), flags=re.UNICODE)


def _has_repeated_content(reply: str, previous_replies: list[str]) -> bool:
    """Detect copied responses without treating normal product terms as repeats."""
    current = _repeat_tokens(reply)
    if len(current) < 8:
        return False

    current_ngrams = {
        tuple(current[index:index + 5])
        for index in range(len(current) - 4)
    }

    for previous in previous_replies[-3:]:
        earlier = _repeat_tokens(previous)
        if len(earlier) < 8:
            continue

        similarity = SequenceMatcher(None, current, earlier).ratio()
        if similarity >= 0.72:
            return True

        earlier_ngrams = {
            tuple(earlier[index:index + 5])
            for index in range(len(earlier) - 4)
        }
        shared_ngrams = len(current_ngrams & earlier_ngrams)
        if (
            shared_ngrams >= 4
            and shared_ngrams / max(len(current_ngrams), 1) >= 0.18
        ):
            return True

    return False


def _count_opening_discovery_questions(previous_replies: list[str]) -> int:
    """Count discovery turns since the last plan recommendation."""
    plan_markers = ("ENTRY LEVEL", "POWER", "ELITE", "ULTRA")
    count = 0
    for reply in reversed(previous_replies):
        normalized = reply.casefold()
        if any(marker.casefold() in normalized for marker in plan_markers):
            break
        if "?" in reply or "؟" in reply:
            count += 1
    return count


def _build_model_messages(
    history: list[dict],
    current_text: str,
    limit: int,
) -> list[dict]:
    """Build a bounded, ordered chat-completions payload for one conversation."""
    previous_limit = max(limit - 1, 0)
    previous = history[-previous_limit:] if previous_limit else []
    return previous + [{"role": "user", "content": current_text}]


async def handle_private_message(event, account_id: str):
    sender = await event.get_sender()
    if not sender or sender.bot:
        return

    user_id = sender.id
    text = event.message.text or ""

    if not text.strip():
        return

    blocked, reason = await should_block(user_id, text)
    if blocked:
        logger.warning("message_blocked", user_id=user_id, reason=reason)
        return

    await increment_daily_stat("messages_received")

    text_lower = text.lower().strip()
    reply_length = "short" if len(text) < 50 else ("medium" if len(text) < 200 else "long")

    async with AsyncSessionLocal() as session:
        customer = await get_or_create_customer(session, sender, account_id)
        await session.flush()

        # Every customer message chooses the response language. This lets the
        # conversation follow a real language switch instead of staying locked
        # to the opening message.
        conv = await get_or_create_conversation(
            session,
            customer,
            account_id,
            customer.language_code or "en",
        )
        await session.flush()

        previous_messages = await get_recent_messages(session, conv.id, limit=1)
        is_new_conversation = not previous_messages
        previous_lang = conv.language or customer.language_code or "en"
        language = await detect_language(text)
        conv.language = language
        customer.language_code = language
        if language != previous_lang:
            logger.info(
                "conversation_language_switched",
                user_id=user_id,
                from_lang=previous_lang,
                to_lang=language,
            )

        # Read the persisted history before adding the current message. This
        # makes the payload sent to the model explicit: prior user/assistant
        # turns followed by the new user turn, with no accidental omission of
        # the latest message when several rows share a timestamp.
        history_before_current = await get_recent_messages(
            session,
            conv.id,
            limit=max(settings.CONVERSATION_HISTORY_LIMIT - 1, 0),
        )
        await save_message(session, conv.id, event.message.id, "inbound", text)
        await session.flush()

        # ── Greeting fast-path ─────────────────────────────────────────────
        # Pure greeting (single word/phrase): skip AI to save tokens and reply
        # instantly. We only do this when the conversation is brand new (≤1 msg).
        if is_new_conversation and text_lower.strip() in GREETING_TRIGGERS:
            msg_count_check = int(await cache_get(f"conv_msg_count:{conv.id}") or 0)
            if msg_count_check == 0:
                greeting_reply = GREETING_REPLIES.get(language, GREETING_REPLIES["en"])
                await save_message(session, conv.id, None, "outbound", greeting_reply, ai_generated=False)
                await session.commit()
                try:
                    await event.reply(greeting_reply, parse_mode="md")
                    await increment_daily_stat("messages_sent")
                    logger.info("greeting_fast_reply", user_id=user_id, language=language)
                except Exception as e:
                    logger.error("send_greeting_failed", user_id=user_id, error=str(e))
                return
        # ──────────────────────────────────────────────────────────────────

        classification = await classify_message(text, language)

        if classification.get("intent") in ("sales", "inquiry", "negotiation", "comparison"):
            await get_or_create_lead(session, customer, uuid.UUID(account_id), classification)

        if classification.get("urgency") == "critical":
            await upsert_memory(session, customer.id, "urgency_flag", "critical", confidence=1.0)

        if classification.get("use_case"):
            await upsert_memory(session, customer.id, "use_case", classification["use_case"], confidence=0.95)

        if classification.get("tech_level") and classification["tech_level"] != "unknown":
            await upsert_memory(session, customer.id, "tech_level", classification["tech_level"], confidence=0.9)

        if classification.get("budget_max") is not None:
            await upsert_memory(
                session,
                customer.id,
                "budget_max",
                str(classification["budget_max"]),
                confidence=0.9,
            )
        if classification.get("budget_min") is not None:
            await upsert_memory(
                session,
                customer.id,
                "budget_min",
                str(classification["budget_min"]),
                confidence=0.9,
            )
        if classification.get("team_size"):
            await upsert_memory(
                session,
                customer.id,
                "team_size",
                str(classification["team_size"]),
                confidence=0.9,
            )

        if classification.get("competitor_mentioned"):
            await upsert_memory(session, customer.id, "competitor", classification["competitor_mentioned"], confidence=1.0)

        context_prompt = await build_context_prompt(session, customer, conv.id)
        known_facts = await get_customer_memory(session, customer.id)
        discovery_completed = any(
            known_facts.get(key, {}).get("value")
            for key in ("use_case", "budget_max", "budget_min", "team_size")
        )

        objection_hint = ""
        if classification.get("objection_type") and classification["objection_type"] != "none":
            handler = get_objection_handler(classification["objection_type"], language)
            if handler:
                label = get_objection_label(language)
                objection_hint = f"\n\n{label}: {handler}"

        history = history_before_current
        messages = _build_model_messages(
            history,
            text,
            settings.CONVERSATION_HISTORY_LIMIT,
        )
        payment_reply = get_payment_reply(
            text,
            language,
            classification.get("purchase_readiness"),
            history,
        )
        direct_reply = get_direct_sales_reply(text, history, language)
        discount_reply = get_discount_reply(text, history, language)
        if payment_reply and discount_reply:
            direct_reply = f"{discount_reply}\n\n{payment_reply}"
        if payment_reply:
            direct_reply = direct_reply or payment_reply
        elif discount_reply:
            direct_reply = discount_reply
        is_first_reply = not any(message.get("role") == "assistant" for message in history)

        previous_replies = [
            message["content"]
            for message in history
            if message.get("role") == "assistant" and message.get("content")
        ]
        discovery_question_count = _count_opening_discovery_questions(previous_replies)
        system_prompt = get_system_prompt(
            language,
            is_first_reply=is_first_reply,
            discovery_question_count=discovery_question_count,
            discovery_completed=discovery_completed,
            direct_sales_question=direct_reply is not None,
            customer_provided_context=(
                discovery_completed
                or has_customer_context_hint(text)
                or bool(direct_reply)
            ),
        )
        full_system = f"{system_prompt}\n\n{context_prompt}{objection_hint}"

        delay_range = TYPING_DELAYS[reply_length]
        typing_delay = random.uniform(*delay_range)

        tokens = 0
        try:
            async with event.client.action(event.chat_id, "typing"):
                await asyncio.sleep(typing_delay)
                if direct_reply:
                    reply = direct_reply
                    tokens = 0
                else:
                    reply, tokens = await generate_reply(messages, full_system)

                reply = _remove_repeated_greeting(reply, is_first_reply)
                if not direct_reply and _has_repeated_content(reply, previous_replies):
                    logger.info(
                        "repetitive_reply_detected",
                        user_id=user_id,
                        previous_reply_count=len(previous_replies),
                    )
                    anti_repeat_system = (
                        f"{full_system}\n\n"
                        "URGENT: Your draft repeats an earlier assistant reply. "
                        "Discard it and write a completely fresh, shorter reply. "
                        "Do not greet, restate previous questions, repeat plan specs, "
                        "or repeat the previous closing. Reply only to the latest customer message."
                    )
                    try:
                        fresh_reply, fresh_tokens = await generate_reply(
                            messages,
                            anti_repeat_system,
                            temperature=0.55,
                        )
                        reply = _remove_repeated_greeting(fresh_reply, is_first_reply)
                        tokens += fresh_tokens
                    except Exception as retry_err:
                        # Keep the first usable answer if the quality retry
                        # hits a transient provider error.
                        logger.warning(
                            "anti_repeat_retry_failed",
                            user_id=user_id,
                            error=str(retry_err),
                        )
        except Exception as ai_err:
            logger.error("ai_failed_using_fallback", user_id=user_id, error=str(ai_err))
            reply = _fallback_reply(language, user_id, text)

        await save_message(
            session, conv.id, None, "outbound", reply,
            ai_generated=tokens > 0, tokens=tokens,
        )

        msg_count_key = f"conv_msg_count:{conv.id}"
        msg_count = int(await cache_get(msg_count_key) or 0) + 1
        await cache_set(msg_count_key, msg_count, ttl=86400)

        if tokens > 0 and msg_count % 10 == 0 and msg_count >= 10:
            asyncio.create_task(
                _extract_and_store_facts(
                    customer.id,
                    messages + [{"role": "assistant", "content": reply}],
                )
            )

        await session.commit()

    try:
        await event.reply(reply, parse_mode="md")
        await increment_daily_stat("messages_sent")
        logger.info(
            "reply_sent",
            user_id=user_id,
            language=language,
            tokens=tokens,
            intent=classification.get("intent"),
        )
    except Exception as e:
        logger.error("send_reply_failed", user_id=user_id, error=str(e))


async def _extract_and_store_facts(customer_id: uuid.UUID, messages: list[dict]):
    try:
        async with AsyncSessionLocal() as new_session:
            facts = await extract_facts_from_conversation(messages)
            if facts:
                filterable = {
                    k: v for k, v in facts.items()
                    if v and v not in ("null", "unknown", [])
                }
                await upsert_memory_bulk(new_session, customer_id, filterable)
                await new_session.commit()
                logger.info(
                    "facts_extracted_and_stored",
                    customer_id=str(customer_id),
                    count=len(filterable),
                )
    except Exception as e:
        logger.warning("fact_extraction_bg_failed", error=str(e))


async def get_or_create_customer(session, sender, account_id: str) -> Customer:
    result = await session.execute(
        select(Customer).where(Customer.telegram_id == sender.id)
    )
    customer = result.scalar_one_or_none()

    if not customer:
        customer = Customer(
            telegram_id=sender.id,
            username=getattr(sender, "username", None),
            display_name=(
                f"{getattr(sender, 'first_name', '') or ''} "
                f"{getattr(sender, 'last_name', '') or ''}"
            ).strip() or None,
            language_code="en",
        )
        session.add(customer)
        await increment_daily_stat("new_customers")
        logger.info("customer_created", telegram_id=sender.id)
    else:
        if getattr(sender, "username", None):
            customer.username = sender.username
        if getattr(sender, "first_name", None) or getattr(sender, "last_name", None):
            new_name = (
                f"{getattr(sender, 'first_name', '') or ''} "
                f"{getattr(sender, 'last_name', '') or ''}"
            ).strip()
            if new_name:
                customer.display_name = new_name

    return customer


async def get_or_create_conversation(
    session, customer: Customer, account_id: str, language: str = "en"
) -> Conversation:
    cache_key = CacheKeys.conversation_active(account_id, customer.telegram_id)
    cached_id = await cache_get(cache_key)
    account_uuid = uuid.UUID(account_id)

    if cached_id:
        try:
            cached_uuid = uuid.UUID(str(cached_id))
        except (TypeError, ValueError):
            logger.warning("invalid_active_conversation_cache", telegram_id=customer.telegram_id)
            cached_uuid = None

        result = None
        if cached_uuid:
            result = await session.execute(
                select(Conversation).where(
                    Conversation.id == cached_uuid,
                    Conversation.customer_id == customer.id,
                    Conversation.account_id == account_uuid,
                    Conversation.status == "active",
                )
            )
        conv = result.scalar_one_or_none() if result is not None else None
        if conv:
            # Refresh the lookup key on every message so an active chat does
            # not silently become a new conversation after the original TTL.
            await cache_set(
                cache_key,
                str(conv.id),
                ttl=settings.CONVERSATION_ACTIVE_TTL,
            )
            return conv

    # Redis is a cache, not the source of truth. Recover the latest active
    # conversation from PostgreSQL after a cache expiry, restart, or failover.
    result = await session.execute(
        select(Conversation)
        .where(
            Conversation.customer_id == customer.id,
            Conversation.account_id == account_uuid,
            Conversation.status == "active",
        )
        .order_by(Conversation.started_at.desc())
        .limit(1)
    )
    conv = result.scalar_one_or_none()
    if conv:
        await cache_set(
            cache_key,
            str(conv.id),
            ttl=settings.CONVERSATION_ACTIVE_TTL,
        )
        logger.info(
            "active_conversation_restored_from_database",
            telegram_id=customer.telegram_id,
            conversation_id=str(conv.id),
        )
        return conv

    conv = Conversation(
        customer_id=customer.id,
        account_id=account_uuid,
        status="active",
        language=language,
        started_at=datetime.now(timezone.utc),
    )
    session.add(conv)
    await session.flush()
    await cache_set(
        cache_key,
        str(conv.id),
        ttl=settings.CONVERSATION_ACTIVE_TTL,
    )
    return conv


async def save_message(
    session,
    conv_id,
    tg_msg_id,
    direction: str,
    content: str,
    ai_generated: bool = False,
    tokens: int = 0,
):
    session.add(Message(
        conversation_id=conv_id,
        telegram_msg_id=tg_msg_id,
        direction=direction,
        content=content,
        ai_generated=ai_generated,
        tokens_used=tokens,
        sent_at=datetime.now(timezone.utc),
    ))
