"""add challenges and participants

Revision ID: f5c8e9a0b1d2
Revises: e4f1a2b3c9d0
Create Date: 2026-08-01 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f5c8e9a0b1d2"
down_revision: Union[str, None] = "e4f1a2b3c9d0"
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
    if not _table_exists("challenges"):
        op.create_table(
            "challenges",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("slug", sa.String(length=80), nullable=False),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("topic", sa.String(length=500), nullable=False),
            sa.Column("announcement", sa.Text(), nullable=False),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("correct_answer", sa.Integer(), nullable=False),
            sa.Column("hashtags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("seo_keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("reward", sa.String(length=500), nullable=False),
            sa.Column("channel_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("language", sa.String(length=5), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("winner_count", sa.Integer(), nullable=False),
            sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )
    if not _index_exists("challenges", "ix_challenges_slug"):
        op.create_index("ix_challenges_slug", "challenges", ["slug"], unique=False)
    if not _index_exists("challenges", "ix_challenges_status"):
        op.create_index("ix_challenges_status", "challenges", ["status"], unique=False)

    if not _table_exists("challenge_participants"):
        op.create_table(
            "challenge_participants",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("challenge_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("telegram_id", sa.BigInteger(), nullable=False),
            sa.Column("username", sa.String(length=255), nullable=True),
            sa.Column("display_name", sa.String(length=255), nullable=True),
            sa.Column("points", sa.Integer(), nullable=False),
            sa.Column("answer_submitted", sa.Boolean(), nullable=False),
            sa.Column("answer_correct", sa.Boolean(), nullable=False),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("challenge_id", "telegram_id", name="uq_challenge_participant_user"),
        )
    if not _index_exists("challenge_participants", "ix_challenge_participants_challenge_id"):
        op.create_index("ix_challenge_participants_challenge_id", "challenge_participants", ["challenge_id"], unique=False)
    if not _index_exists("challenge_participants", "ix_challenge_participants_telegram_id"):
        op.create_index("ix_challenge_participants_telegram_id", "challenge_participants", ["telegram_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_challenge_participants_telegram_id", table_name="challenge_participants")
    op.drop_index("ix_challenge_participants_challenge_id", table_name="challenge_participants")
    op.drop_table("challenge_participants")
    op.drop_index("ix_challenges_status", table_name="challenges")
    op.drop_index("ix_challenges_slug", table_name="challenges")
    op.drop_table("challenges")