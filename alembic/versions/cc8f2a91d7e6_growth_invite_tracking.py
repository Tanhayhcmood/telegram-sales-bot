"""Add Growth Challenge invite, membership, and channel status tables.

Revision ID: cc8f2a91d7e6
Revises: d9e8f7a6b5c4, f5c8e9a0b1d2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "cc8f2a91d7e6"
down_revision: Union[str, Sequence[str], None] = ("d9e8f7a6b5c4", "f5c8e9a0b1d2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(table_name) and column_name in {
        item["name"] for item in inspector.get_columns(table_name)
    }


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(table_name) and index_name in {
        item.get("name") for item in inspector.get_indexes(table_name)
    }

def upgrade() -> None:
    if not _column_exists("growth_rounds", "challenge_angle"):
        op.add_column(
            "growth_rounds",
            sa.Column("challenge_angle", sa.String(length=180), nullable=False, server_default=""),
        )
    op.alter_column("growth_rounds", "challenge_angle", server_default=None)

    if not _table_exists("growth_channel_status"):
        op.create_table(
            "growth_channel_status",
            sa.Column("channel_id", sa.String(length=255), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("last_status", sa.String(length=24), nullable=True),
            sa.Column("last_step", sa.String(length=24), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("last_publish_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("channel_id"),
        )
    if not _table_exists("growth_invites"):
        op.create_table(
            "growth_invites",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("round_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("inviter_user_id", sa.BigInteger(), nullable=False),
            sa.Column("channel_id", sa.String(length=255), nullable=False),
            sa.Column("invite_link", sa.String(length=512), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["round_id"], ["growth_rounds.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("invite_link", name="uq_growth_invite_link"),
            sa.UniqueConstraint("round_id", "inviter_user_id", name="uq_growth_invite_round_inviter"),
        )
    if not _index_exists("growth_invites", "ix_growth_invite_round_inviter"):
        op.create_index("ix_growth_invite_round_inviter", "growth_invites", ["round_id", "inviter_user_id"])
    if not _table_exists("growth_joins"):
        op.create_table(
            "growth_joins",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("round_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("invite_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("inviter_user_id", sa.BigInteger(), nullable=False),
            sa.Column("invitee_user_id", sa.BigInteger(), nullable=False),
            sa.Column("channel_id", sa.String(length=255), nullable=False),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("suspicious", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["invite_id"], ["growth_invites.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["round_id"], ["growth_rounds.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("round_id", "invitee_user_id", name="uq_growth_join_round_invitee"),
        )
    if not _index_exists("growth_joins", "ix_growth_join_round_inviter"):
        op.create_index("ix_growth_join_round_inviter", "growth_joins", ["round_id", "inviter_user_id"])
    if not _index_exists("growth_joins", "ix_growth_join_round_joined"):
        op.create_index("ix_growth_join_round_joined", "growth_joins", ["round_id", "joined_at"])


def downgrade() -> None:
    op.drop_index("ix_growth_join_round_joined", table_name="growth_joins")
    op.drop_index("ix_growth_join_round_inviter", table_name="growth_joins")
    op.drop_table("growth_joins")
    op.drop_index("ix_growth_invite_round_inviter", table_name="growth_invites")
    op.drop_table("growth_invites")
    op.drop_table("growth_channel_status")
    op.drop_column("growth_rounds", "challenge_angle")
