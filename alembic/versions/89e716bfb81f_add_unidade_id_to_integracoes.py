"""add_unidade_id_to_integracoes

Revision ID: 89e716bfb81f
Revises: 5d740eb04415
Create Date: 2026-03-14 18:27:21.528686

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '89e716bfb81f'
down_revision: Union[str, Sequence[str], None] = '5d740eb04415'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('integracoes', sa.Column('unidade_id', sa.Integer(), sa.ForeignKey('unidades.id', ondelete='CASCADE'), nullable=True))
    op.drop_constraint('integracoes_empresa_id_tipo_key', 'integracoes', type_='unique')
    
    # Índice único para integração por unidade
    op.create_index('ix_integracoes_empresa_tipo_unidade', 'integracoes', ['empresa_id', 'tipo', 'unidade_id'], unique=True, postgresql_where=sa.text('unidade_id IS NOT NULL'))
    
    # Índice único para integração global (unidade_id nulo)
    op.create_index('ix_integracoes_empresa_tipo_global', 'integracoes', ['empresa_id', 'tipo'], unique=True, postgresql_where=sa.text('unidade_id IS NULL'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_integracoes_empresa_tipo_global', table_name='integracoes')
    op.drop_index('ix_integracoes_empresa_tipo_unidade', table_name='integracoes')
    op.create_unique_constraint('integracoes_empresa_id_tipo_key', 'integracoes', ['empresa_id', 'tipo'])
    op.drop_column('integracoes', 'unidade_id')
