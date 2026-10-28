"""Telegram read acknowledgements and human-paced reply deadlines."""
from __future__ import annotations

import random
from asyncio import sleep
from time import monotonic


REPLY_DELAY_SECONDS = (30.0, 35.0)


def new_reply_deadline() -> float:
    """Pick a 30-35 second response deadline measured from message receipt."""
    return monotonic() + random.uniform(*REPLY_DELAY_SECONDS)


async def wait_for_reply_deadline(deadline: float) -> None:
    """Wait only for the remaining time; slow processing may exceed the deadline."""
    remaining = deadline - monotonic()
    if remaining > 0:
        await sleep(remaining)


async def mark_message_read(event) -> None:
    """Acknowledge the incoming Telegram message as read through its message ID."""
    await event.client.send_read_acknowledge(event.chat_id, max_id=event.message.id)
