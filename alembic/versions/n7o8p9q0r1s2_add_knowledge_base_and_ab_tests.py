"""add_knowledge_base_and_ab_tests

Revision ID: n7o8p9q0r1s2
Revises: 3cd6b04c5258
Create Date: 2026-03-28

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'n7o8p9q0r1s2'
down_revision: Union[str, Sequence[str], None] = '3cd6b04c5258'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Knowledge Base (RAG) ─────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id              SERIAL PRIMARY KEY,
            empresa_id      INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            titulo          VARCHAR(200) NOT NULL,
            conteudo        TEXT NOT NULL,
            categoria       VARCHAR(50) DEFAULT 'geral',
            embedding       JSONB,
            chunk_index     INTEGER DEFAULT 0,
            source_file     VARCHAR(255),
            ativo           BOOLEAN DEFAULT true,
            created_at      TIMESTAMP DEFAULT NOW(),
            updated_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_kb_empresa_cat
        ON knowledge_base (empresa_id, categoria)
        WHERE ativo = true
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_kb_empresa_ativo
        ON knowledge_base (empresa_id)
        WHERE ativo = true
    """)

    # ── A/B Tests ────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS ab_testes (
            id              SERIAL PRIMARY KEY,
            empresa_id      INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            nome            VARCHAR(200) NOT NULL,
            descricao       TEXT,
            campo_teste     VARCHAR(50) NOT NULL DEFAULT 'prompt_sistema',
            variante_a      TEXT NOT NULL,
            variante_b      TEXT NOT NULL,
            percentual_b    FLOAT DEFAULT 50.0,
            ativo           BOOLEAN DEFAULT true,
            created_at      TIMESTAMP DEFAULT NOW(),
            finalizado_em   TIMESTAMP
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS ab_resultados (
            id              SERIAL PRIMARY KEY,
            teste_id        INTEGER NOT NULL REFERENCES ab_testes(id) ON DELETE CASCADE,
            conversa_id     INTEGER NOT NULL,
            variante        VARCHAR(1) NOT NULL,
            lead_qualificado BOOLEAN DEFAULT false,
            intencao_compra BOOLEAN DEFAULT false,
            score_lead      FLOAT DEFAULT 0,
            msgs_total      INTEGER DEFAULT 0,
            created_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ab_resultados_teste
        ON ab_resultados (teste_id, variante)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ab_resultados")
    op.execute("DROP TABLE IF EXISTS ab_testes")
    op.execute("DROP TABLE IF EXISTS knowledge_base")
