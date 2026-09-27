"""Repair databases that were incorrectly marked as fully migrated.

Some production databases have an ``alembic_version`` row at the current
head while model tables such as ``posts`` and ``challenges`` are absent.
Creating the missing tables from the checked-in SQLAlchemy metadata is
idempotent and avoids deleting any existing customer data.
"""

from alembic import op

from app.db.base import Base
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


revision = "8a6b7c8d9e0f"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # checkfirst=True creates only relations that are genuinely absent.  This
    # is intentionally a repair migration, so it never replaces or drops data.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Do not remove recovered production tables during a downgrade.
    pass