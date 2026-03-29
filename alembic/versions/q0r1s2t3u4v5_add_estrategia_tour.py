"""add estrategia_tour fields to personalidade_ia

Revision ID: q0r1s2t3u4v5
Revises: p9q0r1s2t3u4
Create Date: 2026-03-28

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'q0r1s2t3u4v5'
down_revision: Union[str, Sequence[str], None] = 'p9q0r1s2t3u4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE personalidade_ia ADD COLUMN IF NOT EXISTS estrategia_tour TEXT DEFAULT 'smart'")
    op.execute("ALTER TABLE personalidade_ia ADD COLUMN IF NOT EXISTS tour_perguntar_primeira_visita BOOLEAN DEFAULT TRUE")
    op.execute("ALTER TABLE personalidade_ia ADD COLUMN IF NOT EXISTS tour_mensagem_custom TEXT")


def downgrade() -> None:
    op.execute('ALTER TABLE personalidade_ia DROP COLUMN IF EXISTS estrategia_tour')
    op.execute('ALTER TABLE personalidade_ia DROP COLUMN IF EXISTS tour_perguntar_primeira_visita')
    op.execute('ALTER TABLE personalidade_ia DROP COLUMN IF EXISTS tour_mensagem_custom')
