import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from app.api.deps import APIKeyDep, DBSession
from app.models.challenge import Challenge
from app.services.challenges.public_bot import get_public_bot_username
from app.services.challenges.service import challenge_summary, create_and_publish_challenge, leaderboard

router = APIRouter(prefix="/challenges", tags=["challenges"])


class CreateChallengeRequest(BaseModel):
    topic: str = Field(default="RDP security, VPS reliability, and server protection", min_length=2, max_length=500)
    language: str = Field(default="en", pattern="^en$")


@router.post("")
async def create_challenge(_: APIKeyDep, session: DBSession, body: CreateChallengeRequest):
    try:
        challenge, results = await create_and_publish_challenge(
            session,
            topic=body.topic,
            language="en",
            public_bot_username=get_public_bot_username(),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": str(challenge.id),
        "slug": challenge.slug,
        "title": challenge.title,
        "published": sum(1 for result in results.values() if result.get("status") == "published"),
        "attempted": len(results),
        "ends_at": challenge.ends_at,
    }


@router.get("/active")
async def active_challenge(_: APIKeyDep, session: DBSession):
    challenge = await session.scalar(
        select(Challenge)
        .where(Challenge.status == "active", Challenge.language == "en")
        .order_by(desc(Challenge.created_at))
        .limit(1)
    )
    if not challenge:
        raise HTTPException(status_code=404, detail="No active challenge")
    return await challenge_summary(session, challenge)


@router.get("/{challenge_id}/leaderboard")
async def challenge_leaderboard(_: APIKeyDep, session: DBSession, challenge_id: uuid.UUID):
    challenge = await session.scalar(select(Challenge).where(Challenge.id == challenge_id))
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    rows = await leaderboard(session, challenge.id)
    return [
        {
            "rank": index,
            "telegram_id": row.telegram_id,
            "username": row.username,
            "display_name": row.display_name,
            "points": row.points,
            "correct": row.answer_correct,
        }
        for index, row in enumerate(rows, 1)
    ]