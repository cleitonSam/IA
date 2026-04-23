"""Adiciona coluna mensagem_fora_horario em personalidade_ia

[HORA-01] Bot ficava mudo quando fora do horario. Agora envia mensagem configurada.

Revision ID: hora01_fora_horario
Revises: mkt01_features
Create Date: 2026-04-23
"""
from alembic import op


revision = "hora01_fora_horario"
down_revision = "mkt01_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Mensagem enviada ao cliente quando a IA esta fora do horario.
    # Se ficar NULL ou vazio, o bot usa um default generico.
    op.execute("""
        ALTER TABLE personalidade_ia
        ADD COLUMN IF NOT EXISTS mensagem_fora_horario TEXT
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE personalidade_ia DROP COLUMN IF EXISTS mensagem_fora_horario")
