"""Use manual delivery for Growth Challenge winners.

Revision ID: d9e8f7a6b5c4
Revises: 4a3b2c1d9e8f
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d9e8f7a6b5c4"
down_revision: Union[str, None] = "4a3b2c1d9e8f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    for foreign_key in sa.inspect(bind).get_foreign_keys("growth_winners"):
        if foreign_key.get("constrained_columns") == ["prize_id"] and foreign_key.get("name"):
            op.drop_constraint(
                foreign_key["name"],
                "growth_winners",
                type_="foreignkey",
            )

    prize_column = next(
        column
        for column in sa.inspect(bind).get_columns("growth_winners")
        if column["name"] == "prize_id"
    )
    if not prize_column["nullable"]:
        op.alter_column(
            "growth_winners",
            "prize_id",
            existing_type=postgresql.UUID(as_uuid=True),
            existing_nullable=False,
            nullable=True,
        )
    op.execute(
        "UPDATE growth_winners "
        "SET delivery_status = 'pending_delivery' "
        "WHERE delivery_status IS DISTINCT FROM 'delivered'"
    )
    op.alter_column(
        "growth_winners",
        "delivery_status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        server_default=sa.text("'pending_delivery'"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    null_prizes = bind.execute(
        sa.text("SELECT count(*) FROM growth_winners WHERE prize_id IS NULL")
    ).scalar_one()
    if null_prizes:
        raise RuntimeError(
            "Cannot restore prize-backed delivery while manual-delivery winners have no prize_id."
        )

    op.execute(
        "UPDATE growth_winners "
        "SET delivery_status = 'pending' "
        "WHERE delivery_status = 'pending_delivery'"
    )
    op.alter_column(
        "growth_winners",
        "delivery_status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        server_default=sa.text("'pending'"),
    )
    op.alter_column(
        "growth_winners",
        "prize_id",
        existing_type=postgresql.UUID(as_uuid=True),
        existing_nullable=True,
        nullable=False,
    )
    op.create_foreign_key(
        None,
        "growth_winners",
        "growth_prizes",
        ["prize_id"],
        ["id"],
    )
