"""mapeamento_label_time: configuracao por empresa de label -> team_id Chatwoot

Revision ID: a1b2c3d4e5f6
Revises: z9z9z9z9z9z9
Create Date: 2026-04-29
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'z9z9z9z9z9z9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS mapeamento_label_time (
            id          SERIAL PRIMARY KEY,
            empresa_id  INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            label       VARCHAR(120) NOT NULL,
            team_id     INTEGER NOT NULL,
            ativo       BOOLEAN DEFAULT true,
            created_at  TIMESTAMP DEFAULT NOW(),
            updated_at  TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_mapeamento_label_time_empresa_label
        ON mapeamento_label_time (empresa_id, lower(label))
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_mapeamento_label_time_empresa
        ON mapeamento_label_time (empresa_id)
    """)

    # Seed com mapping da Goodbe (empresa_id=3) — preserva config atual
    # Se empresa 3 nao existir, ON CONFLICT DO NOTHING evita erro
    op.execute("""
        INSERT INTO mapeamento_label_time (empresa_id, label, team_id, ativo)
        SELECT 3, label, team_id, true FROM (VALUES
            ('aluno-altino',     5),
            ('aluno-belenzinho', 10),
            ('aluno-campestre',  9),
            ('aluno-ipiranga',   8),
            ('aluno-jardins',    11),
            ('aluno-nações',     6),
            ('aluno-saude',      7)
        ) AS v(label, team_id)
        WHERE EXISTS (SELECT 1 FROM empresas WHERE id = 3)
        ON CONFLICT (empresa_id, lower(label)) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mapeamento_label_time")
