"""Add contato_fone to conversas

Revision ID: 930ec286d50f
Revises: 3c6b915e866e
Create Date: 2026-03-14 13:27:37.559236

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '930ec286d50f'
down_revision: Union[str, Sequence[str], None] = '3c6b915e866e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('conversas', sa.Column('contato_fone', sa.String(length=50), nullable=True))
    # Criar um índice para buscas rápidas por telefone (UazAPI)
    op.create_index('ix_conversas_contato_fone', 'conversas', ['contato_fone'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_conversas_contato_fone', table_name='conversas')
    op.drop_column('conversas', 'contato_fone')
