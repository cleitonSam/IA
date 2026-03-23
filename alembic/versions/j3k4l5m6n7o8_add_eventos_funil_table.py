"""add_eventos_funil_table

Revision ID: j3k4l5m6n7o8
Revises: i2j3k4l5m6n7
Create Date: 2026-03-23

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'j3k4l5m6n7o8'
down_revision: Union[str, Sequence[str], None] = 'i2j3k4l5m6n7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS eventos_funil (
            id              SERIAL PRIMARY KEY,
            conversa_id     INTEGER NOT NULL,
            empresa_id      INTEGER NOT NULL,
            tipo_evento     VARCHAR(100) NOT NULL,
            descricao       TEXT,
            score_incremento INTEGER DEFAULT 1,
            created_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_eventos_funil_conversa
        ON eventos_funil (conversa_id, tipo_evento)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS eventos_funil")
