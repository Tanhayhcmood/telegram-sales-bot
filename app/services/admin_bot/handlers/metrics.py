from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from app.services.monitoring.metrics_collector import get_cached_metrics, get_daily_stats, get_weekly_stats
from app.services.admin_bot.keyboards import back_kb, metrics_kb

router = Router()


@router.message(Command("metrics"))
@router.callback_query(F.data == "metrics")
async def show_metrics(event: Message | CallbackQuery):
    msg = event if isinstance(event, Message) else event.message
    metrics = await get_cached_metrics()
    stats = await get_daily_stats()

    cpu = metrics.get("cpu_percent", 0)
    ram = metrics.get("ram", {})
    disk = metrics.get("disk", {})
    net = metrics.get("network", {})
    proc = metrics.get("process", {})
    uptime = metrics.get("uptime_hours", 0)

    cpu_bar = _progress_bar(cpu)
    ram_bar = _progress_bar(ram.get("percent", 0))
    disk_bar = _progress_bar(disk.get("percent", 0))

    msgs_in = stats.get("messages_received", 0)
    msgs_out = stats.get("messages_sent", 0)
    response_rate = f"{round(msgs_out / msgs_in * 100)}%" if msgs_in > 0 else "N/A"

    tokens = stats.get("tokens_used", 0)
    cost_cents = 0
    try:
        from app.cache.redis_client import cache_get
        from datetime import date
        today = date.today().isoformat()
        raw = await cache_get(f"stats:daily:{today}:cost_cents")
        cost_cents = int(raw) if raw else 0
    except Exception:
        pass
    cost_str = f"${cost_cents / 100:.2f}" if cost_cents else "< $0.01"

    text = (
        "📈 *System Metrics*\n\n"
        f"⏱ Uptime: `{uptime:.1f}h` ({metrics.get('uptime_days', 0):.1f}d)\n"
        f"🖥 CPU: {cpu:.1f}% × {metrics.get('cpu_count', '?')} cores {cpu_bar}\n"
        f"💾 RAM: {ram.get('used_gb', 0):.1f}/{ram.get('total_gb', 0):.1f} GB {ram_bar}\n"
        f"💿 Disk: {disk.get('used_gb', 0):.1f}/{disk.get('total_gb', 0):.1f} GB {disk_bar}\n"
        f"🌐 Net ↑{net.get('bytes_sent_mb', 0):.1f} MB ↓{net.get('bytes_recv_mb', 0):.1f} MB\n"
        f"🔧 Process RAM: {proc.get('rss_mb', 0):.0f} MB\n\n"
        f"📊 *Today's Stats*\n"
        f"📩 Messages: {msgs_in} in / {msgs_out} out ({response_rate} response rate)\n"
        f"👤 New customers: {stats.get('new_customers', 0)}\n"
        f"📢 Posts published: {stats.get('posts_published', 0)}\n"
        f"🎯 New leads: {stats.get('leads_created', 0)}\n"
        f"📤 Follow-ups sent: {stats.get('followups_sent', 0)}\n"
        f"🤖 AI calls: {stats.get('ai_calls', 0)} | Tokens: {tokens:,}\n"
        f"💰 AI cost today: {cost_str}\n"
    )

    await msg.answer(text, parse_mode="Markdown", reply_markup=metrics_kb())
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.callback_query(F.data == "metrics_weekly")
async def show_weekly_metrics(callback: CallbackQuery):
    weekly = await get_weekly_stats()

    lines = ["📅 *7-Day Performance Trend*\n"]
    for day in weekly:
        d = day["date"][-5:]
        msgs = day.get("messages_received", 0)
        leads = day.get("leads_created", 0)
        customers = day.get("new_customers", 0)
        lines.append(f"`{d}` — 📩 {msgs} msgs | 🎯 {leads} leads | 👤 {customers} new")

    total_msgs = sum(d.get("messages_received", 0) for d in weekly)
    total_leads = sum(d.get("leads_created", 0) for d in weekly)
    lines.append(f"\n*7-day totals:* {total_msgs} messages, {total_leads} leads")

    await callback.message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=back_kb())
    await callback.answer()


@router.callback_query(F.data == "metrics_cost")
async def show_cost_report(callback: CallbackQuery):
    from app.cache.redis_client import cache_get
    from datetime import date, timedelta

    lines = ["💰 *AI Cost Report (Last 7 Days)*\n"]
    total_cost = 0
    today = date.today()

    for i in range(7):
        day = (today - timedelta(days=i)).isoformat()
        tokens_raw = await cache_get(f"stats:daily:{day}:tokens_used")
        cost_raw = await cache_get(f"stats:daily:{day}:cost_cents")
        tokens = int(tokens_raw) if tokens_raw else 0
        cost_cents = int(cost_raw) if cost_raw else 0
        total_cost += cost_cents
        d = day[-5:]
        cost_str = f"${cost_cents / 100:.2f}" if cost_cents else "$0.00"
        lines.append(f"`{d}` — {tokens:,} tokens → {cost_str}")

    lines.append(f"\n*7-day total: ${total_cost / 100:.2f}*")

    await callback.message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=back_kb())
    await callback.answer()


def _progress_bar(percent: float, length: int = 10) -> str:
    filled = int(percent / 100 * length)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percent:.0f}%"
