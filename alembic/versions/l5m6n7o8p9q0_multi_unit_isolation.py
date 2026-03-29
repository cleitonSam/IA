"""multi-unit isolation: conversas composite index + webhook_secret

Revision ID: l5m6n7o8p9q0
Revises: k4l5m6n7o8p9
Create Date: 2026-03-27

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'l5m6n7o8p9q0'
down_revision: Union[str, Sequence[str], None] = 'k4l5m6n7o8p9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Fix conversas unique index: (conversation_id, empresa_id) instead of just conversation_id
    #    Previne colisão entre empresas que usam o mesmo Chatwoot
    op.execute("DROP INDEX IF EXISTS ix_conversas_conversation_id")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_conversas_conversation_id_empresa
        ON conversas (conversation_id, empresa_id)
    """)

    # 2. Add webhook_secret to integracoes (validação de webhooks UazAPI)
    op.execute("""
        ALTER TABLE integracoes
        ADD COLUMN IF NOT EXISTS webhook_secret VARCHAR(64)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE integracoes DROP COLUMN IF EXISTS webhook_secret")
    op.execute("DROP INDEX IF EXISTS ix_conversas_conversation_id_empresa")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_conversas_conversation_id
        ON conversas (conversation_id)
    """)
