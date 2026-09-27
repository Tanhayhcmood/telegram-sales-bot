from telethon import events
from telethon.tl.functions.account import UpdateStatusRequest
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.account import TelegramAccount
from app.services.userbot.client import UserBotClient
from app.services.userbot.handlers import handle_private_message
from app.services.userbot.reconnect import reconnect_with_backoff
from app.services.monitoring.alerting import send_alert, notify_account_disconnected
from app.core.logging import get_logger
from datetime import datetime, timezone
import asyncio
import uuid

logger = get_logger(__name__)

HEALTH_CHECK_INTERVAL = 60
MAX_RECONNECT_FAILURES = 3

ONLINE_PING_INTERVAL = 60


class UserBotManager:
  def __init__(self):
      self._clients: dict[str, UserBotClient] = {}
      self._reconnect_failures: dict[str, int] = {}
      self._handlers_registered: set[str] = set()
      self._running = False
      self._health_task = None
      self._keeper_task = None

  async def load_accounts(self) -> None:
      async with AsyncSessionLocal() as session:
          result = await session.execute(select(TelegramAccount).where(TelegramAccount.is_active == True))
          accounts = result.scalars().all()

      for account in accounts:
          await self.add_account(str(account.id), account.phone, account.session_string)

      logger.info("accounts_loaded", count=len(accounts))

  async def _ping_online(self, account_id: str, client: UserBotClient) -> None:
      """Send a single online ping -- fire and forget, never raises."""
      try:
          await client.client(UpdateStatusRequest(offline=False))
          logger.debug("online_ping_sent", account_id=account_id)
      except Exception as e:
          logger.warning("online_ping_failed", account_id=account_id, error=str(e))

  async def _auto_discover_channels(self, account_id: str) -> None:
      """
      After a successful userbot connection, automatically scan and register
      channels in the background. Runs as a fire-and-forget task -- never raises.

      This ensures channels are always up-to-date after every deploy/restart
      without needing to manually press Control -> Scan Channels.
      """
      try:
          await asyncio.sleep(5)
          from app.services.channel.auto_discover import discover_and_register_channels
          result = await discover_and_register_channels(self, account_id)
          logger.info(
              "auto_channel_discovery_complete",
              account_id=account_id,
              found=result.get("found", 0),
              added=result.get("added", 0),
              reactivated=result.get("reactivated", 0),
          )
      except Exception as e:
          logger.error("auto_channel_discovery_failed", account_id=account_id, error=str(e))

  async def add_account(self, account_id: str, phone: str, session_string: str = None) -> bool:
      client = UserBotClient(phone=phone, session_string=session_string, account_id=account_id)
      connected = await client.connect()

      if connected:
          self._register_handlers(client, account_id)
          self._clients[account_id] = client
          self._reconnect_failures[account_id] = 0
          await self._update_account_status(account_id, connected=True)
          await self._ping_online(account_id, client)
          # Auto-discover channels in background after connecting
          asyncio.create_task(self._auto_discover_channels(account_id))
          logger.info("account_added", account_id=account_id, phone=phone)
          return True
      else:
          logger.error("account_connection_failed", account_id=account_id, phone=phone)
          await notify_account_disconnected(phone, account_id)
          return False

  def _register_handlers(self, client: UserBotClient, account_id: str) -> None:
      if account_id in self._handlers_registered:
          logger.debug("handlers_already_registered_skipping", account_id=account_id)
          return
      self._handlers_registered.add(account_id)

      @client.client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
      async def on_private_message(event):
          try:
              await handle_private_message(event, account_id)
          except Exception as e:
              logger.error("handler_error", account_id=account_id, error=str(e))

  def get_client(self, account_id: str) -> UserBotClient:
      return self._clients.get(account_id)

  def list_accounts(self) -> list[dict]:
      return [
          {
              "account_id": aid,
              "phone": c.phone,
              "is_connected": c.is_connected,
              **c.identity,
              "reconnect_failures": self._reconnect_failures.get(aid, 0),
          }
          for aid, c in self._clients.items()
      ]

  def get_connected_count(self) -> int:
      return sum(1 for c in self._clients.values() if c.is_connected)

  def is_running(self) -> bool:
      return self._running

  async def _update_account_status(self, account_id: str, connected: bool) -> None:
      async with AsyncSessionLocal() as session:
          result = await session.execute(
              select(TelegramAccount).where(TelegramAccount.id == uuid.UUID(account_id))
          )
          account = result.scalar_one_or_none()
          if account:
              account.last_seen_at = datetime.now(timezone.utc)
              await session.commit()

  async def online_keeper_loop(self) -> None:
      """
      Keeps every connected account appearing Online 24/7.

      - Pings UpdateStatusRequest(offline=False) every 60 seconds.
      - Completely independent of AI keys, posting state, or any external service.
      - Never sends offline=True.
      - Runs forever as long as the process is alive.
      """
      logger.info("online_keeper_started", interval_sec=ONLINE_PING_INTERVAL)
      while self._running:
          try:
              for account_id, client in list(self._clients.items()):
                  if client.is_connected:
                      await self._ping_online(account_id, client)
          except Exception as e:
              logger.error("online_keeper_loop_error_recovering", error=str(e))
          await asyncio.sleep(ONLINE_PING_INTERVAL)

  async def health_check_loop(self) -> None:
      while self._running:
          await asyncio.sleep(HEALTH_CHECK_INTERVAL)
          for account_id, client in list(self._clients.items()):
              if not client.is_connected:
                  failures = self._reconnect_failures.get(account_id, 0)
                  logger.warning("userbot_disconnected_detected", account_id=account_id, failures=failures)

                  if failures >= MAX_RECONNECT_FAILURES:
                      logger.error("account_max_reconnect_failures", account_id=account_id)
                      await notify_account_disconnected(client.phone, account_id)
                      continue

                  reconnected = await reconnect_with_backoff(client, account_id, client.phone)
                  if reconnected:
                      self._register_handlers(client, account_id)
                      self._reconnect_failures[account_id] = 0
                      await self._ping_online(account_id, client)
                      await send_alert("info", "telegram", f"Account {client.phone} reconnected", cooldown=False)
                  else:
                      self._reconnect_failures[account_id] = failures + 1

  async def start(self) -> None:
      self._running = True
      await self.load_accounts()
      self._health_task = asyncio.create_task(self.health_check_loop())
      self._keeper_task = asyncio.create_task(self.online_keeper_loop())
      logger.info("userbot_manager_started", accounts=len(self._clients))

  async def stop(self) -> None:
      self._running = False
      # Cancel background loops immediately instead of waiting for the next sleep tick.
      for task in (self._health_task, self._keeper_task):
          if task and not task.done():
              task.cancel()
      for client in self._clients.values():
          try:
              await client.disconnect()
          except Exception:
              pass
      self._clients.clear()
      self._reconnect_failures.clear()
      logger.info("userbot_manager_stopped")

  async def run_until_disconnected(self) -> None:
      clients = list(self._clients.values())
      if not clients:
          logger.warning("no_accounts_connected")
          return
      tasks = [asyncio.create_task(c.client.run_until_disconnected()) for c in clients]
      await asyncio.gather(*tasks, return_exceptions=True)


userbot_manager = UserBotManager()
