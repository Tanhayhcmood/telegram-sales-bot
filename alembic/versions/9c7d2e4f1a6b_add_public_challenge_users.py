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


def _foreign_key_exists(table_name: str, foreign_key_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return False
    return any(
        item.get("name") == foreign_key_name
        or (
            item.get("constrained_columns") == ["public_user_id"]
            and item.get("referred_table") == "public_users"
        )
        for item in inspector.get_foreign_keys(table_name)
    )

def upgrade() -> None:
    if not _table_exists("public_users"):
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
    if not _index_exists("public_users", "ix_public_users_telegram_id"):
        op.create_index("ix_public_users_telegram_id", "public_users", ["telegram_id"], unique=False)
    if not _index_exists("public_users", "ix_public_users_referral_code"):
        op.create_index("ix_public_users_referral_code", "public_users", ["referral_code"], unique=False)
    if not _index_exists("public_users", "ix_public_users_referred_by_id"):
        op.create_index("ix_public_users_referred_by_id", "public_users", ["referred_by_id"], unique=False)

    if not _column_exists("challenge_participants", "public_user_id"):
        op.add_column(
            "challenge_participants",
            sa.Column("public_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    if not _foreign_key_exists("challenge_participants", "fk_challenge_participants_public_user_id"):
        op.create_foreign_key(
            "fk_challenge_participants_public_user_id",
            "challenge_participants",
            "public_users",
            ["public_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if not _index_exists("challenge_participants", "ix_challenge_participants_public_user_id"):
        op.create_index(
            "ix_challenge_participants_public_user_id",
            "challenge_participants",
            ["public_user_id"],
            unique=False,
        )
    if not _column_exists("challenges", "learning_note"):
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