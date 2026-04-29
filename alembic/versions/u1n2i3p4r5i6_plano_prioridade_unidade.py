"""plano_prioridade_unidade: override de prioridade por unidade

Revision ID: u1n2i3p4r5i6
Revises: c1e2n3a4r5i6
Create Date: 2026-04-29
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'u1n2i3p4r5i6'
down_revision: Union[str, Sequence[str], None] = 'c1e2n3a4r5i6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS plano_prioridade_unidade (
            id           SERIAL PRIMARY KEY,
            empresa_id   INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            plano_id     INTEGER NOT NULL REFERENCES planos(id) ON DELETE CASCADE,
            unidade_id   INTEGER NOT NULL REFERENCES unidades(id) ON DELETE CASCADE,
            prioridade   INTEGER NOT NULL DEFAULT 5,
            motivo       TEXT,
            created_at   TIMESTAMP DEFAULT NOW(),
            updated_at   TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_plano_prio_unidade
        ON plano_prioridade_unidade (plano_id, unidade_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_plano_prio_empresa
        ON plano_prioridade_unidade (empresa_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS plano_prioridade_unidade")
