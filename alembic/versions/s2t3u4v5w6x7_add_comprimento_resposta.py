"""add comprimento_resposta to personalidade_ia

Revision ID: s2t3u4v5w6x7
Revises: r1s2t3u4v5w6
Create Date: 2026-03-29

Adiciona campo para controlar verbosidade das respostas da IA.
Valores: 'concisa' (2-3 frases), 'normal' (3-5 frases), 'detalhada' (sem limite).
"""
from typing import Sequence, Union
from alembic import op


revision: str = 's2t3u4v5w6x7'
down_revision: Union[str, Sequence[str], None] = 'r1s2t3u4v5w6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE personalidade_ia
        ADD COLUMN IF NOT EXISTS comprimento_resposta TEXT
        DEFAULT 'normal'
        CHECK (comprimento_resposta IN ('concisa', 'normal', 'detalhada'))
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE personalidade_ia DROP COLUMN IF EXISTS comprimento_resposta")
