from telethon import events, functions
from telethon.errors import AuthKeyDuplicatedError, FloodWaitError, SessionRevokedError, UnauthorizedError
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.account import TelegramAccount
from app.services.userbot.client import UserBotClient, UserBotUnauthorizedError
from app.services.userbot.handlers import handle_private_message
from app.services.monitoring.alerting import send_alert
from app.core.config import settings
from app.core.logging import get_logger
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
from pathlib import Path
import asyncio
import fcntl
import os
import random
import uuid

logger = get_logger(__name__)

def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


USERBOT_ALWAYS_ONLINE_DEFAULT = _env_bool("USERBOT_ALWAYS_ONLINE", True)
ONLINE_INTERVAL_MIN = max(1, min(59, _env_int("USERBOT_ONLINE_INTERVAL_MIN", 25)))
ONLINE_INTERVAL_MAX = max(ONLINE_INTERVAL_MIN, min(59, _env_int("USERBOT_ONLINE_INTERVAL_MAX", 40)))
_FATAL_SESSION_ERRORS = (
    AuthKeyDuplicatedError,
    SessionRevokedError,
    UnauthorizedError,
    UserBotUnauthorizedError,
)


class UserBotManager:
  def __init__(self):
      self._clients: dict[str, UserBotClient] = {}
      self._reconnect_failures: dict[str, int] = {}
      self._handlers_registered: set[str] = set()
      self._running = False
      self._online_enabled = USERBOT_ALWAYS_ONLINE_DEFAULT
      self._connection_tasks: dict[str, asyncio.Task] = {}
      self._keeper_tasks: dict[str, asyncio.Task] = {}
      self._online_events: dict[str, asyncio.Event] = {}
      self._fatal_accounts: set[str] = set()
      self._fatal_alerted: set[str] = set()
      self._connection_state: dict[str, bool] = {}
      self._connection_error_state: dict[str, str] = {}
      self._keeper_error_state: dict[str, str] = {}
      self._last_online_success: dict[str, datetime] = {}
      self._online_failures: dict[str, deque] = defaultdict(deque)
      self._hourly_ping_ok = 0
      self._hourly_ping_failures = 0
      self._summary_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
      self._summary_task: asyncio.Task | None = None
      self._session_guard_handle = None
      self._stopped_event = asyncio.Event()
      self._stopped_event.set()

  async def load_accounts(self) -> None:
      await self._bootstrap_env_account()
      async with AsyncSessionLocal() as session:
          result = await session.execute(select(TelegramAccount).where(TelegramAccount.is_active == True))
          accounts = result.scalars().all()

      for account in accounts:
          await self.add_account(str(account.id), account.phone, account.session_string)

      logger.info("accounts_loaded", count=len(accounts))

  async def _bootstrap_env_account(self) -> None:
      """Persist the configured Render userbot session before loading accounts.

      Render instances can restart with an empty or newly migrated database.
      Keeping this opt-in prevents startup from silently creating placeholder
      accounts while allowing a real session to be restored from environment
      secrets without exposing it in logs.
      """
      phone = settings.TELEGRAM_USERBOT_PHONE.strip()
      session_string = settings.TELEGRAM_USERBOT_SESSION_STRING.strip()
      if not phone or not session_string:
          return

      async with AsyncSessionLocal() as session:
          result = await session.execute(
              select(TelegramAccount).where(TelegramAccount.phone == phone)
          )
          account = result.scalar_one_or_none()
          created = account is None

          if account is None:
              account = TelegramAccount(
                  phone=phone,
                  session_string=session_string,
                  is_active=True,
              )
              session.add(account)
          else:
              account.session_string = session_string
              account.is_active = True

          await session.commit()

      logger.info(
          "env_userbot_account_ready",
          phone=phone,
          created=created,
      )

  def _acquire_process_guard(self) -> bool:
      if self._session_guard_handle is not None:
          return True
      handle = None
      try:
          Path("sessions").mkdir(parents=True, exist_ok=True)
          handle = open(Path("sessions") / "userbot-manager.lock", "a+")
          fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
          self._session_guard_handle = handle
          return True
      except BlockingIOError:
          if handle:
              handle.close()
          logger.error("userbot_duplicate_process_guard", message="Another process already holds the userbot session lock; refusing to start a second session.")
          return False
      except Exception as exc:
          if handle:
              handle.close()
          logger.error("userbot_process_guard_failed", error_type=type(exc).__name__)
          return False

  def _release_process_guard(self) -> None:
      handle = self._session_guard_handle
      self._session_guard_handle = None
      if handle is None:
          return
      try:
          fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
          handle.close()
      except Exception:
          pass

  def _event_for(self, account_id: str) -> asyncio.Event:
      event = self._online_events.get(account_id)
      if event is None:
          event = asyncio.Event()
          self._online_events[account_id] = event
      return event

  def _start_keeper(self, account_id: str, client: UserBotClient) -> None:
      if not self._running or not self._online_enabled or account_id in self._fatal_accounts:
          return
      task = self._keeper_tasks.get(account_id)
      if task and not task.done():
          return
      self._event_for(account_id).clear()
      self._keeper_tasks[account_id] = asyncio.create_task(
          self._online_keeper_supervisor(account_id, client),
          name=f"userbot-online-keeper-{account_id}",
      )

  def _start_connection_supervisor(self, account_id: str, client: UserBotClient) -> None:
      if not self._running or account_id in self._fatal_accounts:
          return
      task = self._connection_tasks.get(account_id)
      if task and not task.done():
          return
      self._connection_tasks[account_id] = asyncio.create_task(
          self._connection_supervisor(account_id, client),
          name=f"userbot-connection-supervisor-{account_id}",
      )

  def _connection_changed(self, account_id: str, connected: bool, reason: str | None = None) -> None:
      if self._connection_state.get(account_id) is connected:
          return
      self._connection_state[account_id] = connected
      if connected:
          self._connection_error_state.pop(account_id, None)
          logger.info("userbot_connection_state_changed", account_id=account_id, connected=True)
      else:
          logger.warning("userbot_connection_state_changed", account_id=account_id, connected=False, reason=reason or "disconnected")
          self._event_for(account_id).set()

  def _record_online_failure(self, account_id: str) -> None:
      now = datetime.now(timezone.utc)
      self._online_failures[account_id].append(now)
      self._hourly_ping_failures += 1

  def online_status(self) -> dict:
      threshold = datetime.now(timezone.utc) - timedelta(hours=1)
      failures = 0
      for timestamps in self._online_failures.values():
          while timestamps and timestamps[0] < threshold:
              timestamps.popleft()
          failures += len(timestamps)
      last_success = max(self._last_online_success.values(), default=None)
      return {
          "enabled": self._online_enabled,
          "last_success": last_success,
          "failures_last_hour": failures,
          "connected_accounts": self.get_connected_count(),
      }

  async def set_online(self, enabled: bool) -> dict:
      enabled = bool(enabled)
      changed = self._online_enabled != enabled
      self._online_enabled = enabled
      if changed:
          logger.info("userbot_online_state_changed", enabled=enabled)

      if enabled:
          for account_id in self._clients:
              self._event_for(account_id).clear()
          for account_id, client in list(self._clients.items()):
              if client.is_connected:
                  self._start_keeper(account_id, client)
          return {"enabled": True, "offline_sent": 0, "offline_failures": 0, "connected_accounts": self.get_connected_count()}

      for account_id in self._clients:
          self._event_for(account_id).set()
      tasks = [task for task in self._keeper_tasks.values() if not task.done()]
      for task in tasks:
          task.cancel()
      if tasks:
          await asyncio.gather(*tasks, return_exceptions=True)
      self._keeper_tasks.clear()

      sent = 0
      failed = 0
      for account_id, client in list(self._clients.items()):
          if not client.is_connected:
              continue
          try:
              sent_ok = await self._send_offline_status(account_id, client)
              if sent_ok:
                  sent += 1
                  self._hourly_ping_ok += 1
              else:
                  failed += 1
          except _FATAL_SESSION_ERRORS as exc:
              failed += 1
              self._record_online_failure(account_id)
              await self._handle_fatal_session(account_id, client, exc)
          except Exception as exc:
              failed += 1
              self._record_online_failure(account_id)
              logger.warning("userbot_offline_status_failed", account_id=account_id, error_type=type(exc).__name__)
      return {"enabled": False, "offline_sent": sent, "offline_failures": failed, "connected_accounts": self.get_connected_count()}

  async def _send_offline_status(self, account_id: str, client: UserBotClient) -> bool:
      request = functions.account.UpdateStatusRequest(offline=True)
      try:
          await client.client(request, ordered=False)
          return True
      except FloodWaitError as exc:
          self._record_online_failure(account_id)
          await self._sleep_in_short_chunks(float(exc.seconds) + 5.0)
          try:
              await client.client(request, ordered=False)
              return True
          except FloodWaitError as retry_exc:
              self._record_online_failure(account_id)
              await self._sleep_in_short_chunks(float(retry_exc.seconds) + 5.0)
              return False

  async def _sleep_in_short_chunks(self, seconds: float) -> None:
      remaining = max(0.0, seconds)
      while remaining > 0:
          duration = min(59.0, remaining)
          await asyncio.sleep(duration)
          remaining -= duration

  async def _notify_admins_once(self, text: str) -> None:
      from app.services.admin_bot.bot import get_bot
      bot = get_bot()
      if bot is None:
          logger.error("userbot_admin_alert_unavailable", reason="ADMIN_BOT_TOKEN is not configured")
          return
      admin_ids = getattr(settings, "admin_ids", []) or []
      if not admin_ids:
          logger.error("userbot_admin_alert_unavailable", reason="No admin IDs are configured")
          return
      failed = False
      for admin_id in admin_ids:
          try:
              await bot.send_message(admin_id, text, parse_mode=None)
          except Exception:
              failed = True
      if failed:
          logger.error("userbot_admin_alert_delivery_failed", admins=len(admin_ids))

  async def _handle_fatal_session(self, account_id: str, client: UserBotClient, exc: Exception) -> None:
      if account_id in self._fatal_alerted:
          return
      self._fatal_alerted.add(account_id)
      self._fatal_accounts.add(account_id)
      if isinstance(exc, AuthKeyDuplicatedError):
          detail = "Telegram reported a duplicated auth key; another instance is using the same session string."
      else:
          detail = f"Telegram user session is no longer authorized ({type(exc).__name__})."
      logger.error("userbot_session_fatal_stopped", account_id=account_id, error_type=type(exc).__name__, detail=detail)
      self._event_for(account_id).set()
      current = asyncio.current_task()
      for task in (self._keeper_tasks.get(account_id), self._connection_tasks.get(account_id)):
          if task and task is not current and not task.done():
              task.cancel()
      try:
          await client.disconnect()
      except Exception:
          pass
      await self._notify_admins_once(f"🚨 Userbot stopped for {client.phone}: {detail}")

  async def _online_keeper_loop(self, account_id: str, client: UserBotClient) -> None:
      while self._running and self._online_enabled and account_id not in self._fatal_accounts:
          if not client.is_connected:
              try:
                  await asyncio.wait_for(self._event_for(account_id).wait(), timeout=5.0)
              except asyncio.TimeoutError:
                  pass
              self._event_for(account_id).clear()
              continue
          try:
              await asyncio.sleep(0)  # Yield to message handlers before the low-priority status RPC.
              await client.client(functions.account.UpdateStatusRequest(offline=False), ordered=False)
              self._last_online_success[account_id] = datetime.now(timezone.utc)
              self._hourly_ping_ok += 1
              self._keeper_error_state.pop(account_id, None)
          except FloodWaitError as exc:
              self._record_online_failure(account_id)
              await self._sleep_in_short_chunks(float(exc.seconds) + 5.0)
              continue
          except _FATAL_SESSION_ERRORS as exc:
              self._record_online_failure(account_id)
              await self._handle_fatal_session(account_id, client, exc)
              return
          except asyncio.CancelledError:
              raise
          except Exception as exc:
              self._record_online_failure(account_id)
              error_type = type(exc).__name__
              if self._keeper_error_state.get(account_id) != error_type:
                  logger.warning("online_keeper_error_state_changed", account_id=account_id, error_type=error_type)
                  self._keeper_error_state[account_id] = error_type
          interval = random.randint(ONLINE_INTERVAL_MIN, ONLINE_INTERVAL_MAX)
          try:
              await asyncio.wait_for(self._event_for(account_id).wait(), timeout=interval)
          except asyncio.TimeoutError:
              pass
          self._event_for(account_id).clear()

  async def _online_keeper_supervisor(self, account_id: str, client: UserBotClient) -> None:
      while self._running and self._online_enabled and account_id not in self._fatal_accounts:
          try:
              await self._online_keeper_loop(account_id, client)
              if not self._running or not self._online_enabled or account_id in self._fatal_accounts:
                  return
          except asyncio.CancelledError:
              raise
          except _FATAL_SESSION_ERRORS as exc:
              self._record_online_failure(account_id)
              await self._handle_fatal_session(account_id, client, exc)
              return
          except Exception as exc:
              self._record_online_failure(account_id)
              error_type = type(exc).__name__
              if self._keeper_error_state.get(account_id) != error_type:
                  logger.warning("online_keeper_supervisor_restarting", account_id=account_id, error_type=error_type)
                  self._keeper_error_state[account_id] = error_type
              await asyncio.sleep(2.0)

  async def _connection_supervisor(self, account_id: str, client: UserBotClient) -> None:
      backoff = 2.0
      while self._running and account_id not in self._fatal_accounts:
          try:
              if client.is_connected:
                  self._reconnect_failures[account_id] = 0
                  self._start_keeper(account_id, client)
                  await asyncio.sleep(5.0)
                  continue

              self._event_for(account_id).set()
              self._connection_changed(account_id, False, reason="connection_lost")
              try:
                  connected = await client.connect()
              except _FATAL_SESSION_ERRORS as exc:
                  await self._handle_fatal_session(account_id, client, exc)
                  return
              except asyncio.CancelledError:
                  raise
              except Exception as exc:
                  connected = False
                  client._last_connect_error = type(exc).__name__

              if connected:
                  self._register_handlers(client, account_id)
                  self._reconnect_failures[account_id] = 0
                  self._connection_changed(account_id, True)
                  await self._update_account_status(account_id, connected=True)
                  self._event_for(account_id).set()
                  self._start_keeper(account_id, client)
                  backoff = 2.0
                  await send_alert("info", "telegram", f"Account {client.phone} reconnected", cooldown=False)
                  continue

              self._reconnect_failures[account_id] = self._reconnect_failures.get(account_id, 0) + 1
              error_type = getattr(client, "_last_connect_error", None) or "ConnectFailed"
              if self._connection_error_state.get(account_id) != error_type:
                  self._connection_error_state[account_id] = error_type
                  logger.warning("userbot_reconnect_state_changed", account_id=account_id, error_type=error_type, next_retry_seconds=int(backoff))
              await asyncio.sleep(backoff)
              backoff = min(backoff * 2.0, 60.0)
          except asyncio.CancelledError:
              raise
          except _FATAL_SESSION_ERRORS as exc:
              await self._handle_fatal_session(account_id, client, exc)
              return
          except Exception as exc:
              error_type = type(exc).__name__
              if self._connection_error_state.get(account_id) != error_type:
                  self._connection_error_state[account_id] = error_type
                  logger.warning("userbot_connection_supervisor_restarting", account_id=account_id, error_type=error_type)
              await asyncio.sleep(2.0)

  async def _hourly_summary_loop(self) -> None:
      while self._running:
          now = datetime.now(timezone.utc)
          current_hour = now.replace(minute=0, second=0, microsecond=0)
          if current_hour != self._summary_hour:
              logger.info("online_keeper_hourly_summary", pings_ok=self._hourly_ping_ok, failures=self._hourly_ping_failures)
              self._hourly_ping_ok = 0
              self._hourly_ping_failures = 0
              self._summary_hour = current_hour
          next_hour = current_hour + timedelta(hours=1)
          await asyncio.sleep(min(59.0, max(1.0, (next_hour - now).total_seconds())))

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
      self._clients[account_id] = client
      try:
          connected = await client.connect()
      except _FATAL_SESSION_ERRORS as exc:
          await self._handle_fatal_session(account_id, client, exc)
          return False

      self._connection_changed(account_id, connected, reason=getattr(client, "_last_connect_error", None))
      if connected:
          self._register_handlers(client, account_id)
          self._reconnect_failures[account_id] = 0
          await self._update_account_status(account_id, connected=True)
          self._start_keeper(account_id, client)
          asyncio.create_task(self._auto_discover_channels(account_id))
          logger.info("account_added", account_id=account_id, phone=phone)
      else:
          self._reconnect_failures[account_id] = 1
          logger.warning("account_connection_pending_reconnect", account_id=account_id, error_type=getattr(client, "_last_connect_error", None) or "ConnectFailed")
      self._start_connection_supervisor(account_id, client)
      return connected

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

  async def start(self) -> None:
      if self._running:
          return
      if not self._acquire_process_guard():
          self._running = False
          return
      self._running = True
      self._stopped_event.clear()
      self._online_enabled = USERBOT_ALWAYS_ONLINE_DEFAULT
      try:
          await self.load_accounts()
          self._summary_task = asyncio.create_task(self._hourly_summary_loop(), name="userbot-online-hourly-summary")
          logger.info("userbot_manager_started", accounts=len(self._clients), online_enabled=self._online_enabled)
      except Exception:
          self._running = False
          self._stopped_event.set()
          self._release_process_guard()
          raise

  async def stop(self) -> None:
      self._running = False
      self._stopped_event.set()
      for event in self._online_events.values():
          event.set()
      tasks = list(self._connection_tasks.values()) + list(self._keeper_tasks.values())
      if self._summary_task and not self._summary_task.done():
          tasks.append(self._summary_task)
      for task in tasks:
          if not task.done():
              task.cancel()
      if tasks:
          await asyncio.gather(*tasks, return_exceptions=True)
      self._connection_tasks.clear()
      self._keeper_tasks.clear()
      self._summary_task = None
      for client in self._clients.values():
          try:
              await client.disconnect()
          except Exception:
              pass
      self._clients.clear()
      self._reconnect_failures.clear()
      self._release_process_guard()
      logger.info("userbot_manager_stopped")

  async def run_until_disconnected(self) -> None:
      if not self._clients:
          logger.warning("no_accounts_connected")
      await self._stopped_event.wait()


userbot_manager = UserBotManager()
