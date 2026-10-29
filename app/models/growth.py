import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class GrowthRound(Base, TimestampMixin):
    __tablename__ = "growth_rounds"
    __table_args__ = (
        UniqueConstraint("challenge_hash", name="uq_growth_round_challenge_hash"),
        Index(
            "uq_growth_one_active_round",
            "is_active",
            unique=True,
            postgresql_where=text("is_active IS TRUE"),
        ),
        Index("ix_growth_round_next_round_at", "next_round_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    challenge_type: Mapped[str] = mapped_column(String(40), nullable=False)
    challenge_text: Mapped[str] = mapped_column(Text, nullable=False)
    challenge_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    challenge_angle: Mapped[str] = mapped_column(String(180), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    channel_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    published_messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entries_close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_round_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    announcement_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class GrowthEntry(Base, TimestampMixin):
    __tablename__ = "growth_entries"
    __table_args__ = (
        UniqueConstraint("proof_hash", name="uq_growth_entry_proof_hash"),
        UniqueConstraint(
            "source_user_id",
            "source_chat_id",
            "source_message_id",
            name="uq_growth_entry_source_message",
        ),
        Index("ix_growth_entry_round_status", "round_id", "status"),
        Index("ix_growth_entry_user_round", "telegram_user_id", "round_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("growth_rounds.id", ondelete="CASCADE"), nullable=False
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    proof_type: Mapped[str] = mapped_column(String(24), nullable=False)
    proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    proof_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    admin_notifications: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


class GrowthPrize(Base, TimestampMixin):
    # Legacy table retained intact; the runtime no longer stores or allocates prizes.
    __tablename__ = "growth_prizes"
    __table_args__ = (Index("ix_growth_prize_status", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="available")
    reserved_round_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("growth_rounds.id", ondelete="SET NULL"), nullable=True
    )
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GrowthWinner(Base, TimestampMixin):
    __tablename__ = "growth_winners"
    __table_args__ = (
        UniqueConstraint("round_id", "telegram_user_id", name="uq_growth_winner_round_user"),
        Index("ix_growth_winner_user_selected", "telegram_user_id", "selected_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("growth_rounds.id", ondelete="CASCADE"), nullable=False
    )
    # Nullable for newly selected winners; historical prize links are preserved.
    prize_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending_delivery"
    )
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GrowthChannelStatus(Base, TimestampMixin):
    __tablename__ = "growth_channel_status"

    channel_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_step: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GrowthInvite(Base, TimestampMixin):
    __tablename__ = "growth_invites"
    __table_args__ = (
        UniqueConstraint("round_id", "inviter_user_id", name="uq_growth_invite_round_inviter"),
        UniqueConstraint("invite_link", name="uq_growth_invite_link"),
        Index("ix_growth_invite_round_inviter", "round_id", "inviter_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("growth_rounds.id", ondelete="CASCADE"), nullable=False
    )
    inviter_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[str] = mapped_column(String(255), nullable=False)
    invite_link: Mapped[str] = mapped_column(String(512), nullable=False)


class GrowthJoin(Base, TimestampMixin):
    __tablename__ = "growth_joins"
    __table_args__ = (
        UniqueConstraint("round_id", "invitee_user_id", name="uq_growth_join_round_invitee"),
        Index("ix_growth_join_round_inviter", "round_id", "inviter_user_id"),
        Index("ix_growth_join_round_joined", "round_id", "joined_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("growth_rounds.id", ondelete="CASCADE"), nullable=False
    )
    invite_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("growth_invites.id", ondelete="CASCADE"), nullable=False
    )
    inviter_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    invitee_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[str] = mapped_column(String(255), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspicious: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
