"""add_image_url_to_posts

Revision ID: b7e3f1a2d9c8
Revises: 3bbc4389aba7
Create Date: 2026-06-12 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b7e3f1a2d9c8'
down_revision: Union[str, None] = '3bbc4389aba7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('posts', sa.Column('image_url', sa.String(length=2000), nullable=True))


def downgrade() -> None:
    op.drop_column('posts', 'image_url')
