"""add_horario_atendimento_ia_to_personalidade_ia

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-03-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE personalidade_ia
            ADD COLUMN IF NOT EXISTS horario_atendimento_ia JSONB
    """)


def downgrade() -> None:
    op.drop_column('personalidade_ia', 'horario_atendimento_ia')
