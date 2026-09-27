"""
Admin bot handler — Proxy management

Commands / callbacks:
  /proxies  or  callback proxy_menu   — show proxy list + stats
  /addproxy <url>                      — add a proxy
    Formats accepted:
      socks5://user:pass@host:port
      socks5://host:port
      http://user:pass@host:port
      host:port                        (defaults to socks5, no auth)
  callback proxy_check_all             — re-check liveness of all proxies
  callback proxy_autoassign            — round-robin assign proxies to channels
  callback proxy_list                  — alias for proxy_menu
"""
import re
import uuid
from urllib.parse import urlparse

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from sqlalchemy import select, update, func
from app.db.session import AsyncSessionLocal
from app.models.proxy import Proxy
from app.models.channel import TelegramChannel
from app.services.admin_bot.keyboards import back_kb, proxy_menu_kb
from app.core.logging import get_logger

router = Router()
logger = get_logger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_proxy_url(raw: str) -> dict | None:
    """
    Parse a proxy URL string into a dict with keys:
      proxy_type, host, port, username, password
    Returns None if parsing fails.
    """
    raw = raw.strip()
    # bare host:port  (no scheme)
    if "://" not in raw:
        parts = raw.split(":")
        if len(parts) == 2:
            try:
                return {"proxy_type": "socks5", "host": parts[0], "port": int(parts[1]),
                        "username": None, "password": None}
            except ValueError:
                return None
        return None

    try:
        p = urlparse(raw)
        scheme = p.scheme.lower()
        if scheme not in ("socks5", "http", "https", "socks4"):
            return None
        proxy_type = "http" if scheme in ("http", "https") else "socks5"
        return {
            "proxy_type": proxy_type,
            "host": p.hostname,
            "port": p.port,
            "username": p.username or None,
            "password": p.password or None,
        }
    except Exception:
        return None


async def _proxy_stats() -> dict:
    async with AsyncSessionLocal() as session:
        # FIX: wrap every func.count() in select() — bare func.count() is not executable
        total = (await session.execute(select(func.count(Proxy.id)))).scalar() or 0
        active = (await session.execute(
            select(func.count(Proxy.id)).where(Proxy.is_active == True)
        )).scalar() or 0
        alive = (await session.execute(
            select(func.count(Proxy.id)).where(Proxy.is_active == True, Proxy.is_alive == True)
        )).scalar() or 0
        assigned = (await session.execute(
            select(func.count(TelegramChannel.id)).where(TelegramChannel.proxy_id != None)
        )).scalar() or 0
        channels_total = (await session.execute(
            select(func.count(TelegramChannel.id)).where(TelegramChannel.is_active == True)
        )).scalar() or 0
    return {"total": total, "active": active, "alive": alive,
            "assigned": assigned, "channels_total": channels_total}


# ── /proxies ─────────────────────────────────────────────────────────────────

@router.message(Command("proxies"))
@router.callback_query(F.data.in_({"proxy_menu", "proxy_list"}))
async def proxy_menu(event: Message | CallbackQuery):
    msg = event if isinstance(event, Message) else event.message

    stats = await _proxy_stats()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Proxy).where(Proxy.is_active == True).order_by(Proxy.created_at.desc()).limit(20)
        )
        proxies = result.scalars().all()

    lines = []
    for p in proxies:
        icon = "🟢" if p.is_alive else "🔴"
        auth = f" ({p.username})" if p.username else ""
        label = f" [{p.label}]" if p.label else ""
        lines.append(f"{icon} `{p.host}:{p.port}`{auth}{label}")

    proxy_list = "\n".join(lines) if lines else "  _(no proxies yet)_"

    text = (
        "🌐 *Proxy Manager*\n\n"
        f"📊 Total: `{stats['total']}` | Active: `{stats['active']}` | "
        f"🟢 Alive: `{stats['alive']}`\n"
        f"🔗 Channels with proxy: `{stats['assigned']}` / `{stats['channels_total']}`\n\n"
        f"{proxy_list}\n\n"
        "➕ Add proxy:\n`/addproxy socks5://user:pass@host:port`"
    )
    await msg.answer(text, parse_mode="Markdown", reply_markup=proxy_menu_kb())
    if isinstance(event, CallbackQuery):
        await event.answer()


# ── /addproxy ────────────────────────────────────────────────────────────────

@router.message(Command("addproxy"))
async def add_proxy(message: Message):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "❌ Usage:\n`/addproxy socks5://user:pass@host:port`\nor\n`/addproxy host:port`",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return

    parsed = _parse_proxy_url(parts[1])
    if not parsed or not parsed.get("host") or not parsed.get("port"):
        await message.answer("❌ Invalid proxy format. Use: `socks5://user:pass@host:port`",
                             parse_mode="Markdown", reply_markup=back_kb())
        return

    async with AsyncSessionLocal() as session:
        proxy = Proxy(
            proxy_type=parsed["proxy_type"],
            host=parsed["host"],
            port=parsed["port"],
            username=parsed.get("username"),
            password=parsed.get("password"),
            is_active=True,
            is_alive=True,
        )
        session.add(proxy)
        await session.commit()
        await session.refresh(proxy)

    await message.answer(
        f"✅ Proxy added!\n`{parsed['proxy_type']}://{parsed['host']}:{parsed['port']}`\n\n"
        "Run /proxies to see the list, or use *Auto-Assign* to assign to channels.",
        parse_mode="Markdown",
        reply_markup=proxy_menu_kb(),
    )


# ── Check all proxies ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "proxy_check_all")
async def proxy_check_all(callback: CallbackQuery):
    await callback.message.answer("🔍 Checking all proxies... (این ممکنه چند ثانیه طول بکشه)")
    await callback.answer()

    from app.services.proxy.checker import check_all_proxies
    async with AsyncSessionLocal() as session:
        result = await check_all_proxies(session)

    await callback.message.answer(
        f"✅ Check complete!\n🟢 Alive: `{result['alive']}` | 🔴 Dead: `{result['dead']}` | "
        f"Total: `{result['total']}`",
        parse_mode="Markdown",
        reply_markup=proxy_menu_kb(),
    )


# ── Auto-assign proxies to channels ──────────────────────────────────────────

@router.callback_query(F.data == "proxy_autoassign")
async def proxy_autoassign(callback: CallbackQuery):
    await callback.message.answer("🔄 Auto-assigning proxies to channels...")
    await callback.answer()

    async with AsyncSessionLocal() as session:
        # Get alive proxies
        proxy_result = await session.execute(
            select(Proxy).where(Proxy.is_active == True, Proxy.is_alive == True)
        )
        proxies = proxy_result.scalars().all()

        if not proxies:
            await callback.message.answer(
                "❌ No alive proxies found. Add proxies first with /addproxy",
                reply_markup=proxy_menu_kb(),
            )
            return

        # Get all active channels
        channel_result = await session.execute(
            select(TelegramChannel).where(TelegramChannel.is_active == True)
        )
        channels = channel_result.scalars().all()

        if not channels:
            await callback.message.answer("❌ No active channels found.", reply_markup=proxy_menu_kb())
            return

        # Round-robin assign
        assigned = 0
        for idx, channel in enumerate(channels):
            proxy = proxies[idx % len(proxies)]
            channel.proxy_id = proxy.id
            assigned += 1

        await session.commit()

    lines = []
    async with AsyncSessionLocal() as session:
        ch_result = await session.execute(
            select(TelegramChannel, Proxy)
            .join(Proxy, TelegramChannel.proxy_id == Proxy.id)
            .where(TelegramChannel.is_active == True)
            .limit(20)
        )
        rows = ch_result.all()
        for channel, proxy in rows:
            name = channel.display_name or channel.username or str(channel.telegram_channel_id)
            lines.append(f"• {name[:25]} → `{proxy.host}:{proxy.port}`")

    preview = "\n".join(lines) if lines else ""
    await callback.message.answer(
        f"✅ Assigned {assigned} channels across {len(proxies)} proxies!\n\n{preview}",
        parse_mode="Markdown",
        reply_markup=proxy_menu_kb(),
    )


# ── Remove dead proxies ───────────────────────────────────────────────────────

@router.callback_query(F.data == "proxy_remove_dead")
async def proxy_remove_dead(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        # Unassign channels using dead proxies first
        await session.execute(
            update(TelegramChannel)
            .where(
                TelegramChannel.proxy_id.in_(
                    select(Proxy.id).where(Proxy.is_alive == False)
                )
            )
            .values(proxy_id=None)
        )
        # Deactivate dead proxies
        result = await session.execute(
            update(Proxy).where(Proxy.is_alive == False).values(is_active=False)
        )
        removed = result.rowcount
        await session.commit()

    await callback.message.answer(
        f"🗑 Deactivated {removed} dead proxy/proxies and unassigned their channels.",
        reply_markup=proxy_menu_kb(),
    )
    await callback.answer()
