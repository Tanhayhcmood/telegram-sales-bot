from fastapi import APIRouter, HTTPException
from app.api.deps import DBSession, APIKeyDep
from app.services.content.generator import generate_post, generate_multilingual_post
from app.services.content.desktop_image_generator import (
    DesktopImageGenerationError,
    generate_desktop_image,
)
from app.models.post import Post
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid

router = APIRouter(prefix="/content", tags=["content"])

SUPPORTED_TYPES = [
    "educational", "marketing", "technical", "announcement",
    "viral_giveaway", "viral_free_resource", "viral_tip_secret",
    "viral_poll_engagement", "viral_news_hook",
]
SUPPORTED_LANGUAGES = ["en", "fa", "ar", "tr", "ru", "de", "fr", "es"]


class GenerateRequest(BaseModel):
    topic: str
    content_type: str = "educational"
    language: str = "en"


class GenerateMultilingualRequest(BaseModel):
    topic: str
    content_type: str = "educational"
    languages: list[str] = ["en"]


class CreatePostRequest(BaseModel):
    account_id: uuid.UUID
    content: str
    content_type: str = "announcement"
    languages: dict = {}
    channel_ids: list[str] = []
    image_url: Optional[str] = None
    scheduled_at: Optional[datetime] = None


class GenerateDesktopImageRequest(BaseModel):
    topic: str = "Windows VPS desktop preview"
    save: bool = True


@router.post("/generate")
async def generate(_: APIKeyDep, body: GenerateRequest):
    if body.content_type not in SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported content_type. Use: {SUPPORTED_TYPES}")
    if body.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Unsupported language. Use: {SUPPORTED_LANGUAGES}")
    content = await generate_post(body.content_type, body.topic, body.language)
    return {"content": content, "language": body.language, "content_type": body.content_type}
from app.api.deps import DBSession, APIKeyDep
from app.services.content.generator import generate_post, generate_multilingual_post
from app.models.post import Post
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid

router = APIRouter(prefix="/content", tags=["content"])

SUPPORTED_TYPES = [
    "educational", "marketing", "technical", "announcement",
    "viral_giveaway", "viral_free_resource", "viral_tip_secret",
    "viral_poll_engagement", "viral_news_hook",
]
SUPPORTED_LANGUAGES = ["en", "fa", "ar", "tr", "ru", "de", "fr", "es"]


class GenerateRequest(BaseModel):
    topic: str
    content_type: str = "educational"
    language: str = "en"


class GenerateMultilingualRequest(BaseModel):
    topic: str
    content_type: str = "educational"
    languages: list[str] = ["en"]


class CreatePostRequest(BaseModel):
    account_id: uuid.UUID
    content: str
    content_type: str = "announcement"
    languages: dict = {}
    channel_ids: list[str] = []
    image_url: Optional[str] = None
    scheduled_at: Optional[datetime] = None


@router.post("/generate")
async def generate(_: APIKeyDep, body: GenerateRequest):
    if body.content_type not in SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported content_type. Use: {SUPPORTED_TYPES}")
    if body.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Unsupported language. Use: {SUPPORTED_LANGUAGES}")
    content = await generate_post(body.content_type, body.topic, body.language)
    return {"content": content, "language": body.language, "content_type": body.content_type}


@router.post("/generate-multilingual")
async def generate_multilingual(_: APIKeyDep, body: GenerateMultilingualRequest):
    languages = [l for l in body.languages if l in SUPPORTED_LANGUAGES]
    if not languages:
        raise HTTPException(status_code=400, detail="No valid languages provided")
    contents = await generate_multilingual_post(body.content_type, body.topic, languages)
    return {"contents": contents, "topic": body.topic}


@router.post("/generate-desktop-image")
async def generate_desktop_image_endpoint(_: APIKeyDep, body: GenerateDesktopImageRequest):
    try:
        image_path = await generate_desktop_image(body.topic)
    except DesktopImageGenerationError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    from pathlib import Path

    return {
        "filename": Path(image_path).name,
        "path": image_path,
        "source": "pillow-local-assets",
        "renderer": "Pillow",
        "telegram_ready": True,
    }


@router.post("/posts")
async def create_post(_: APIKeyDep, session: DBSession, body: CreatePostRequest):
    post = Post(
        account_id=body.account_id,
        content=body.content,
        content_type=body.content_type,
        languages=body.languages,
        channel_ids=body.channel_ids,
        image_url=body.image_url,
        status="scheduled" if body.scheduled_at else "draft",
        scheduled_at=body.scheduled_at,
    )
    session.add(post)
    await session.commit()
    await session.refresh(post)
    return {"id": str(post.id), "status": post.status}


@router.post("/posts/{post_id}/publish")
async def publish_now(_: APIKeyDep, session: DBSession, post_id: uuid.UUID):
    from sqlalchemy import select
    from app.services.channel.publisher import publish_post
    result = await session.execute(select(Post).where(Post.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    post.status = "publishing"
    results = await publish_post(session, post)
    await session.commit()
    return {"results": results}
