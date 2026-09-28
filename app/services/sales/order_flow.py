"""Conversation-level checkout and order-state helpers.

This module deliberately tracks the checkout state in the existing customer
JSON metadata. It does not claim that a payment is verified or a server is
activated until an operator or a real payment/provisioning integration does
that work.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from app.services.sales.direct_questions import PLAN_ORDER
from app.services.sales.payment import get_requested_payment_method


CHECKOUT_STAGES = {
    "discovery",
    "plan_recommended",
    "payment_method_selection",
    "payment_pending",
    "payment_submitted",
    "payment_verification",
    "provisioning",
    "completed",
}

_PLAN_ALIASES = {
    "ENTRY LEVEL": ("entry level", "entry", "پلن پایه", "پلن ورودی"),
    "POWER": ("power",),
    "ELITE": ("elite",),
    "ULTRA": ("ultra",),
}

_RECEIPT_TERMS = (
    "پرداخت کردم",
    "واریز کردم",
    "واریز شد",
    "رسید پرداخت",
    "رسیدم",
    "اسکرین شات",
    "اسکرین‌شات",
    "اسکرینشات",
    "هش تراکنش",
    "شناسه تراکنش",
    "کد پیگیری",
    "تراکنش انجام شد",
    "i paid",
    "payment sent",
    "sent the payment",
    "payment screenshot",
    "transaction screenshot",
    "transaction id",
    "txid",
    "tx hash",
    "transaction hash",
    "receipt",
)

_ORDER_STATUS_TERMS = (
    "وضعیت سفارش",
    "پیگیری سفارش",
    "سفارشم",
    "رسیدم بررسی",
    "پرداخت بررسی",
    "تایید پرداخت",
    "تأیید پرداخت",
    "سرویس فعال شد",
    "order status",
    "track my order",
    "check my payment",
    "payment verified",
    "has my payment",
    "is my server active",
)

_PAYMENT_PROBLEM_TERMS = (
    "پرداخت ناموفق",
    "پرداخت نشد",
    "واریز نشد",
    "اشتباه واریز",
    "شبکه اشتباه",
    "شبکه رو اشتباه",
    "برگشت خورد",
    "برنگشته",
    "payment failed",
    "payment did not go through",
    "wrong network",
    "wrong address",
    "sent to the wrong",
    "refund",
    "reverted",
)


def _normalize(text: str) -> str:
    return " ".join(
        (text or "")
        .replace("\u200c", " ")
        .casefold()
        .split()
    )


def get_order_state(customer) -> dict:
    metadata = getattr(customer, "metadata_", None) or {}
    state = metadata.get("order_flow")
    return dict(state) if isinstance(state, dict) else {}


def update_order_state(customer, stage: str, **updates) -> dict:
    """Persist a small checkout state machine in existing JSONB metadata."""
    if stage not in CHECKOUT_STAGES:
        raise ValueError(f"Unsupported checkout stage: {stage}")

    previous = get_order_state(customer)
    now = datetime.now(timezone.utc).isoformat()
    state = {
        **previous,
        "order_id": previous.get("order_id") or f"ORD-{uuid.uuid4().hex[:10].upper()}",
        "stage": stage,
        "updated_at": now,
        **{key: value for key, value in updates.items() if value is not None},
    }
    if "created_at" not in state:
        state["created_at"] = now

    metadata = dict(getattr(customer, "metadata_", None) or {})
    metadata["order_flow"] = state
    customer.metadata_ = metadata
    return state


def extract_plan(text: str, history: list[dict] | None = None) -> str | None:
    """Find the first known plan in the newest message, then recent turns."""
    candidates = [text or ""]
    candidates.extend(
        message.get("content", "")
        for message in reversed(history or [])
        if message.get("content")
    )
    for candidate in candidates:
        normalized = _normalize(candidate)
        found: list[tuple[int, str]] = []
        for plan in PLAN_ORDER:
            positions = [
                normalized.find(alias)
                for alias in _PLAN_ALIASES[plan]
                if normalized.find(alias) >= 0
            ]
            if positions:
                found.append((min(positions), plan))
        if found:
            return sorted(found)[0][1]
    return None


def is_payment_receipt_message(text: str, has_media: bool = False, stage: str | None = None) -> bool:
    """Recognize an uploaded or described receipt without accepting it as proof."""
    normalized = _normalize(text)
    if any(term in normalized for term in _RECEIPT_TERMS):
        return True
    return bool(has_media and stage in {"payment_pending", "payment_submitted", "payment_verification"})


def has_transaction_reference(text: str) -> bool:
    normalized = _normalize(text)
    if any(term in normalized for term in ("txid", "tx hash", "transaction id", "transaction hash", "شناسه تراکنش", "هش تراکنش", "کد پیگیری")):
        return True
    # A long hex string is a useful hint, but never proof of payment.
    return bool(re.search(r"\b[a-f0-9]{24,}\b", normalized))


def is_order_status_request(text: str) -> bool:
    normalized = _normalize(text)
    return any(term in normalized for term in _ORDER_STATUS_TERMS)


def is_payment_problem_message(text: str) -> bool:
    normalized = _normalize(text)
    return any(term in normalized for term in _PAYMENT_PROBLEM_TERMS)


def get_payment_problem_reply(language: str, state: dict) -> str | None:
    if not state or state.get("stage") not in {
        "payment_pending",
        "payment_submitted",
        "payment_verification",
    }:
        return None
    order_id = state.get("order_id", "")
    if language == "fa":
        return (
            f"متوجه شدم؛ مشکل پرداخت سفارش `{order_id}` رو مرحله‌به‌مرحله بررسی می‌کنیم. "
            "لطفاً انتقال دیگری انجام نده و همینجا تصویر خطا، شبکه انتخاب‌شده و TXID/هش تراکنش را بفرست. "
            "تا قبل از بررسی شبکه و تراکنش، نمی‌تونم تأیید یا وعده بازگشت وجه بدم؛ اطلاعات رو برای بررسی دقیق به تیم مربوط ارجاع می‌دم."
        )
    return (
        f"I understand — we’ll review the payment issue for order `{order_id}` carefully. "
        "Please do not send another transfer. Send the error screenshot, selected network, and TXID/transaction hash here. "
        "Until the network and transaction are checked, I cannot claim a confirmation or promise a refund; I’ll route the details for review."
    )


def get_checkout_context_prompt(state: dict, language: str) -> str:
    """Give the model the current checkout stage without exposing internals."""
    if not state:
        return ""

    stage = state.get("stage", "discovery")
    plan = state.get("plan") or "the selected plan"
    labels_fa = {
        "discovery": "در حال شناخت نیاز مشتری",
        "plan_recommended": "پلن پیشنهاد شده و آماده تصمیم‌گیری",
        "payment_method_selection": "مشتری خرید را تأیید کرده و باید روش پرداخت را انتخاب کند",
        "payment_pending": "آدرس پرداخت ارسال شده و منتظر انتقال وجه و رسید هستیم",
        "payment_submitted": "رسید دریافت شده و در انتظار بررسی انسانی است",
        "payment_verification": "پرداخت در حال بررسی است",
        "provisioning": "پرداخت تأیید شده و فعال‌سازی در حال انجام است",
        "completed": "سفارش تکمیل و سرویس فعال شده است",
    }
    labels_en = {
        "discovery": "understanding the customer's needs",
        "plan_recommended": "a plan has been recommended and the customer is deciding",
        "payment_method_selection": "the customer agreed to buy and must choose a payment method",
        "payment_pending": "the payment address was sent and we are waiting for payment and receipt",
        "payment_submitted": "a receipt was received and awaits human verification",
        "payment_verification": "the payment is being verified",
        "provisioning": "payment was verified and activation is in progress",
        "completed": "the order is complete and the service is active",
    }
    label = labels_fa.get(stage, labels_fa["discovery"]) if language == "fa" else labels_en.get(stage, labels_en["discovery"])
    return (
        f"CHECKOUT CONTEXT: {label}. Selected plan: {plan}. "
        "Never claim payment verification, order completion, or service activation "
        "unless the context explicitly says that stage is completed."
    )


def get_payment_next_step(language: str, plan: str | None = None) -> str:
    if language == "fa":
        plan_text = f" برای پلن {plan}" if plan else ""
        return (
            f"مبلغ را فقط{plan_text} به همین آدرس و روی همان شبکه ارسال کن. "
            "بعد از انتقال، تصویر رسید و در صورت امکان TXID یا هش تراکنش را همینجا بفرست. "
            "تا قبل از تأیید، انتقال دوم انجام نده."
        )
    plan_text = f" for the {plan} plan" if plan else ""
    return (
        f"Send only the amount{plan_text} to this address on the matching network. "
        "After the transfer, send the receipt and, if available, the TXID or transaction hash here. "
        "Please do not send a second transfer before verification."
    )


def get_receipt_received_reply(language: str, order_state: dict, has_reference: bool) -> str:
    order_id = order_state.get("order_id", "your order")
    if language == "fa":
        reference_note = (
            "TXID/هش تراکنش هم ثبت شد."
            if has_reference
            else
            "اگر TXID یا هش تراکنش در تصویر مشخص نیست، آن را هم ارسال کن تا بررسی سریع‌تر و دقیق‌تر انجام شود."
        )
        return (
            f"رسیدت دریافت شد و سفارش `{order_id}` در وضعیت «در انتظار تأیید پرداخت» ثبت شد. "
            "تیم مالی مبلغ، ارز، شبکه و شناسه تراکنش را بررسی می‌کند؛ دریافت رسید به‌تنهایی به معنی تأیید پرداخت نیست. "
            f"{reference_note} تا اعلام نتیجه، انتقال دیگری انجام نده. بعد از تأیید، مرحله فعال‌سازی سرویس را همینجا پیگیری می‌کنیم."
        )
    reference_note = (
        "The TXID/transaction hash was included."
        if has_reference
        else
        "If the TXID or transaction hash is not visible in the image, send it as well for faster verification."
    )
    return (
        f"Your receipt was received and order `{order_id}` is now marked as payment pending verification. "
        "Our finance team will check the amount, asset, network, and transaction reference; receiving a receipt "
        "does not by itself confirm payment. "
        f"{reference_note} Please do not send a second transfer. We will continue with activation here after verification."
    )


def get_order_status_reply(language: str, state: dict) -> str | None:
    if not state:
        return None
    stage = state.get("stage", "discovery")
    plan = state.get("plan")
    plan_text_fa = f" برای پلن {plan}" if plan else ""
    plan_text_en = f" for the {plan} plan" if plan else ""

    if language == "fa":
        messages = {
            "plan_recommended": f"برای سفارش{plan_text_fa} هنوز منتظر تأیید نهایی تو هستیم. اگر آماده‌ای، بگو «می‌خوام بخرم» تا مرحله پرداخت را شروع کنیم.",
            "payment_method_selection": "خریدت ثبت شده و فقط انتخاب رمزارز/شبکه باقی مانده. بگو با کدام روش پرداخت می‌کنی تا آدرس دقیق همان روش را بفرستم.",
            "payment_pending": f"آدرس پرداخت{plan_text_fa} ارسال شده و هنوز رسیدی برای سفارش `{state.get('order_id', '')}` ثبت نشده. بعد از واریز، تصویر رسید و TXID را بفرست.",
            "payment_submitted": f"رسید سفارش `{state.get('order_id', '')}` دریافت شده و در انتظار بررسی پرداخت است. هنوز تأیید نهایی یا فعال‌سازی اعلام نشده؛ نتیجه را همینجا اعلام می‌کنیم.",
            "payment_verification": f"پرداخت سفارش `{state.get('order_id', '')}` در حال بررسی است. لطفاً تا اعلام نتیجه انتقال دیگری انجام نده.",
            "provisioning": f"پرداخت سفارش `{state.get('order_id', '')}` تأیید شده و فعال‌سازی{plan_text_fa} در حال انجام است. نتیجه نهایی همینجا اعلام می‌شود.",
            "completed": f"سفارش `{state.get('order_id', '')}` تکمیل شده و سرویس{plan_text_fa} فعال است.",
        }
    else:
        messages = {
            "plan_recommended": f"Your recommendation{plan_text_en} is ready, but we are still waiting for your final confirmation. Say “I want to buy” to start payment.",
            "payment_method_selection": "Your purchase is noted. The only remaining step is choosing the cryptocurrency/network. Tell me your preferred method and I’ll send the exact address.",
            "payment_pending": f"The payment address{plan_text_en} was sent, but no receipt is registered for order `{state.get('order_id', '')}` yet. Send the receipt and TXID after payment.",
            "payment_submitted": f"Receipt for order `{state.get('order_id', '')}` was received and is awaiting payment verification. Final confirmation and activation have not been claimed yet.",
            "payment_verification": f"Payment for order `{state.get('order_id', '')}` is being verified. Please do not send another transfer until we confirm the result.",
            "provisioning": f"Payment for order `{state.get('order_id', '')}` is verified and activation{plan_text_en} is in progress. We’ll confirm the final result here.",
            "completed": f"Order `{state.get('order_id', '')}` is complete and the service{plan_text_en} is active.",
        }
    return messages.get(stage)


def get_checkout_followup(language: str, state: dict) -> str | None:
    """Return a non-pushy follow-up for an unfinished operational step."""
    stage = state.get("stage")
    order_id = state.get("order_id", "")
    plan = state.get("plan")
    if stage == "payment_pending":
        if language == "fa":
            plan_text = f" برای پلن {plan}" if plan else ""
            return (
                f"سلام، فقط برای پیگیری سفارش `{order_id}` پیام دادم. "
                f"آدرس پرداخت{plan_text} ارسال شده؛ اگر واریز انجام شد، لطفاً تصویر رسید و TXID را همینجا بفرست. "
                "اگر در انتخاب شبکه یا پرداخت مشکلی داری، بگو تا دقیق راهنمایی‌ات کنم."
            )
        plan_text = f" for the {plan} plan" if plan else ""
        return (
            f"Hi, I’m following up on order `{order_id}`. The payment address{plan_text} was sent; "
            "if you have paid, send the receipt and TXID here. If anything is unclear about the network or payment, I’ll guide you."
        )
    if stage == "plan_recommended":
        if language == "fa":
            return f"سلام، درباره پیشنهاد سفارش `{order_id}` پیگیری می‌کنم. اگر سؤال یا تردیدی داری بگو تا قبل از تصمیم نهایی کامل راهنمایی‌ات کنم."
        return (
            f"Hi, I’m following up on order `{order_id}`. If you have any question or hesitation about the recommendation, "
            "tell me and I’ll clarify it before you decide."
        )
    return None


def payment_method_for_message(text: str) -> str | None:
    return get_requested_payment_method(text)