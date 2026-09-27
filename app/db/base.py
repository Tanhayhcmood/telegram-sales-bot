import ssl
from sqlalchemy.ext.asyncio import create_async_engine, AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import DateTime, func
from datetime import datetime
from app.core.config import settings

_use_ssl = settings.DATABASE_SSL or settings.APP_ENV == "production"


def _make_ssl_ctx() -> ssl.SSLContext:
    """SSL context that accepts Render's self-signed internal certs."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# asyncpg connect_args:
#   timeout=5  — fail fast (default is 60s which blocks lifespan startup)
#   ssl        — no-verify SSL context for Render internal PostgreSQL
_connect_args: dict = {"timeout": 5}
if _use_ssl:
    _connect_args["ssl"] = _make_ssl_ctx()

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_timeout=10,
    echo=settings.DEBUG,
    connect_args=_connect_args,
)


class Base(AsyncAttrs, DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
