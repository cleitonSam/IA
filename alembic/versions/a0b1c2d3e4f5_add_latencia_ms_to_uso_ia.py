"""add latencia_ms to uso_ia

Revision ID: a0b1c2d3e4f5
Revises: z9a0b1c2d3e4
Create Date: 2026-03-30

Adiciona coluna latencia_ms (INTEGER) à tabela uso_ia para armazenar
a latência real da chamada ao LLM em milissegundos.
Exibida no painel "Performance IA" do dashboard.
"""
from alembic import op

# revision identifiers
revision = "a0b1c2d3e4f5"
down_revision = "z9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE uso_ia ADD COLUMN IF NOT EXISTS latencia_ms INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE uso_ia DROP COLUMN IF EXISTS latencia_ms")
