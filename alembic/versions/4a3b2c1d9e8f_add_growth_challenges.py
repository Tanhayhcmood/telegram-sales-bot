"""Add isolated Growth Challenge tables.

Revision ID: 4a3b2c1d9e8f
Revises: 8a6b7c8d9e0f
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "4a3b2c1d9e8f"
down_revision: Union[str, None] = "8a6b7c8d9e0f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(table_name) and index_name in {
        item.get("name") for item in inspector.get_indexes(table_name)
    }

def upgrade() -> None:
    # Existing deployments may already have some or all Growth relations.

    if not _table_exists("growth_rounds"):
        op.create_table(
            "growth_rounds",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("challenge_type", sa.String(length=40), nullable=False),
            sa.Column("challenge_text", sa.Text(), nullable=False),
            sa.Column("challenge_hash", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("channel_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("prize_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("published_messages", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("entries_close_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("review_ends_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("next_round_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("final_outcome", sa.String(length=20), nullable=True),
            sa.Column("announcement_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("challenge_hash", name="uq_growth_round_challenge_hash"),
        )
    if not _index_exists("growth_rounds", "uq_growth_one_active_round"):
        op.create_index("uq_growth_one_active_round", "growth_rounds", ["is_active"], unique=True, postgresql_where=sa.text("is_active IS TRUE"))
    if not _index_exists("growth_rounds", "ix_growth_round_next_round_at"):
        op.create_index("ix_growth_round_next_round_at", "growth_rounds", ["next_round_at"], unique=False)

    if not _table_exists("growth_entries"):
        op.create_table(
            "growth_entries",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("round_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
            sa.Column("username", sa.String(length=255), nullable=True),
            sa.Column("proof_type", sa.String(length=24), nullable=False),
            sa.Column("proof_hash", sa.String(length=64), nullable=False),
            sa.Column("proof_file_id", sa.String(length=512), nullable=True),
            sa.Column("source_user_id", sa.BigInteger(), nullable=False),
            sa.Column("source_chat_id", sa.BigInteger(), nullable=False),
            sa.Column("source_message_id", sa.BigInteger(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("admin_notifications", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["round_id"], ["growth_rounds.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("proof_hash", name="uq_growth_entry_proof_hash"),
            sa.UniqueConstraint("source_user_id", "source_chat_id", "source_message_id", name="uq_growth_entry_source_message"),
        )
    if not _index_exists("growth_entries", "ix_growth_entry_round_status"):
        op.create_index("ix_growth_entry_round_status", "growth_entries", ["round_id", "status"], unique=False)
    if not _index_exists("growth_entries", "ix_growth_entry_user_round"):
        op.create_index("ix_growth_entry_user_round", "growth_entries", ["telegram_user_id", "round_id"], unique=False)

    if not _table_exists("growth_prizes"):
        op.create_table(
            "growth_prizes",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("kind", sa.String(length=8), nullable=False),
            sa.Column("encrypted_payload", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="available"),
            sa.Column("reserved_round_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["reserved_round_id"], ["growth_rounds.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists("growth_prizes", "ix_growth_prize_status"):
        op.create_index("ix_growth_prize_status", "growth_prizes", ["status"], unique=False)

    if not _table_exists("growth_winners"):
        op.create_table(
            "growth_winners",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("round_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("prize_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
            sa.Column("username", sa.String(length=255), nullable=True),
            sa.Column("delivery_status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("delivery_log", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["round_id"], ["growth_rounds.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["prize_id"], ["growth_prizes.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("round_id", "telegram_user_id", name="uq_growth_winner_round_user"),
        )
    if not _index_exists("growth_winners", "ix_growth_winner_user_selected"):
        op.create_index("ix_growth_winner_user_selected", "growth_winners", ["telegram_user_id", "selected_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_growth_winner_user_selected", table_name="growth_winners")
    op.drop_table("growth_winners")
    op.drop_index("ix_growth_prize_status", table_name="growth_prizes")
    op.drop_table("growth_prizes")
    op.drop_index("ix_growth_entry_user_round", table_name="growth_entries")
    op.drop_index("ix_growth_entry_round_status", table_name="growth_entries")
    op.drop_table("growth_entries")
    op.drop_index("ix_growth_round_next_round_at", table_name="growth_rounds")
    op.drop_index("uq_growth_one_active_round", table_name="growth_rounds")
    op.drop_table("growth_rounds")
