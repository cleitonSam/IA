"""add colunas faltantes: conversas (primeira_resposta_em, score_interesse) e planos (unidade_id)

Revision ID: y8z9a0b1c2d3
Revises: x7y8z9a0b1c2
Create Date: 2026-03-30

Corrige três erros de runtime:

1. `column "primeira_resposta_em" does not exist`
   - registrar_primeira_resposta() em main.py faz UPDATE SET primeira_resposta_em = NOW()
   - bd_registrar_metricas_turno() em db_queries.py calcula tempo médio lendo esta coluna

2. `column "score_interesse" does not exist`
   - bd_registrar_evento_funil() em main.py faz UPDATE conversas SET score_interesse = ...
   - Coluna paralela a score_lead (adicionada em x7y8z9a0b1c2);
     score_interesse é incrementado via main.py, score_lead via db_queries.py

3. `column "unidade_id" does not exist` (em planos)  ← CRASH CRÍTICO
   - buscar_planos_ativos() adiciona AND (unidade_id = $2 OR unidade_id IS NULL) quando
     chamado com unidade_id — mas a tabela foi criada sem esta coluna
   - sincronizar_planos_evo() em db_queries.py faz UPDATE planos SET unidade_id = ...
     e INSERT INTO planos (..., unidade_id, ...) — ambos falham sem a coluna
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'y8z9a0b1c2d3'
down_revision: Union[str, Sequence[str], None] = 'x7y8z9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. conversas ──────────────────────────────────────────────────────────
    op.execute("ALTER TABLE conversas ADD COLUMN IF NOT EXISTS primeira_resposta_em TIMESTAMP")
    op.execute("ALTER TABLE conversas ADD COLUMN IF NOT EXISTS score_interesse       INTEGER DEFAULT 0")

    # ── 2. planos ─────────────────────────────────────────────────────────────
    # unidade_id permite filtrar planos por unidade; NULL = plano global da empresa
    op.execute("ALTER TABLE planos ADD COLUMN IF NOT EXISTS unidade_id INTEGER REFERENCES unidades(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_planos_unidade_id ON planos (unidade_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_planos_unidade_id")
    op.execute("ALTER TABLE planos   DROP COLUMN IF EXISTS unidade_id")
    op.execute("ALTER TABLE conversas DROP COLUMN IF EXISTS score_interesse")
    op.execute("ALTER TABLE conversas DROP COLUMN IF EXISTS primeira_resposta_em")
