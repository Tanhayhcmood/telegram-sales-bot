"""enforce mandatory subscriptions for existing active channels

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-08-02 16:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Channel discovery can predate the require_join flag or an administrator
    # can have disabled it accidentally. Existing active publishing channels
    # are the authoritative subscription list for this public bot.
    op.execute(
        sa.text(
            "UPDATE channels SET require_join = TRUE "
            "WHERE is_active = TRUE AND require_join IS DISTINCT FROM TRUE"
        )
    )


def downgrade() -> None:
    # Do not silently disable subscriptions during a rollback. The previous
    # migration's server default remains the safe behavior for new rows.
    pass