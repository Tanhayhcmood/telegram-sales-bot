"""make channel account_id nullable for manually-added force-sub channels

Channels added by the admin through the force-subscription menu are not tied
to a userbot account (they are used only to gate public-bot access).  Making
account_id nullable lets the admin register such channels without first
running a userbot scan.

The posting pipeline already guards against NULL account_id (it only picks up
channels that are reachable via a connected userbot account), so this change
is safe and backward-compatible with all existing rows.

Revision ID: d1e2f3a4b5c6
Revises: c3d4e5f6a7b8
Create Date: 2026-08-02 20:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Allow account_id to be NULL so admin-added force-sub channels don't need
    # a userbot account.  The FK itself is preserved — NULL simply means "no
    # associated userbot".
    op.alter_column(
        "channels",
        "account_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    # Remove any manually-added rows (account_id IS NULL) before reverting,
    # otherwise the NOT NULL constraint cannot be restored.
    op.execute(sa.text("DELETE FROM channels WHERE account_id IS NULL"))
    op.alter_column(
        "channels",
        "account_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
