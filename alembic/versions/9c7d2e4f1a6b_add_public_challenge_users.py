"""add public challenge users, referrals, and participant links

Revision ID: 9c7d2e4f1a6b
Revises: f5c8e9a0b1d2
Create Date: 2026-08-02 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "9c7d2e4f1a6b"
down_revision: Union[str, None] = "f5c8e9a0b1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "public_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("referral_code", sa.String(length=20), nullable=False),
        sa.Column("referred_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("total_points", sa.Integer(), nullable=False),
        sa.Column("challenge_count", sa.Integer(), nullable=False),
        sa.Column("correct_answers", sa.Integer(), nullable=False),
        sa.Column("referral_count", sa.Integer(), nullable=False),
        sa.Column("referral_points", sa.Integer(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["referred_by_id"], ["public_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_id"),
        sa.UniqueConstraint("referral_code"),
    )
    op.create_index("ix_public_users_telegram_id", "public_users", ["telegram_id"], unique=False)
    op.create_index("ix_public_users_referral_code", "public_users", ["referral_code"], unique=False)
    op.create_index("ix_public_users_referred_by_id", "public_users", ["referred_by_id"], unique=False)

    op.add_column(
        "challenge_participants",
        sa.Column("public_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_challenge_participants_public_user_id",
        "challenge_participants",
        "public_users",
        ["public_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_challenge_participants_public_user_id",
        "challenge_participants",
        ["public_user_id"],
        unique=False,
    )
    op.add_column("challenges", sa.Column("learning_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_index("ix_challenge_participants_public_user_id", table_name="challenge_participants")
    op.drop_constraint(
        "fk_challenge_participants_public_user_id",
        "challenge_participants",
        type_="foreignkey",
    )
    op.drop_column("challenge_participants", "public_user_id")
    op.drop_index("ix_public_users_referred_by_id", table_name="public_users")
    op.drop_index("ix_public_users_referral_code", table_name="public_users")
    op.drop_index("ix_public_users_telegram_id", table_name="public_users")
    op.drop_table("public_users")
    op.drop_column("challenges", "learning_note")