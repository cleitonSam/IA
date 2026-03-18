"""add_menu_triagem_to_personalidade_ia

Revision ID: c2d3e4f5g6h7
Revises: b3c4d5e6f7a8
Create Date: 2026-03-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c2d3e4f5g6h7'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE personalidade_ia
            ADD COLUMN IF NOT EXISTS menu_triagem JSONB
    """)


def downgrade() -> None:
    op.drop_column('personalidade_ia', 'menu_triagem')
