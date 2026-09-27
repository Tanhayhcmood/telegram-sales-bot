from typing import List
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 System Status", callback_data="status")
    builder.button(text="📈 Metrics", callback_data="metrics")
    builder.button(text="💬 Conversations", callback_data="conversations")
    builder.button(text="🎯 Sales & Leads", callback_data="sales")
    builder.button(text="📢 Publishing", callback_data="publishing")
    builder.button(text="📋 Logs", callback_data="logs")
    builder.button(text="⚙️ Control", callback_data="control")
    builder.button(text="🔔 Alerts", callback_data="alerts_menu")
    builder.button(text="🔍 IP Scanner", callback_data="scanner")
    builder.button(text="🌐 Proxies", callback_data="proxy_menu")
    builder.adjust(2)
    return builder.as_markup()



def publishing_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Create New Post", callback_data="post_new")
    builder.button(text="⚡ Flash Sale", callback_data="flash_sale")
    builder.button(text="📊 Publishing Stats", callback_data="post_stats")
    builder.button(text="🔙 Main Menu", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def post_type_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🧠 Educational", callback_data="ptype_educational")
    builder.button(text="🔥 Marketing", callback_data="ptype_marketing")
    builder.button(text="⚙️ Technical", callback_data="ptype_technical")
    builder.button(text="📣 Announcement", callback_data="ptype_announcement")
    builder.button(text="⚖️ Comparison", callback_data="ptype_comparison")
    builder.button(text="🎯 Promotion", callback_data="ptype_promotion")
    builder.button(text="🎁 Giveaway", callback_data="ptype_viral_giveaway")
    builder.button(text="🗳️ Poll/Engagement", callback_data="ptype_viral_poll_engagement")
    builder.button(text="🤫 Secret Tip", callback_data="ptype_viral_tip_secret")
    builder.button(text="📦 Free Resource", callback_data="ptype_viral_free_resource")
    builder.button(text="🚨 Breaking News", callback_data="ptype_viral_news_hook")
    builder.button(text="❌ Cancel", callback_data="publishing")
    builder.adjust(2)
    return builder.as_markup()


def post_preview_kb(has_image: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Send Now", callback_data="post_send_now")
    if not has_image:
        builder.button(text="🖼 Add Image", callback_data="post_add_image")
    else:
        builder.button(text="🖼 Change Image", callback_data="post_add_image")
    builder.button(text="🔄 Regenerate", callback_data="post_regenerate")
    builder.button(text="❌ Cancel", callback_data="publishing")
    builder.adjust(2)
    return builder.as_markup()


def post_image_skip_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Skip (Text Only)", callback_data="post_skip_image")
    builder.button(text="❌ Cancel", callback_data="publishing")
    builder.adjust(1)
    return builder.as_markup()


def control_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Start UserBot", callback_data="ctrl_start")
    builder.button(text="⏹️ Stop UserBot", callback_data="ctrl_stop")
    builder.button(text="🔄 Restart UserBot", callback_data="ctrl_restart")
    builder.button(text="⏸️ Pause Posting", callback_data="ctrl_pause_posting")
    builder.button(text="▶️ Resume Posting", callback_data="ctrl_resume_posting")
    builder.button(text="📡 Scan Channels", callback_data="ctrl_scan_channels")
    builder.button(text="🚀 پست فوری همه کانال‌ها", callback_data="ctrl_post_now")
    builder.button(text="🖥 پست سرور رایگان فوری", callback_data="ctrl_rdp_post_now")
    builder.button(text="🖼 پیش‌نمایش تصویر RDP", callback_data="ctrl_rdp_preview_image")
    builder.button(text="📋 پست پلن‌های RDP", callback_data="ctrl_rdp_plans_post")
    builder.button(text="🔁 Reset Cooldowns", callback_data="ctrl_reset_cooldowns")
    builder.button(text="🩺 Channel Diag", callback_data="ctrl_channel_diag")
    builder.button(text="🔙 Back", callback_data="main_menu")
    builder.adjust(2)
    return builder.as_markup()


def proxy_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Auto-Assign to Channels", callback_data="proxy_autoassign")
    builder.button(text="🔍 Check All Liveness", callback_data="proxy_check_all")
    builder.button(text="🗑 Remove Dead Proxies", callback_data="proxy_remove_dead")
    builder.button(text="📋 Refresh List", callback_data="proxy_list")
    builder.button(text="🔙 Main Menu", callback_data="main_menu")
    builder.adjust(2)
    return builder.as_markup()


def back_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Main Menu", callback_data="main_menu")
    return builder.as_markup()


def logs_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Error Logs", callback_data="logs_errors")
    builder.button(text="📊 Daily Report", callback_data="logs_daily")
    builder.button(text="📅 Weekly Report", callback_data="logs_weekly")
    builder.button(text="🔙 Back", callback_data="main_menu")
    builder.adjust(2)
    return builder.as_markup()


def sales_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔥 Hot Leads", callback_data="sales_hot")
    builder.button(text="📊 Pipeline", callback_data="sales_pipeline")
    builder.button(text="🔙 Back", callback_data="main_menu")
    builder.adjust(2)
    return builder.as_markup()


def metrics_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Weekly Trend", callback_data="metrics_weekly")
    builder.button(text="💰 Cost Report", callback_data="metrics_cost")
    builder.button(text="🔙 Back", callback_data="main_menu")
    builder.adjust(2)
    return builder.as_markup()


def confirm_kb(action: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Confirm", callback_data=f"confirm_{action}")
    builder.button(text="❌ Cancel", callback_data="main_menu")
    builder.adjust(2)
    return builder.as_markup()
