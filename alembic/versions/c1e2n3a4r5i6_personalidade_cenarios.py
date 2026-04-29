"""personalidade_ia: coluna cenarios JSONB (lista de [cenario, acao])

Revision ID: c1e2n3a4r5i6
Revises: p1r2i3o4r5i6
Create Date: 2026-04-29
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'c1e2n3a4r5i6'
down_revision: Union[str, Sequence[str], None] = 'p1r2i3o4r5i6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE personalidade_ia
        ADD COLUMN IF NOT EXISTS cenarios JSONB DEFAULT '[]'::jsonb
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE personalidade_ia DROP COLUMN IF EXISTS cenarios")
