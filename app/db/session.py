from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.db.base import engine
from typing import AsyncGenerator

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Load model metadata without creating tables.

    Production schema changes are owned by Alembic and are applied by the
    startup script before background services begin.  Calling
    ``Base.metadata.create_all`` here races with Alembic and can leave the
    database with all tables present but no migration history.
    """
    from app.models import (  # noqa: F401
        account, customer, conversation, lead, channel, post, knowledge, alert, admin, challenge, public_user
    )
