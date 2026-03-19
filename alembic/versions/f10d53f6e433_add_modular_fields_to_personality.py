"""add modular fields to personality

Revision ID: f10d53f6e433
Revises: f2g3h4i5j6k7
Create Date: 2026-03-19 18:08:18.248880

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f10d53f6e433'
down_revision: Union[str, Sequence[str], None] = 'f2g3h4i5j6k7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema using IF NOT EXISTS for robustness."""
    columns = [
        ('idioma', 'VARCHAR(100)'),
        ('objetivos_venda', 'TEXT'),
        ('metas_comerciais', 'TEXT'),
        ('script_vendas', 'TEXT'),
        ('scripts_objecoes', 'TEXT'),
        ('frases_fechamento', 'TEXT'),
        ('diferenciais', 'TEXT'),
        ('posicionamento', 'TEXT'),
        ('publico_alvo', 'TEXT'),
        ('restricoes', 'TEXT'),
        ('linguagem_proibida', 'TEXT'),
        ('contexto_empresa', 'TEXT'),
        ('contexto_extra', 'TEXT'),
        ('abordagem_proativa', 'TEXT'),
        ('exemplos', 'TEXT'),
        ('palavras_proibidas', 'TEXT'),
        ('despedida_personalizada', 'TEXT'),
        ('regras_formatacao', 'TEXT'),
        ('regras_seguranca', 'TEXT'),
    ]
    for name, type_ in columns:
        op.execute(f'ALTER TABLE personalidade_ia ADD COLUMN IF NOT EXISTS {name} {type_}')


def downgrade() -> None:
    """Downgrade schema."""
    columns = [
        'regras_seguranca', 'regras_formatacao', 'despedida_personalizada',
        'palavras_proibidas', 'exemplos', 'abordagem_proativa',
        'contexto_extra', 'contexto_empresa', 'linguagem_proibida',
        'restricoes', 'publico_alvo', 'posicionamento', 'diferenciais',
        'frases_fechamento', 'scripts_objecoes', 'script_vendas',
        'metas_comerciais', 'objetivos_venda', 'idioma'
    ]
    for name in columns:
        # op.drop_column não tem IF EXISTS nativo no Alembic para todas as versões,
        # mas podemos usar SQL puro.
        op.execute(f'ALTER TABLE personalidade_ia DROP COLUMN IF EXISTS {name}')
