"""create uso_ia table

Revision ID: z9a0b1c2d3e4
Revises: y8z9a0b1c2d3
Create Date: 2026-03-30

Cria a tabela uso_ia para rastrear consumo de tokens e custo por chamada à IA.
Referenciada em dashboard.py (linhas 674, 1120, 1279, 1313) e main.py (linha 3473).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "z9a0b1c2d3e4"
down_revision = "y8z9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS uso_ia (
            id               SERIAL PRIMARY KEY,
            empresa_id       INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            unidade_id       INTEGER REFERENCES unidades(id) ON DELETE SET NULL,
            conversa_id      INTEGER REFERENCES conversas(id) ON DELETE SET NULL,
            modelo           VARCHAR(100),
            tokens_prompt    INTEGER NOT NULL DEFAULT 0,
            tokens_completion INTEGER NOT NULL DEFAULT 0,
            custo_usd        NUMERIC(10,6) NOT NULL DEFAULT 0,
            cache_hit        BOOLEAN NOT NULL DEFAULT false,
            fallback         BOOLEAN NOT NULL DEFAULT false,
            created_at       TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)

    # Garante que colunas adicionadas após a criação inicial existam
    # (caso a tabela tenha sido criada por um deploy anterior sem elas)
    op.execute("ALTER TABLE uso_ia ADD COLUMN IF NOT EXISTS modelo       VARCHAR(100)")
    op.execute("ALTER TABLE uso_ia ADD COLUMN IF NOT EXISTS unidade_id  INTEGER REFERENCES unidades(id)  ON DELETE SET NULL")
    op.execute("ALTER TABLE uso_ia ADD COLUMN IF NOT EXISTS conversa_id INTEGER REFERENCES conversas(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE uso_ia ADD COLUMN IF NOT EXISTS cache_hit   BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE uso_ia ADD COLUMN IF NOT EXISTS fallback     BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE uso_ia ADD COLUMN IF NOT EXISTS latencia_ms  INTEGER")

    # Índices para as queries de dashboard (filtragem por empresa + data)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_uso_ia_empresa_id
            ON uso_ia (empresa_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_uso_ia_empresa_created_at
            ON uso_ia (empresa_id, created_at)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_uso_ia_unidade_id
            ON uso_ia (unidade_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_uso_ia_conversa_id
            ON uso_ia (conversa_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS uso_ia CASCADE")
