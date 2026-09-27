from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from app.db.session import AsyncSessionLocal
from app.models.post import Post
from app.models.account import TelegramAccount
from app.models.channel import TelegramChannel
from app.services.content.generator import generate_post
from app.services.channel.publisher import publish_post
from app.services.admin_bot.keyboards import (
    back_kb, publishing_menu_kb, post_type_kb,
    post_preview_kb, post_image_skip_kb,
)
from app.core.logging import get_logger
from sqlalchemy import select, func
import uuid
import os
from pathlib import Path

logger = get_logger(__name__)
router = Router()

TYPE_LABELS = {
    "educational": "🧠 Educational",
    "marketing": "🔥 Marketing",
    "technical": "⚙️ Technical",
    "announcement": "📣 Announcement",
    "comparison": "⚖️ Comparison",
    "promotion": "🎯 Promotion",
    "viral_giveaway": "🎁 Giveaway",
    "viral_poll_engagement": "🗳️ Poll/Engagement",
    "viral_tip_secret": "🤫 Secret Tip",
    "viral_free_resource": "📦 Free Resource",
    "viral_news_hook": "🚨 Breaking News",
}


class PostStates(StatesGroup):
    choosing_type = State()
    entering_topic = State()
    reviewing_post = State()
    adding_image = State()


# ─── Main Publishing Menu ────────────────────────────────────────────────────

@router.message(Command("publishing"))
@router.callback_query(F.data == "publishing")
async def show_publishing(event: Message | CallbackQuery, state: FSMContext):
    await state.clear()
    msg = event if isinstance(event, Message) else event.message

    async with AsyncSessionLocal() as session:
        total = (await session.execute(select(func.count(Post.id)))).scalar() or 0
        published = (await session.execute(
            select(func.count(Post.id)).where(Post.status == "published")
        )).scalar() or 0
        scheduled = (await session.execute(
            select(func.count(Post.id)).where(Post.status == "scheduled")
        )).scalar() or 0
        failed = (await session.execute(
            select(func.count(Post.id)).where(Post.status == "failed")
        )).scalar() or 0
        channels = (await session.execute(
            select(func.count(TelegramChannel.id)).where(TelegramChannel.is_active == True)
        )).scalar() or 0

    text = (
        "📢 *Publishing*\n\n"
        f"📋 Total posts: `{total}`\n"
        f"✅ Published: `{published}`\n"
        f"⏰ Scheduled: `{scheduled}`\n"
        f"❌ Failed: `{failed}`\n"
        f"📡 Active channels: `{channels}`\n"
    )

    await msg.answer(text, parse_mode="Markdown", reply_markup=publishing_menu_kb())
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.callback_query(F.data == "post_stats")
async def show_stats(callback: CallbackQuery, state: FSMContext):
    await show_publishing(callback, state)


# ─── Step 1: Choose Post Type ────────────────────────────────────────────────

@router.callback_query(F.data == "post_new")
async def start_new_post(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PostStates.choosing_type)
    text = (
        "✏️ *Create New Post*\n\n"
        "Choose the type of content you want to create:"
    )
    try:
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=post_type_kb(),
        )
    except Exception:
        await callback.message.answer(
            text,
            parse_mode="Markdown",
            reply_markup=post_type_kb(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("ptype_"), PostStates.choosing_type)
async def choose_type(callback: CallbackQuery, state: FSMContext):
    content_type = callback.data.replace("ptype_", "")
    type_label = TYPE_LABELS.get(content_type, content_type)
    await state.update_data(content_type=content_type)
    await state.set_state(PostStates.entering_topic)
    text = (
        f"*Type selected:* {type_label}\n\n"
        "✍️ Now send me the *topic* for this post.\n\n"
        "_Example: NVMe SSD speed advantages for WordPress / VPS vs shared hosting / 50% discount on VPS plans_"
    )
    try:
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=post_image_skip_kb(),
        )
    except Exception:
        await callback.message.answer(
            text,
            parse_mode="Markdown",
            reply_markup=post_image_skip_kb(),
        )
    await callback.answer()


# ─── Step 2: Enter Topic → Generate ─────────────────────────────────────────

@router.message(PostStates.entering_topic)
async def receive_topic(message: Message, state: FSMContext):
    topic = message.text.strip()
    if not topic:
        await message.answer("⚠️ Please send a valid topic.")
        return

    data = await state.get_data()
    content_type = data.get("content_type", "educational")
    type_label = TYPE_LABELS.get(content_type, content_type)

    thinking_msg = await message.answer(
        f"⚡ *Generating your {type_label} post…*\n\n"
        "_AI is crafting a premium post — this takes 5–10 seconds_",
        parse_mode="Markdown",
    )

    try:
        content = await generate_post(content_type, topic, language="en", include_hashtags=True)
    except Exception as e:
        logger.error("admin_post_generation_failed", error=str(e))
        err_detail = str(e)[:250] if str(e) else "Unknown error"
        await thinking_msg.edit_text(
            f"❌ *Generation failed*\n\n```\n{err_detail}\n```\n_Check GROQ\\_API\\_KEY on Render._",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return

    await state.update_data(topic=topic, content=content, image_url=None)
    await state.set_state(PostStates.reviewing_post)
    await thinking_msg.delete()
    try:
        await _send_preview(message, state, content, image_url=None)
    except Exception as preview_err:
        logger.error("admin_preview_send_failed", error=str(preview_err))
        await message.answer(
            f"❌ *Preview render failed*\n\n`{str(preview_err)[:250]}`",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        await state.clear()


async def _send_preview(
    target: Message,
    state: FSMContext,
    content: str,
    image_url: str | None,
):
    data = await state.get_data()
    content_type = data.get("content_type", "educational")
    type_label = TYPE_LABELS.get(content_type, content_type)
    topic = data.get("topic", "")
    safe_topic = topic.replace("_", "\\_")
    image_note = "🖼 *Image attached*" if image_url else "📄 *Text only* _(you can add an image below)_"

    header = (
        f"👁 *Post Preview*\n"
        f"Type: {type_label}  |  Topic: _{safe_topic}_\n"
        f"{image_note}\n"
        f"{'─' * 30}\n\n"
    )

    try:
        await target.answer(
            header + content,
            parse_mode="Markdown",
            reply_markup=post_preview_kb(has_image=bool(image_url)),
        )
    except Exception:
        plain_header = (
            f"👁 Post Preview\n"
            f"Type: {type_label}  |  Topic: {topic}\n"
            f"{'─' * 30}\n\n"
        )
        await target.answer(
            plain_header + content,
            reply_markup=post_preview_kb(has_image=bool(image_url)),
        )


# ─── Step 3: Actions on Preview ─────────────────────────────────────────────

@router.callback_query(F.data == "post_regenerate", PostStates.reviewing_post)
async def regenerate_post(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    topic = data.get("topic", "")
    content_type = data.get("content_type", "educational")
    type_label = TYPE_LABELS.get(content_type, content_type)

    await callback.message.edit_text(
        f"⚡ *Regenerating {type_label} post…*\n\n_One moment…_",
        parse_mode="Markdown",
    )
    await callback.answer()

    try:
        content = await generate_post(content_type, topic, language="en", include_hashtags=True)
    except Exception as e:
        logger.error("admin_post_regeneration_failed", error=str(e))
        await callback.message.edit_text(
            "❌ *Regeneration failed.* Please try again.",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return

    image_url = data.get("image_url")
    await state.update_data(content=content)
    await callback.message.delete()
    try:
        await _send_preview(callback.message, state, content, image_url=image_url)
    except Exception as preview_err:
        logger.error("admin_regen_preview_failed", error=str(preview_err))
        await callback.message.answer(
            f"❌ *Preview render failed*\n\n`{str(preview_err)[:250]}`",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        await state.clear()


@router.callback_query(F.data == "post_add_image", PostStates.reviewing_post)
async def request_image(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PostStates.adding_image)
    await callback.message.answer(
        "🖼 *Send me the image* for this post.\n\n"
        "_Send a photo directly in the chat. It will be attached to the post when published._",
        parse_mode="Markdown",
        reply_markup=post_image_skip_kb(),
    )
    await callback.answer()


@router.message(PostStates.adding_image, F.photo)
async def receive_image(message: Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    try:
        file = await bot.get_file(photo.file_id)
        temp_dir = "/tmp/post_images"
        os.makedirs(temp_dir, exist_ok=True)
        local_path = f"{temp_dir}/{photo.file_id}.jpg"
        await bot.download_file(file.file_path, local_path)
        image_url = local_path
        await state.update_data(image_url=image_url)
        logger.info("post_image_received", file_id=photo.file_id, local_path=local_path)
    except Exception as e:
        logger.error("admin_image_fetch_failed", error=str(e))
        await message.answer("❌ Failed to process image. Try again or skip.")
        return

    await state.set_state(PostStates.reviewing_post)
    data = await state.get_data()
    content = data.get("content", "")
    await message.answer("✅ *Image attached!* Here's your updated preview:")
    await _send_preview(message, state, content, image_url=image_url)


@router.callback_query(F.data == "post_skip_image")
async def skip_image(callback: CallbackQuery, state: FSMContext):
    current = await state.get_state()
    if current == PostStates.adding_image:
        await state.set_state(PostStates.reviewing_post)
        data = await state.get_data()
        content = data.get("content", "")
        image_url = data.get("image_url")
        await callback.message.answer("📄 *No image — text only.* Here's your preview:")
        await _send_preview(callback.message, state, content, image_url=image_url)
    elif current == PostStates.entering_topic:
        await callback.answer("Please send the topic first.", show_alert=True)
        return
    await callback.answer()


# ─── Step 4: Send Now ────────────────────────────────────────────────────────

@router.callback_query(F.data == "post_send_now", PostStates.reviewing_post)
async def send_post_now(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    content = data.get("content", "")
    content_type = data.get("content_type", "announcement")
    image_url = data.get("image_url")

    if not content:
        await callback.answer("❌ No content to send.", show_alert=True)
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    status_msg = await callback.message.answer(
        "🚀 *Publishing to all active channels…*",
        parse_mode="Markdown",
    )
    await callback.answer()

    async with AsyncSessionLocal() as session:
        accounts_result = await session.execute(
            select(TelegramAccount).where(TelegramAccount.is_active == True)
        )
        accounts = accounts_result.scalars().all()

        if not accounts:
            await status_msg.edit_text(
                "❌ *No active Telegram accounts found.*\n\nAdd an account first via the API.",
                parse_mode="Markdown",
                reply_markup=back_kb(),
            )
            await state.clear()
            return

        channels_result = await session.execute(
            select(TelegramChannel).where(TelegramChannel.is_active == True)
        )
        channels = channels_result.scalars().all()

        if not channels:
            await status_msg.edit_text(
                "❌ *No active channels found.*\n\nScan channels first via Control → Scan Channels.",
                parse_mode="Markdown",
                reply_markup=back_kb(),
            )
            await state.clear()
            return

        account = accounts[0]
        channel_ids = [str(ch.id) for ch in channels]

        post = Post(
            account_id=account.id,
            content=content,
            content_type=content_type,
            languages={"en": content},
            channel_ids=channel_ids,
            image_url=image_url,
            status="publishing",
        )
        session.add(post)
        await session.commit()
        await session.refresh(post)

        try:
            from app.services.channel.publisher import publish_post as do_publish
            results = await do_publish(session, post)
            await session.commit()
        except Exception as e:
            logger.error("admin_publish_failed", error=str(e))
            await status_msg.edit_text(
                f"❌ *Publishing error:*\n`{str(e)[:300]}`",
                parse_mode="Markdown",
                reply_markup=back_kb(),
            )
            await state.clear()
            return

    published = sum(1 for r in results.values() if r.get("status") == "published")
    skipped = sum(1 for r in results.values() if r.get("status") == "skipped")
    failed_count = sum(1 for r in results.values() if r.get("status") == "error")
    image_note = " 🖼" if image_url else ""

    summary = (
        f"✅ *Post Published!*{image_note}\n\n"
        f"📡 Channels: {len(channels)}\n"
        f"✅ Published: `{published}`\n"
        f"⏭ Skipped: `{skipped}`\n"
        f"❌ Failed: `{failed_count}`\n"
    )
    await status_msg.edit_text(summary, parse_mode="Markdown", reply_markup=publishing_menu_kb())
    await state.clear()
    logger.info("admin_post_published", published=published, total=len(channels), has_image=bool(image_url))


# ─── Flash Sale ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "flash_sale")
async def handle_flash_sale(callback: CallbackQuery, state: FSMContext):
    logger.info(
        "flash_sale_callback_received",
        callback_id=callback.id,
        admin_id=callback.from_user.id if callback.from_user else None,
    )
    await state.clear()
    await callback.answer()

    try:
        try:
            status_msg = await callback.message.edit_text(
                "⚡ *Building Flash Sale post...*",
                parse_mode="Markdown",
            )
        except Exception as status_error:
            logger.warning("flash_sale_status_edit_failed", error=str(status_error))
            status_msg = await callback.message.answer(
                "⚡ *Building Flash Sale post...*",
                parse_mode="Markdown",
            )

        from app.services.content.flash_sale_builder import build_flash_sale_post

        async with AsyncSessionLocal() as session:
            channels_q = await session.execute(
                select(TelegramChannel).where(TelegramChannel.is_active == True)
            )
            channels = channels_q.scalars().all()

            accounts_q = await session.execute(
                select(TelegramAccount).where(TelegramAccount.is_active == True).limit(1)
            )
            accounts = accounts_q.scalars().all()

            if not channels or not accounts:
                await status_msg.edit_text(
                    "❌ No active channels or accounts found.",
                    reply_markup=back_kb(),
                )
                return

            account = accounts[0]
            channel_ids = [str(ch.id) for ch in channels]
            ch_username = channels[0].username if channels else None

            content, image_url = build_flash_sale_post(
                channel_username=ch_username,
                duration_hours=2,
            )
            logo_path = image_url.removeprefix("FILE:") if image_url else ""
            # publishing.py -> handlers -> admin_bot -> services -> app -> repo root
            logo_file = Path(__file__).resolve().parents[4] / logo_path
            if not image_url or not image_url.startswith("FILE:") or not logo_file.is_file():
                raise RuntimeError(f"Flash Sale logo is missing: {logo_file}")
            if len(content) > 1020:
                raise RuntimeError(
                    f"Flash Sale caption is too long for Telegram: {len(content)} characters"
                )
            logger.info(
                "flash_sale_logo_verified",
                path=str(logo_file),
                size_bytes=logo_file.stat().st_size,
                channels=len(channels),
            )

            post = Post(
                account_id=account.id,
                content=content,
                content_type="promotion",
                languages={"en": content},
                channel_ids=channel_ids,
                image_url=image_url or None,
                status="publishing",
            )
            session.add(post)
            await session.commit()
            await session.refresh(post)

            from app.services.channel.publisher import publish_post as do_publish
            pub_results = await do_publish(session, post, require_media=True)
            await session.commit()

        published = sum(1 for r in pub_results.values() if r.get("status") == "published")
        failed_count = sum(1 for r in pub_results.values() if r.get("status") == "error")
        with_media = sum(
            1 for r in pub_results.values()
            if r.get("status") == "published" and r.get("has_media") is True
        )

        await status_msg.edit_text(
            f"⚡ *Flash Sale Posted!*\n\n"
            f"📡 Channels: {len(channels)}\n"
            f"✅ Published with logo: `{with_media}`\n"
            f"❌ Failed: `{failed_count}`\n",
            parse_mode="Markdown",
            reply_markup=publishing_menu_kb(),
        )
        logger.info(
            "flash_sale_published",
            published=published,
            published_with_logo=with_media,
            failed=failed_count,
            total=len(channels),
        )

    except Exception as e:
        logger.error("flash_sale_handler_error", error=str(e))
        await status_msg.edit_text(
            f"❌ Error: {str(e)[:200]}",
            reply_markup=back_kb(),
        )
