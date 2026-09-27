"""add proxy per channel

Revision ID: e4f1a2b3c9d0
Revises: b7e3f1a2d9c8
Create Date: 2026-07-30 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e4f1a2b3c9d0'
down_revision: Union[str, None] = 'b7e3f1a2d9c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'proxies',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('proxy_type', sa.String(length=10), nullable=False, server_default='socks5'),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('password', sa.String(length=255), nullable=True),
        sa.Column('label', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_alive', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_proxies_is_active', 'proxies', ['is_active'], unique=False)

    op.add_column(
        'channels',
        sa.Column('proxy_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_channels_proxy_id',
        'channels', 'proxies',
        ['proxy_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_channels_proxy_id', 'channels', type_='foreignkey')
    op.drop_column('channels', 'proxy_id')
    op.drop_index('ix_proxies_is_active', table_name='proxies')
    op.drop_table('proxies')
