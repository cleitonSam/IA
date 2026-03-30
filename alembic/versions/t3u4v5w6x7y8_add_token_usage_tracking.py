"""add token usage tracking table

Revision ID: t3u4v5w6x7y8
Revises: s2t3u4v5w6x7
Create Date: 2026-03-29

Cria tabela para rastrear consumo de tokens e custo por empresa/dia/modelo.
Permite dashboards de custo, alertas de budget e otimização de gastos.
"""
from typing import Sequence, Union
from alembic import op


revision: str = 't3u4v5w6x7y8'
down_revision: Union[str, Sequence[str], None] = 's2t3u4v5w6x7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS token_usage (
            id          BIGSERIAL PRIMARY KEY,
            empresa_id  INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            data        DATE NOT NULL DEFAULT CURRENT_DATE,
            modelo      TEXT NOT NULL,
            tokens_in   INTEGER NOT NULL DEFAULT 0,
            tokens_out  INTEGER NOT NULL DEFAULT 0,
            custo_usd   NUMERIC(10, 6) NOT NULL DEFAULT 0,
            req_count   INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            updated_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Índice único: 1 registro por empresa+data+modelo (upsert eficiente)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_token_usage_empresa_data_modelo
        ON token_usage(empresa_id, data, modelo)
    """)

    # Índice para queries de resumo por empresa
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_token_usage_empresa_data
        ON token_usage(empresa_id, data DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS token_usage CASCADE")
