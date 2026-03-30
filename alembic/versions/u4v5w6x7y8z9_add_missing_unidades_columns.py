"""add missing columns to unidades table

Revision ID: u4v5w6x7y8z9
Revises: t3u4v5w6x7y8
Create Date: 2026-03-29

Adiciona colunas que faltavam na tabela unidades:
  - uuid, nome_abreviado, numero, telefone_principal
  - horarios, modalidades, planos, formas_pagamento, convenios, infraestrutura

Também converte servicos e palavras_chave de TEXT → JSONB.
Antes de converter, normaliza os valores que não são JSON válido
(ex: "Consultoria" → '"Consultoria"') para que o cast não falhe.

Usa ADD COLUMN IF NOT EXISTS e blocos DO $$ para ser idempotente.
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'u4v5w6x7y8z9'
down_revision: Union[str, Sequence[str], None] = 't3u4v5w6x7y8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Adiciona colunas simples que faltam
    op.execute("ALTER TABLE unidades ADD COLUMN IF NOT EXISTS uuid TEXT")
    op.execute("ALTER TABLE unidades ADD COLUMN IF NOT EXISTS nome_abreviado VARCHAR(100)")
    op.execute("ALTER TABLE unidades ADD COLUMN IF NOT EXISTS numero VARCHAR(20)")
    op.execute("ALTER TABLE unidades ADD COLUMN IF NOT EXISTS telefone_principal VARCHAR(50)")

    # 2. Adiciona colunas JSONB que faltam
    op.execute("ALTER TABLE unidades ADD COLUMN IF NOT EXISTS horarios JSONB")
    op.execute("ALTER TABLE unidades ADD COLUMN IF NOT EXISTS modalidades JSONB")
    op.execute("ALTER TABLE unidades ADD COLUMN IF NOT EXISTS planos JSONB")
    op.execute("ALTER TABLE unidades ADD COLUMN IF NOT EXISTS formas_pagamento JSONB")
    op.execute("ALTER TABLE unidades ADD COLUMN IF NOT EXISTS convenios JSONB")
    op.execute("ALTER TABLE unidades ADD COLUMN IF NOT EXISTS infraestrutura JSONB")

    # 3. Converte servicos TEXT → JSONB
    #    Valores como "Consultoria" (texto simples) são convertidos em
    #    JSON strings  ("Consultoria") antes do ALTER para evitar erro de cast.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'unidades'
                  AND column_name = 'servicos'
                  AND data_type = 'text'
            ) THEN
                -- Normaliza linhas com texto simples (não começa com [ { ou ")
                UPDATE unidades
                SET servicos = to_json(servicos)::text
                WHERE servicos IS NOT NULL
                  AND servicos <> ''
                  AND servicos NOT SIMILAR TO '\s*[\[{"]%';

                -- Agora todos os valores são JSON válido; faz o cast
                ALTER TABLE unidades
                    ALTER COLUMN servicos
                    TYPE JSONB
                    USING CASE
                        WHEN servicos IS NULL OR servicos = '' THEN NULL
                        ELSE servicos::jsonb
                    END;
            END IF;
        END $$;
    """)

    # 4. Converte palavras_chave TEXT → JSONB
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'unidades'
                  AND column_name = 'palavras_chave'
                  AND data_type = 'text'
            ) THEN
                -- Normaliza linhas com texto simples
                UPDATE unidades
                SET palavras_chave = to_json(palavras_chave)::text
                WHERE palavras_chave IS NOT NULL
                  AND palavras_chave <> ''
                  AND palavras_chave NOT SIMILAR TO '\s*[\[{"]%';

                ALTER TABLE unidades
                    ALTER COLUMN palavras_chave
                    TYPE JSONB
                    USING CASE
                        WHEN palavras_chave IS NULL OR palavras_chave = '' THEN NULL
                        ELSE palavras_chave::jsonb
                    END;
            END IF;
        END $$;
    """)

    # 5. Garante foto_grade e link_tour_virtual (podem ter sido adicionados
    #    pela migration d1e2f3g4h5i6, mas se não rodou, adicionamos aqui)
    op.execute("ALTER TABLE unidades ADD COLUMN IF NOT EXISTS foto_grade TEXT")
    op.execute("ALTER TABLE unidades ADD COLUMN IF NOT EXISTS link_tour_virtual TEXT")


def downgrade() -> None:
    # Remove apenas as colunas novas; não reverte TEXT→JSONB (risco de perda)
    for col in [
        'infraestrutura', 'convenios', 'formas_pagamento', 'planos',
        'modalidades', 'horarios', 'telefone_principal', 'numero',
        'nome_abreviado', 'uuid',
    ]:
        op.execute(f"ALTER TABLE unidades DROP COLUMN IF EXISTS {col}")
