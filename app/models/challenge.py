import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Challenge(Base, TimestampMixin):
    __tablename__ = "challenges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    announcement: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    learning_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    answers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    correct_answer: Mapped[int] = mapped_column(Integer, nullable=False)
    hashtags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    seo_keywords: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    reward: Mapped[str] = mapped_column(String(500), nullable=False)
    channel_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    language: Mapped[str] = mapped_column(String(5), nullable=False, default="en")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    winner_count: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    participants = relationship("ChallengeParticipant", back_populates="challenge", lazy="select")


class ChallengeParticipant(Base, TimestampMixin):
    __tablename__ = "challenge_participants"
    __table_args__ = (
        UniqueConstraint("challenge_id", "telegram_id", name="uq_challenge_participant_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False, index=True
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    answer_submitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    answer_correct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    public_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public_users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    challenge = relationship("Challenge", back_populates="participants")