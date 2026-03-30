"""add csat sentiment and followup filters

Revision ID: a1b2c3d4e5f6
Revises: z9a0b1c2d3e4
Create Date: 2026-03-30

Adiciona campos de avaliação CSAT e sentimento IA na tabela conversas,
e campos de filtro inteligente na tabela templates_followup.

Campos em conversas:
  - rating_csat: nota CSAT recebida (1–5), preenchida via webhook Chatwoot
  - sentimento_ia: classificação do sentimento pela IA após resolução
    (ex: "positivo", "neutro", "negativo", "irritado", "cancelamento")
  - cancelamento_detectado: flag booleana se IA detectou intenção de cancelamento

Campos em templates_followup:
  - filtro_rating_min: nota mínima do CSAT para enviar (0 = sem filtro)
  - filtro_sentimentos_excluir: array JSON de sentimentos que BLOQUEIAM o envio
    ex: '["irritado","negativo","cancelamento"]'
  - bloquear_cancelamento: se TRUE, não envia se cancelamento_detectado = TRUE
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "a1b2c3d4e5f6"
down_revision = "z9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── conversas: campos CSAT + sentimento ──────────────────────────────
    op.execute("""
        ALTER TABLE conversas
          ADD COLUMN IF NOT EXISTS rating_csat              SMALLINT DEFAULT NULL,
          ADD COLUMN IF NOT EXISTS sentimento_ia            VARCHAR(50) DEFAULT NULL,
          ADD COLUMN IF NOT EXISTS cancelamento_detectado   BOOLEAN DEFAULT FALSE;
    """)

    # ── templates_followup: filtros inteligentes ─────────────────────────
    op.execute("""
        ALTER TABLE templates_followup
          ADD COLUMN IF NOT EXISTS filtro_rating_min          SMALLINT NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS filtro_sentimentos_excluir TEXT NOT NULL DEFAULT '[]',
          ADD COLUMN IF NOT EXISTS bloquear_cancelamento       BOOLEAN NOT NULL DEFAULT FALSE;
    """)

    # Índice para consultas por sentimento e CSAT no histórico
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversas_sentimento_ia
          ON conversas (empresa_id, sentimento_ia)
          WHERE sentimento_ia IS NOT NULL;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversas_rating_csat
          ON conversas (empresa_id, rating_csat)
          WHERE rating_csat IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_conversas_rating_csat;")
    op.execute("DROP INDEX IF EXISTS idx_conversas_sentimento_ia;")
    op.execute("""
        ALTER TABLE templates_followup
          DROP COLUMN IF EXISTS bloquear_cancelamento,
          DROP COLUMN IF EXISTS filtro_sentimentos_excluir,
          DROP COLUMN IF EXISTS filtro_rating_min;
    """)
    op.execute("""
        ALTER TABLE conversas
          DROP COLUMN IF EXISTS cancelamento_detectado,
          DROP COLUMN IF EXISTS sentimento_ia,
          DROP COLUMN IF EXISTS rating_csat;
    """)
