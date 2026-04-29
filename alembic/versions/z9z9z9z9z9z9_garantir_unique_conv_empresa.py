"""garantir unique composto (conversation_id, empresa_id) — fix idempotente

Revision ID: z9z9z9z9z9z9
Revises: r2s3t4u5v6w7
Create Date: 2026-04-29

Migration anterior (r2s3t4u5v6w7) tentou dropar o unique antigo e criar o composto,
mas em alguns ambientes o INDEX antigo ix_conversas_conversation_id continuou existindo
ou foi recriado. Esta migration FORCA o estado correto:
  - DROP do index antigo (incluindo se for CONSTRAINT)
  - CREATE do composto (conversation_id, empresa_id) se faltar
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'z9z9z9z9z9z9'
down_revision: Union[str, Sequence[str], None] = 'r2s3t4u5v6w7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop tanto INDEX quanto CONSTRAINT (caso tenha sido criada como UNIQUE constraint)
    op.execute("ALTER TABLE conversas DROP CONSTRAINT IF EXISTS ix_conversas_conversation_id")
    op.execute("DROP INDEX IF EXISTS ix_conversas_conversation_id")

    # 2. Garante o composto (idempotente)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_conversas_conversation_id_empresa
        ON conversas (conversation_id, empresa_id)
    """)


def downgrade() -> None:
    # Recria o legado pra reverter
    op.execute("DROP INDEX IF EXISTS ix_conversas_conversation_id_empresa")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_conversas_conversation_id
        ON conversas (conversation_id)
    """)
