"""unidade_promo: campos de promocao por unidade

Revision ID: p9r9o9m9o9
Revises: u1n2i3p4r5i6
Create Date: 2026-04-29
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'p9r9o9m9o9'
down_revision: Union[str, Sequence[str], None] = 'u1n2i3p4r5i6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adiciona campos de promocao em unidades. Idempotente (IF NOT EXISTS).
    op.execute("""
        ALTER TABLE unidades
            ADD COLUMN IF NOT EXISTS promo_ativa            BOOLEAN     DEFAULT false,
            ADD COLUMN IF NOT EXISTS promo_nome             VARCHAR(100),
            ADD COLUMN IF NOT EXISTS promo_chamada          TEXT,
            ADD COLUMN IF NOT EXISTS promo_desconto         NUMERIC(10,2),
            ADD COLUMN IF NOT EXISTS promo_desconto_tipo    VARCHAR(20)  DEFAULT 'percentual',
            ADD COLUMN IF NOT EXISTS promo_brinde           TEXT,
            ADD COLUMN IF NOT EXISTS promo_validade_inicio  DATE,
            ADD COLUMN IF NOT EXISTS promo_validade_fim     DATE,
            ADD COLUMN IF NOT EXISTS promo_cor              VARCHAR(7)   DEFAULT '#ff3366',
            ADD COLUMN IF NOT EXISTS promo_emoji            VARCHAR(8)   DEFAULT '🔥',
            ADD COLUMN IF NOT EXISTS promo_observacoes      TEXT,
            ADD COLUMN IF NOT EXISTS promo_voucher_id       INTEGER
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE unidades
            DROP COLUMN IF EXISTS promo_ativa,
            DROP COLUMN IF EXISTS promo_nome,
            DROP COLUMN IF EXISTS promo_chamada,
            DROP COLUMN IF EXISTS promo_desconto,
            DROP COLUMN IF EXISTS promo_desconto_tipo,
            DROP COLUMN IF EXISTS promo_brinde,
            DROP COLUMN IF EXISTS promo_validade_inicio,
            DROP COLUMN IF EXISTS promo_validade_fim,
            DROP COLUMN IF EXISTS promo_cor,
            DROP COLUMN IF EXISTS promo_emoji,
            DROP COLUMN IF EXISTS promo_observacoes,
            DROP COLUMN IF EXISTS promo_voucher_id
    """)
