"""remove_cache_respostas_and_add_kpi_columns

Revision ID: 41c67487b635
Revises: 930ec286d50f
Create Date: 2026-03-14 17:51:22.670378

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '41c67487b635'
down_revision: Union[str, Sequence[str], None] = '930ec286d50f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table('cache_respostas')
    op.add_column('conversas', sa.Column('link_venda_enviado', sa.Boolean(), server_default='false', nullable=True))
    op.add_column('conversas', sa.Column('intencao_de_compra', sa.Boolean(), server_default='false', nullable=True))

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('conversas', 'intencao_de_compra')
    op.drop_column('conversas', 'link_venda_enviado')
    op.create_table(
        'cache_respostas',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=True),
        sa.Column('unidade_id', sa.Integer(), nullable=True),
        sa.Column('hash_pergunta', sa.String(), nullable=True),
        sa.Column('pergunta_original', sa.Text(), nullable=True),
        sa.Column('resposta', sa.Text(), nullable=True),
        sa.Column('modelo_utilizado', sa.String(), nullable=True),
        sa.Column('tokens_utilizados', sa.Integer(), nullable=True),
        sa.Column('vezes_utilizado', sa.Integer(), server_default='1', nullable=True),
        sa.Column('ultimo_uso', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
