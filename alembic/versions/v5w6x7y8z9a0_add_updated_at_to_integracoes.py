"""add updated_at to integracoes table

Revision ID: v5w6x7y8z9a0
Revises: u4v5w6x7y8z9
Create Date: 2026-03-30

A tabela integracoes foi criada sem updated_at, mas management.py faz:
  - SELECT ... updated_at FROM integracoes
  - UPDATE integracoes SET ..., updated_at = NOW() WHERE ...

Isso causava UndefinedColumnError no GET /management/integrations e no
PUT /management/integrations/{tipo}.

Adiciona a coluna com DEFAULT NOW() e inicializa rows existentes com
o valor de created_at para não deixar NULLs.
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'v5w6x7y8z9a0'
down_revision: Union[str, Sequence[str], None] = 'u4v5w6x7y8z9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adiciona updated_at se não existir
    op.execute("""
        ALTER TABLE integracoes
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()
    """)
    # Preenche rows existentes com o valor de created_at (melhor que NULL)
    op.execute("""
        UPDATE integracoes
        SET updated_at = created_at
        WHERE updated_at IS NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE integracoes DROP COLUMN IF EXISTS updated_at")
