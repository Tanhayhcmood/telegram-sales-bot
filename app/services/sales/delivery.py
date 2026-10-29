"""Paid-order-only credential delivery; never called by the AI layer."""
from __future__ import annotations
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)
PAYMENT_NOT_CONFIRMED_EN = "Payment is not confirmed yet."
PAYMENT_NOT_CONFIRMED_FA = "پرداخت هنوز تأیید نشده است."
HANDOFF = "I've passed this to our team, someone will contact you shortly"


def delivery_gate(order: dict | None, telegram_user_id: int) -> tuple[bool, str]:
    if not isinstance(order, dict):
        return False, "unpaid"
    status = str(order.get("payment_status", order.get("status", ""))).strip().casefold()
    if status not in {"paid", "confirmed"}:
        return False, "unpaid"
    try:
        if int(order.get("buyer_id")) != int(telegram_user_id):
            return False, "wrong_buyer"
    except (TypeError, ValueError):
        return False, "wrong_buyer"
    if order.get("delivery_status") in {"sending", "delivered", "attempted_unknown"}:
        return False, "already_attempted"
    if not order.get("delivery_payload"):
        return False, "payload_missing"
    return True, "ok"


def is_delivery_request(text: str) -> bool:
    import re
    return bool(re.search(r"\b(?:send|show|give|where(?:'s| is)?|what(?:'s| is))\b.{0,40}\b(?:server|access|login|password|credentials|rdp|ip|panel)\b|\bmy\s+(?:server|rdp|login|credentials|access|password)\b|\b(?:server|rdp|login|access)\s+(?:details|information|credentials)\b|سرورم|اطلاعات ورود|رمز سرور|آی.?پی سرور|دسترسی سرور", str(text or ""), re.I))


async def deliver_paid_order(order_id: str, telegram_user_id: int, sender, language: str = "en") -> str:
    """Load by order id, lock, enforce paid+buyer+once, send, and mark delivered."""
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.models.customer import Customer
    from app.services.userbot.outbound_guard import send_verified_delivery

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Customer).where(
                Customer.metadata_["order_flow"]["order_id"].as_string() == str(order_id)
            ).with_for_update()
        )
        customer = result.scalar_one_or_none()
        state = dict((getattr(customer, "metadata_", None) or {}).get("order_flow") or {}) if customer else {}
        order = {
            **state,
            "payment_status": state.get("payment_status"),
            "buyer_id": getattr(customer, "telegram_id", None),
            "delivery_status": state.get("delivery_status"),
            "delivery_payload": state.get("delivery_payload"),
        }
        allowed, reason = delivery_gate(order, telegram_user_id)
        if reason == "unpaid":
            return PAYMENT_NOT_CONFIRMED_FA if language == "fa" else PAYMENT_NOT_CONFIRMED_EN
        if not allowed:
            logger.warning("paid_delivery_denied order=%s user=%s reason=%s", str(order_id), int(telegram_user_id), reason)
            return HANDOFF
        if int(customer.telegram_id) != int(telegram_user_id):
            return HANDOFF
        # Reserve before sending; a timeout cannot trigger a duplicate credential send.
        state["delivery_status"] = "sending"
        state["delivery_attempted_at"] = datetime.now(timezone.utc).isoformat()
        metadata = dict(customer.metadata_ or {})
        metadata["order_flow"] = state
        customer.metadata_ = metadata
        await session.commit()
        payload = str(state["delivery_payload"])
        try:
            await send_verified_delivery(sender, telegram_user_id, payload, str(order_id))
        except Exception:
            logger.error("paid_delivery_send_uncertain order=%s user=%s", str(order_id), int(telegram_user_id))
            state["delivery_status"] = "attempted_unknown"
            metadata["order_flow"] = state
            customer.metadata_ = metadata
            await session.commit()
            return HANDOFF
        state["delivery_status"] = "delivered"
        state["delivered_at"] = datetime.now(timezone.utc).isoformat()
        state["delivered_to"] = int(telegram_user_id)
        metadata["order_flow"] = state
        customer.metadata_ = metadata
        await session.commit()
        logger.info("paid_delivery_sent order=%s user=%s", str(order_id), int(telegram_user_id))
        return "delivered"


async def record_delivery_payload(order_id: str, payload: str) -> bool:
    """Provisioning-only hook: store delivery data server-side for a paid order."""
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.models.customer import Customer
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Customer).where(
                Customer.metadata_["order_flow"]["order_id"].as_string() == str(order_id)
            ).with_for_update()
        )
        customer = result.scalar_one_or_none()
        if customer is None:
            return False
        metadata = dict(customer.metadata_ or {})
        state = dict(metadata.get("order_flow") or {})
        if str(state.get("payment_status", "")).casefold() not in {"paid", "confirmed"} or state.get("delivery_status") or state.get("delivery_payload"):
            return False
        state["delivery_payload"] = str(payload)
        metadata["order_flow"] = state
        customer.metadata_ = metadata
        await session.commit()
        return True
