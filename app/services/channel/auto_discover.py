from telethon.tl.types import Channel
from telethon.tl.functions.channels import GetAdminedPublicChannelsRequest
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.channel import TelegramChannel
from app.core.logging import get_logger
import uuid

logger = get_logger(__name__)


async def discover_and_register_channels(userbot_manager, account_id: str) -> dict:
  """
  Only finds channels where the account is creator or admin with post rights.
  - Not in DB -> add it (active=True)
  - In DB but inactive -> reactivate
  - DB channels no longer admin -> deactivate
    SAFETY: if iter_dialogs returns 0 results, skip deactivation entirely
            (likely a transient network/session error, not a real change).
  """
  client_wrapper = userbot_manager.get_client(account_id)
  if not client_wrapper or not client_wrapper.is_connected:
      return {"error": "account_not_connected", "found": 0, "added": 0, "reactivated": 0, "channels": []}

  client = client_wrapper.client

  admin_channels = []
  seen_entity_ids = set()
  dialogs_scanned = 0
  broadcast_channels_seen = 0
  admin_candidates_seen = 0
  broadcast_channel_details = []
  admin_channel_ids = set()
  admined_public_channels_seen = 0

  try:
      # Scan both the regular dialog list and Telegram's archived folder.
      # Archived dialogs are omitted by iter_dialogs() unless archived=True.
      for archived in (False, True):
          async for dialog in client.iter_dialogs(archived=archived):
              dialogs_scanned += 1
              entity = dialog.entity
              entity_id = getattr(entity, "id", None)
              if entity_id is not None and entity_id in seen_entity_ids:
                  continue
              if entity_id is not None:
                  seen_entity_ids.add(entity_id)

              if not isinstance(entity, Channel):
                  continue
              if not getattr(entity, "broadcast", False):
                  continue
              broadcast_channels_seen += 1

              is_creator = bool(getattr(entity, "creator", False))
              admin_rights = getattr(entity, "admin_rights", None)
              has_admin_rights = bool(admin_rights)
              is_admin = is_creator or has_admin_rights
              can_post = is_creator or bool(getattr(admin_rights, "post_messages", False))
              broadcast_channel_details.append({
                  "title": getattr(entity, "title", None),
                  "username": getattr(entity, "username", None),
                  "is_creator": is_creator,
                  "has_admin_rights": has_admin_rights,
                  "can_post": can_post,
                  "archived": archived,
              })

              # Include every broadcast channel where this account is the creator
              # or has any administrator rights. Posting permission is tracked
              # separately instead of silently dropping the channel from discovery.
              if not is_admin:
                  continue
              admin_candidates_seen += 1

              tg_id = int(f"-100{entity.id}") if entity.id > 0 else entity.id
              admin_channel_ids.add(tg_id)

              admin_channels.append({
                  "telegram_id": tg_id,
                  "username": getattr(entity, "username", None),
                  "title": getattr(entity, "title", None),
                  "is_creator": is_creator,
                  "can_post": can_post,
              })
              logger.info(
                  "admin_channel_found",
                  title=entity.title,
                  creator=is_creator,
                  can_post=can_post,
                  archived=archived,
              )

      # Telegram exposes public channels administered by this account through a
      # separate endpoint; some of them are not present in the dialog list.
      admined_public = await client(GetAdminedPublicChannelsRequest())
      for entity in getattr(admined_public, "chats", []):
          if not isinstance(entity, Channel) or not getattr(entity, "broadcast", False):
              continue
          tg_id = int(f"-100{entity.id}") if entity.id > 0 else entity.id
          if tg_id in admin_channel_ids:
              continue

          admined_public_channels_seen += 1
          broadcast_channels_seen += 1
          is_creator = bool(getattr(entity, "creator", False))
          admin_rights = getattr(entity, "admin_rights", None)
          can_post = is_creator or bool(getattr(admin_rights, "post_messages", False))
          admin_channel_ids.add(tg_id)
          admin_candidates_seen += 1
          broadcast_channel_details.append({
              "title": getattr(entity, "title", None),
              "username": getattr(entity, "username", None),
              "is_creator": is_creator,
              "has_admin_rights": True,
              "can_post": can_post,
              "archived": None,
              "source": "admined_public_channels",
          })
          admin_channels.append({
              "telegram_id": tg_id,
              "username": getattr(entity, "username", None),
              "title": getattr(entity, "title", None),
              "is_creator": is_creator,
              "can_post": can_post,
          })
          logger.info(
              "admin_public_channel_found",
              title=getattr(entity, "title", None),
              can_post=can_post,
          )
  except Exception as e:
      logger.error("dialog_scan_failed", error=str(e))
      return {"error": str(e), "found": 0, "added": 0, "reactivated": 0, "channels": [], "scan_stats": {"dialogs_scanned": dialogs_scanned, "broadcast_channels_seen": broadcast_channels_seen, "admin_candidates_seen": admin_candidates_seen, "broadcast_channel_details": broadcast_channel_details, "admined_public_channels_seen": admined_public_channels_seen}}

  # --- Safety guard ---------------------------------------------------
  # If iter_dialogs returned 0 admin channels, do NOT deactivate existing
  # records. This protects against transient network/session errors that
  # return an empty dialog list wiping all channels and killing auto-posting.
  if not admin_channels:
      logger.warning(
          "scan_returned_zero_channels_skipping_deactivation",
          account_id=account_id,
          note="iter_dialogs returned 0 admin channels -- skipping deactivation of existing records",
      )
      return {"found": 0, "added": 0, "reactivated": 0, "channels": [], "scan_stats": {"dialogs_scanned": dialogs_scanned, "broadcast_channels_seen": broadcast_channels_seen, "admin_candidates_seen": admin_candidates_seen}}

  added = 0
  reactivated = 0
  admin_tg_ids = {ch["telegram_id"] for ch in admin_channels}

  async with AsyncSessionLocal() as session:
      account_uuid = uuid.UUID(account_id)

      existing_result = await session.execute(
          select(TelegramChannel).where(TelegramChannel.account_id == account_uuid)
      )
      existing_records = {r.telegram_channel_id: r for r in existing_result.scalars().all()}

      for ch in admin_channels:
          tg_id = ch["telegram_id"]

          if tg_id in existing_records:
              record = existing_records[tg_id]
              record.username = ch["username"]
              record.display_name = ch["title"]
              record.metadata_ = {
                  **(record.metadata_ or {}),
                  "join_link": (
                      f"https://t.me/{ch['username'].lstrip('@')}"
                      if ch["username"]
                      else None
                  ),
                  "is_creator": ch["is_creator"],
                  "can_post": ch["can_post"],
              }
              if not record.is_active:
                  record.is_active = True
                  reactivated += 1
                  logger.info("channel_reactivated", title=ch["title"])
          else:
              channel = TelegramChannel(
                  account_id=account_uuid,
                  telegram_channel_id=tg_id,
                  username=ch["username"],
                  display_name=ch["title"],
                  language="en",
                  is_active=True,
                  metadata_={
                      "join_link": (
                          f"https://t.me/{ch['username'].lstrip('@')}"
                          if ch["username"]
                          else None
                      )
                  },
              )
              session.add(channel)
              added += 1
              logger.info("channel_registered", title=ch["title"])

      # Deactivate channels we are no longer admin of
      # (only reached when scan returned at least one result -- see guard above)
      for tg_id, record in existing_records.items():
          if tg_id not in admin_tg_ids and record.is_active:
              record.is_active = False
              logger.info("channel_deactivated_not_admin", title=record.display_name)

      await session.commit()

  logger.info(
      "scan_complete",
      found=len(admin_channels),
      added=added,
      reactivated=reactivated,
      dialogs_scanned=dialogs_scanned,
      broadcast_channels_seen=broadcast_channels_seen,
      admin_candidates_seen=admin_candidates_seen,
      admined_public_channels_seen=admined_public_channels_seen,
  )
  return {
      "found": len(admin_channels),
      "added": added,
      "reactivated": reactivated,
      "scan_stats": {
          "dialogs_scanned": dialogs_scanned,
          "broadcast_channels_seen": broadcast_channels_seen,
          "admin_candidates_seen": admin_candidates_seen,
          "broadcast_channel_details": broadcast_channel_details,
          "admined_public_channels_seen": admined_public_channels_seen,
      },
      "channels": [
          {
              "title": c["title"],
              "username": c["username"],
              "is_creator": c["is_creator"],
              "can_post": c["can_post"],
          }
          for c in admin_channels
      ],
  }
