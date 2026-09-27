from telethon import TelegramClient
from telethon.sessions import StringSession
from app.core.config import settings
from app.core.logging import get_logger
from typing import Optional

logger = get_logger(__name__)


class UserBotClient:
    def __init__(
        self,
        phone: str,
        session_string: Optional[str] = None,
        account_id: str = None,
        proxy: tuple = None,   # PySocks-format tuple for per-channel IP routing
    ):
        self.phone = phone
        self.account_id = account_id
        self._session_string = session_string  # keep for creating proxy-specific clients
        self._is_connected = False
        self._me = None

        # Bug 1 fix: session_string is REQUIRED — Render's disk is ephemeral, so file-based
        # sessions are wiped on every deploy/restart. Always load from the DB-stored string.
        if not session_string:
            raise ValueError(
                f"No session_string found in DB for account {phone}. "
                "Generate a session string via the session-gen tool and persist it "
                "in the telegram_accounts table before activating this account."
            )
        session = StringSession(session_string)

        client_kwargs = dict(
            device_model="Linux Server",
            system_version="Ubuntu 22.04",
            app_version="1.0.0",
            lang_code="en",
            system_lang_code="en",
            connection_retries=3,         # Bug 6 fix: was None → infinite hang; 3 finite retries
            retry_delay=1,
            timeout=60,
            request_retries=1,
            flood_sleep_threshold=60,     # Bug 3 fix: was 0 → crash on FloodWait; 60 = auto-sleep
        )
        if proxy:
            client_kwargs["proxy"] = proxy

        self._client = TelegramClient(
            session,
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
            **client_kwargs,
        )

    @property
    def client(self) -> TelegramClient:
        return self._client

    @property
    def session_string(self) -> Optional[str]:
        """Return the session string stored at construction time."""
        return self._session_string

    async def connect(self) -> bool:
        try:
            await self._client.connect()
            if not await self._client.is_user_authorized():
                logger.warning("userbot_not_authorized", phone=self.phone)
                return False
            me = await self._client.get_me()
            self._me = me
            self._is_connected = True
            logger.info("userbot_connected", phone=self.phone, name=f"{me.first_name}")
            return True
        except Exception as e:
            logger.error("userbot_connect_failed", phone=self.phone, error=str(e))
            return False

    async def disconnect(self) -> None:
        if self._client.is_connected():
            await self._client.disconnect()
            self._is_connected = False
            logger.info("userbot_disconnected", phone=self.phone)

    async def send_message(self, entity, text: str, parse_mode: str = "md", **kwargs):
        return await self._client.send_message(entity, text, parse_mode=parse_mode, **kwargs)

    async def send_file(self, entity, file, caption: str = None, parse_mode: str = "md", **kwargs):
        return await self._client.send_file(
            entity,
            file,
            caption=caption,
            parse_mode=parse_mode,
            **kwargs,
        )

    async def get_me(self):
        return await self._client.get_me()

    @property
    def identity(self) -> dict:
        me = self._me
        if not me:
            return {}
        return {
            "telegram_user_id": getattr(me, "id", None),
            "telegram_username": getattr(me, "username", None),
            "telegram_name": " ".join(
                part for part in [getattr(me, "first_name", None), getattr(me, "last_name", None)] if part
            ) or None,
            "telegram_phone": getattr(me, "phone", None),
        }

    @property
    def is_connected(self) -> bool:
        return self._is_connected and self._client.is_connected()
