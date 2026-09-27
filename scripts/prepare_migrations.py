"""Safely reconcile databases created by the pre-Alembic startup path.

Older releases called ``Base.metadata.create_all`` while the service booted.
That could create a complete schema before Alembic had a chance to create its
version table.  This helper stamps only that specific, verifiable state.
Fresh and partial databases are left untouched so normal Alembic migrations
can create or upgrade them.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys

from sqlalchemy import inspect

from app.db.base import Base, engine
from app.models import (  # noqa: F401
    account,
    admin,
    alert,
    challenge,
    channel,
    conversation,
    customer,
    knowledge,
    lead,
    post,
    proxy,
    public_user,
)


def _inspect_complete_legacy_schema(sync_connection) -> bool:
    """Run all reflection calls on the synchronous connection greenlet."""
    inspector = inspect(sync_connection)
    tables = set(inspector.get_table_names())

    if "alembic_version" in tables:
        return False

    expected_tables = set(Base.metadata.tables)
    if not expected_tables or not expected_tables.issubset(tables):
        return False

    for table_name, table in Base.metadata.tables.items():
        actual_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        expected_columns = {column.name for column in table.columns}
        if not expected_columns.issubset(actual_columns):
            return False

    return True


async def _is_complete_legacy_schema() -> bool:
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_inspect_complete_legacy_schema)
    finally:
        # Dispose in the same event loop that created the asyncpg connection.
        await engine.dispose()


def main() -> int:
    legacy_schema = asyncio.run(_is_complete_legacy_schema())

    if not legacy_schema:
        print("[migrations] Fresh or versioned schema; normal Alembic flow applies.")
        return 0

    print(
        "[migrations] Complete legacy create_all schema detected without "
        "alembic_version; stamping current head."
    )
    try:
        clean_env = os.environ.copy()
        clean_env.pop("PYTHONPATH", None)
        subprocess.run(["alembic", "stamp", "head"], check=True, env=clean_env)
    except subprocess.CalledProcessError as exc:
        print(f"[migrations] Alembic stamp failed with exit code {exc.returncode}.", file=sys.stderr)
        return exc.returncode or 1
    # Tell start.sh that the schema is already at head. Running upgrade again
    # in this same startup can race with the stamp connection on Render.
    return 10


if __name__ == "__main__":
    raise SystemExit(main())