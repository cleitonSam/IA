"""add oferecer_tour to personalidade_ia

Revision ID: p9q0r1s2t3u4
Revises: o8p9q0r1s2t3
Create Date: 2026-03-28

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'p9q0r1s2t3u4'
down_revision: Union[str, Sequence[str], None] = 'o8p9q0r1s2t3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE personalidade_ia ADD COLUMN IF NOT EXISTS oferecer_tour BOOLEAN DEFAULT TRUE')


def downgrade() -> None:
    op.execute('ALTER TABLE personalidade_ia DROP COLUMN IF EXISTS oferecer_tour')
