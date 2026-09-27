import uuid
from sqlalchemy import String, Boolean, BigInteger, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin


class TelegramChannel(Base, TimestampMixin):
    __tablename__ = "channels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # nullable=True — channels added manually for force-subscription do not need
    # a userbot account.  The posting pipeline skips channels where account is None.
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telegram_accounts.id"), nullable=True
    )

    telegram_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language: Mapped[str] = mapped_column(String(5), default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    post_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    # Each channel gets its own proxy for IP diversity
    proxy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proxies.id", ondelete="SET NULL"), nullable=True
    )

    # account is None for manually-added force-sub channels
    account = relationship(
        "TelegramAccount",
        back_populates="channels",
        foreign_keys=[account_id],
    )
    proxy = relationship("Proxy", back_populates="channels", lazy="select")
