"""add_usar_emoji_to_personalidade_ia

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-03-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE personalidade_ia
            ADD COLUMN IF NOT EXISTS usar_emoji BOOLEAN NOT NULL DEFAULT TRUE
    """)


def downgrade() -> None:
    op.drop_column('personalidade_ia', 'usar_emoji')
