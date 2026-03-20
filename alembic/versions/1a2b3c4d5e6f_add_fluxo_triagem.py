"""add fluxo_triagem to personalidade_ia

Revision ID: 1a2b3c4d5e6f
Revises: 0e0f1g2h3i4j
Create Date: 2026-03-20 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, Sequence[str], None] = '0e0f1g2h3i4j'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Adiciona coluna fluxo_triagem JSONB para o editor visual de fluxo."""
    op.execute(
        'ALTER TABLE personalidade_ia ADD COLUMN IF NOT EXISTS fluxo_triagem JSONB'
    )


def downgrade() -> None:
    """Remove coluna fluxo_triagem."""
    op.execute(
        'ALTER TABLE personalidade_ia DROP COLUMN IF EXISTS fluxo_triagem'
    )
