from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from app.api.deps import DBSession, APIKeyDep
from app.models.knowledge import KnowledgeArticle
from pydantic import BaseModel
from typing import Optional
import uuid

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class ArticleIn(BaseModel):
    title: str
    content: str
    category: str = "general"
    language: str = "en"
    tags: list[str] = []


class ArticleOut(BaseModel):
    id: uuid.UUID
    title: str
    content: str
    category: str
    language: str
    tags: list
    is_active: bool
    model_config = {"from_attributes": True}


@router.get("", response_model=list[ArticleOut])
async def list_articles(
    _: APIKeyDep,
    session: DBSession,
    category: Optional[str] = None,
    language: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, le=100),
):
    q = select(KnowledgeArticle).where(KnowledgeArticle.is_active == True)
    if category:
        q = q.where(KnowledgeArticle.category == category)
    if language:
        q = q.where(KnowledgeArticle.language == language)
    result = await session.execute(q.offset(skip).limit(limit))
    return result.scalars().all()


@router.post("", response_model=ArticleOut)
async def create_article(_: APIKeyDep, session: DBSession, body: ArticleIn):
    article = KnowledgeArticle(**body.model_dump())
    session.add(article)
    await session.commit()
    await session.refresh(article)
    return article


@router.delete("/{article_id}")
async def deactivate_article(_: APIKeyDep, session: DBSession, article_id: uuid.UUID):
    result = await session.execute(select(KnowledgeArticle).where(KnowledgeArticle.id == article_id))
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    article.is_active = False
    await session.commit()
    return {"status": "deactivated"}
