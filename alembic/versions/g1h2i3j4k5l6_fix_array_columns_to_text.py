"""fix array columns to text in personalidade_ia

Revision ID: g1h2i3j4k5l6
Revises: f10d53f6e433
Create Date: 2026-03-19 20:00:00.000000

Corrige colunas que foram criadas como TEXT[] (array) em vez de TEXT simples.
Usa DO $$ ... $$ para verificar o tipo antes de alterar — seguro de rodar múltiplas vezes.
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'g1h2i3j4k5l6'
down_revision: Union[str, Sequence[str], None] = '0e0f1g2h3i4j'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Colunas que devem ser TEXT simples mas podem estar como TEXT[]
_COLUMNS = [
    'palavras_proibidas',
    'linguagem_proibida',
    'restricoes',
    'scripts_objecoes',
    'frases_fechamento',
    'diferenciais',
    'posicionamento',
    'publico_alvo',
    'objetivos_venda',
    'metas_comerciais',
    'script_vendas',
    'contexto_empresa',
    'contexto_extra',
    'abordagem_proativa',
    'exemplos',
    'despedida_personalizada',
    'regras_formatacao',
    'regras_seguranca',
]


def upgrade() -> None:
    """Converte colunas TEXT[] → TEXT, concatenando itens com vírgula."""
    for col in _COLUMNS:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'personalidade_ia'
                      AND column_name = '{col}'
                      AND data_type = 'ARRAY'
                ) THEN
                    ALTER TABLE personalidade_ia
                        ALTER COLUMN {col}
                        TYPE TEXT
                        USING array_to_string({col}, ', ');
                END IF;
            END $$;
        """)


def downgrade() -> None:
    """Não desfaz — conversão de TEXT[] → TEXT com perda de estrutura."""
    pass
