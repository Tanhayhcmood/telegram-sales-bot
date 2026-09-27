import uuid
from sqlalchemy import String, Boolean, BigInteger, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin
from datetime import datetime
from sqlalchemy import DateTime


class TelegramAccount(Base, TimestampMixin):
    __tablename__ = "telegram_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    session_string: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    conversations = relationship("Conversation", back_populates="account", lazy="select")
    leads = relationship("Lead", back_populates="account", lazy="select")
    channels = relationship("TelegramChannel", back_populates="account", lazy="select")
    posts = relationship("Post", back_populates="account", lazy="select")
