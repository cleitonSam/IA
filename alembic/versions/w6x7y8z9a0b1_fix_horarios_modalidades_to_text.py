"""fix horarios and modalidades columns: JSONB -> TEXT

Revision ID: w6x7y8z9a0b1
Revises: v5w6x7y8z9a0
Create Date: 2026-03-30

A migration u4v5w6x7y8z9 criou horarios e modalidades como JSONB, mas
esses campos recebem texto livre do frontend (ex: "Segunda-Sexta 6h-22h",
"Musculação, Yoga, Pilates"). Texto livre não é JSON válido e causa erro
no PostgreSQL ao tentar fazer o cast.

Converte de JSONB → TEXT. Se já forem TEXT, o IF block é ignorado.
Valores JSONB existentes são convertidos para texto via jsonb_typeof.
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'w6x7y8z9a0b1'
down_revision: Union[str, Sequence[str], None] = 'v5w6x7y8z9a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Converte horarios JSONB → TEXT
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'unidades'
                  AND column_name = 'horarios'
                  AND data_type = 'jsonb'
            ) THEN
                ALTER TABLE unidades
                    ALTER COLUMN horarios
                    TYPE TEXT
                    USING CASE
                        WHEN horarios IS NULL THEN NULL
                        WHEN jsonb_typeof(horarios) = 'string' THEN horarios #>> '{}'
                        ELSE horarios::text
                    END;
            END IF;
        END $$;
    """)

    # Converte modalidades JSONB → TEXT
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'unidades'
                  AND column_name = 'modalidades'
                  AND data_type = 'jsonb'
            ) THEN
                ALTER TABLE unidades
                    ALTER COLUMN modalidades
                    TYPE TEXT
                    USING CASE
                        WHEN modalidades IS NULL THEN NULL
                        WHEN jsonb_typeof(modalidades) = 'string' THEN modalidades #>> '{}'
                        ELSE modalidades::text
                    END;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    # TEXT → JSONB (só funciona se os valores forem JSON válido)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'unidades'
                  AND column_name = 'horarios'
                  AND data_type = 'text'
            ) THEN
                ALTER TABLE unidades ALTER COLUMN horarios TYPE JSONB
                    USING CASE WHEN horarios IS NULL OR horarios = '' THEN NULL
                               ELSE horarios::jsonb END;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'unidades'
                  AND column_name = 'modalidades'
                  AND data_type = 'text'
            ) THEN
                ALTER TABLE unidades ALTER COLUMN modalidades TYPE JSONB
                    USING CASE WHEN modalidades IS NULL OR modalidades = '' THEN NULL
                               ELSE modalidades::jsonb END;
            END IF;
        END $$;
    """)
