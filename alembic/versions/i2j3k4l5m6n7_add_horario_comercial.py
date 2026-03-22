"""add_horario_comercial_to_personalidade_ia

Revision ID: i2j3k4l5m6n7
Revises: h1i2j3k4l5m6
Create Date: 2026-03-22

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'i2j3k4l5m6n7'
down_revision: Union[str, Sequence[str], None] = 'h1i2j3k4l5m6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        'ALTER TABLE personalidade_ia ADD COLUMN IF NOT EXISTS horario_comercial JSONB'
    )


def downgrade() -> None:
    op.execute(
        'ALTER TABLE personalidade_ia DROP COLUMN IF EXISTS horario_comercial'
    )
