import asyncio
import ssl
from logging.config import fileConfig
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
from app.core.config import settings
from app.db.base import Base
from app.models import (  # noqa: F401
    account,
    customer,
    conversation,
    lead,
    channel,
    post,
    knowledge,
    alert,
    admin,
    proxy,
    challenge,
    public_user,
)

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_use_ssl = settings.DATABASE_SSL or settings.APP_ENV == "production"


def _make_ssl_ctx() -> ssl.SSLContext:
    """SSL context that accepts Render internal self-signed certs."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    # Increased from 5s to 30s: on Render free tier, rolling deploys can briefly
    # saturate the DB connection pool. 30s gives enough headroom to wait for a
    # connection slot without the start.sh retry loop burning through attempts too fast.
    connect_args: dict = {"timeout": 30}
    if _use_ssl:
        connect_args["ssl"] = _make_ssl_ctx()
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )
    async with connectable.connect() as connection:
        # Render can briefly run old and new instances together.  Serialize
        # migration and stamp operations so both instances cannot create the
        # same table at the same time.
        await connection.execute(text("SELECT pg_advisory_lock(hashtext('telegram_sales_bot_alembic'))"))
        # The advisory-lock SELECT starts an implicit SQLAlchemy transaction.
        # Commit it before handing the connection to Alembic; otherwise
        # Alembic's transaction becomes nested in the lock transaction and the
        # cleanup rollback silently undoes every successful migration.
        await connection.commit()
        try:
            await connection.run_sync(do_run_migrations)
        except Exception:
            # A failed DDL statement aborts the PostgreSQL transaction. Reset
            # it before releasing the session-level advisory lock.
            await connection.rollback()
            raise
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(hashtext('telegram_sales_bot_alembic'))"))
            await connection.commit()
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
