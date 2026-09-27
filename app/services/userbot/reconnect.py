import asyncio
from app.core.logging import get_logger
from app.services.monitoring.alerting import send_alert

logger = get_logger(__name__)

MAX_RETRIES = 5
RETRY_DELAYS = [5, 10, 30, 60, 120]


async def reconnect_with_backoff(client, account_id: str, phone: str) -> bool:
    for attempt in range(MAX_RETRIES):
        delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
        logger.warning("userbot_reconnect_attempt", phone=phone, attempt=attempt + 1, delay=delay)
        await asyncio.sleep(delay)

        try:
            connected = await client.connect()
            if connected:
                logger.info("userbot_reconnected", phone=phone, attempt=attempt + 1)
                await send_alert("info", "telegram", f"UserBot reconnected: {phone}")
                return True
        except Exception as e:
            logger.error("userbot_reconnect_error", phone=phone, attempt=attempt + 1, error=str(e))

    await send_alert("critical", "telegram", f"UserBot failed to reconnect after {MAX_RETRIES} attempts: {phone}")
    return False
