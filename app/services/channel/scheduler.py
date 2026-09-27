from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.models.post import Post
from app.services.channel.publisher import publish_post
from app.core.logging import get_logger
from datetime import datetime, timezone

logger = get_logger(__name__)


async def process_scheduled_posts(session: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(Post).where(
            and_(
                Post.status == "scheduled",
                Post.scheduled_at <= now,
            )
        )  # no LIMIT — process every due post; a hard cap of 10 silently drops posts
    )
    posts = result.scalars().all()

    published_count = 0
    for post in posts:
        post.status = "publishing"
        try:
            await publish_post(session, post)
            published_count += 1
            logger.info("scheduled_post_published", post_id=str(post.id))
        except Exception as e:
            post.status = "failed"
            logger.error("scheduled_post_failed", post_id=str(post.id), error=str(e))

    await session.commit()
    return published_count
