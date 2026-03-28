"""add_memoria_cliente_table

Revision ID: l5m6n7o8p9q0
Revises: k4l5m6n7o8p9
Create Date: 2026-03-27

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'l5m6n7o8p9q0'
down_revision: Union[str, Sequence[str], None] = 'k4l5m6n7o8p9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS memoria_cliente (
            id              SERIAL PRIMARY KEY,
            empresa_id      INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            contato_fone    VARCHAR(30) NOT NULL,
            tipo            VARCHAR(30) NOT NULL,
            conteudo        TEXT NOT NULL,
            relevancia      FLOAT DEFAULT 1.0,
            created_at      TIMESTAMP DEFAULT NOW(),
            updated_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_memoria_fone
        ON memoria_cliente (contato_fone, empresa_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_memoria_tipo
        ON memoria_cliente (empresa_id, tipo)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS memoria_cliente")
