"""planos: campo prioridade (0-10) + motivo_prioridade

Revision ID: p1r2i3o4r5i6
Revises: v1c2h3e4r5
Create Date: 2026-04-29
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'p1r2i3o4r5i6'
down_revision: Union[str, Sequence[str], None] = 'v1c2h3e4r5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE planos
        ADD COLUMN IF NOT EXISTS prioridade INTEGER DEFAULT 5
    """)
    op.execute("""
        ALTER TABLE planos
        ADD COLUMN IF NOT EXISTS motivo_prioridade TEXT
    """)
    # Index pra ordenacao rapida (prioridade DESC)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_planos_prioridade
        ON planos (empresa_id, prioridade DESC, ordem ASC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_planos_prioridade")
    op.execute("ALTER TABLE planos DROP COLUMN IF EXISTS motivo_prioridade")
    op.execute("ALTER TABLE planos DROP COLUMN IF EXISTS prioridade")
