from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from app.core.config import settings
from app.services.monitoring.health import full_health_check
from app.services.admin_bot.keyboards import main_menu_kb, back_kb

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    text = (
        "🤖 *Telegram Sales Agent — Admin Panel*\n\n"
        "Your AI-powered sales & support system is running.\n"
        "Use the menu below to monitor and control everything."
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu_kb())


@router.message(Command("myid"))
async def cmd_myid(message: Message):
    """Public command — no admin check — returns caller's Telegram ID."""
    user = message.from_user
    if not user:
        await message.answer("❌ Could not determine your identity.")
        return

    admin_ids = settings.admin_ids
    is_admin = user.id in admin_ids

    text = (
        f"🆔 *Your Telegram ID:* `{user.id}`\n"
        f"👤 Name: {user.full_name or 'Unknown'}\n"
        f"🔑 Admin access: {'✅ Yes' if is_admin else '❌ No'}"
    )
    if not is_admin:
        text += (
            f"\n\nTo grant yourself admin access, go to Render → "
            f"Environment Variables and set:\n"
            f"`ADMIN_TELEGRAM_IDS={user.id}`"
        )
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("status"))
@router.callback_query(F.data == "status")
async def show_status(event: Message | CallbackQuery):
    msg = event if isinstance(event, Message) else event.message
    await msg.answer("⏳ Checking system status...")

    health = await full_health_check()
    status_emoji = {"ok": "✅", "degraded": "⚠️", "critical": "🔴"}.get(health["status"], "❓")

    from app.services.userbot.manager import userbot_manager
    accounts = userbot_manager.list_accounts()
    connected = sum(1 for a in accounts if a["is_connected"])

    lines = [f"{status_emoji} *System: {health['status'].upper()}*\n"]

    for svc_name, svc_status in health["services"].items():
        svc_emoji = "✅" if svc_status["status"] == "ok" else "❌"
        lines.append(f"{svc_emoji} {svc_name.capitalize()}: `{svc_status['status']}`")
        if "error" in svc_status:
            lines.append(f"   └ _{svc_status['error'][:80]}_")

    lines.append("")
    lines.append(f"📱 *UserBots*: {connected}/{len(accounts)} connected")
    for acc in accounts:
        acc_emoji = "🟢" if acc["is_connected"] else "🔴"
        failures = acc.get("reconnect_failures", 0)
        fail_str = f" (⚠️ {failures} failures)" if failures > 0 else ""
        lines.append(f"  {acc_emoji} {acc['phone']}{fail_str}")
        identity_bits = []
        if acc.get("telegram_username"):
            identity_bits.append(f"@{acc['telegram_username']}")
        if acc.get("telegram_user_id"):
            identity_bits.append(f"ID: {acc['telegram_user_id']}")
        if identity_bits:
            lines.append("     └ Telegram: " + " | ".join(identity_bits))

    await msg.answer("\n".join(lines), parse_mode="Markdown", reply_markup=back_kb())
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.callback_query(F.data == "main_menu")
async def show_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "🤖 *Admin Panel — Main Menu*",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()
