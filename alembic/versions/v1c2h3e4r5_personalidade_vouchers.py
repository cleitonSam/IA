"""personalidade_ia: usar_vouchers + vouchers_estrategia

Revision ID: v1c2h3e4r5
Revises: m1n2o3p4q5r6
Create Date: 2026-04-29
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'v1c2h3e4r5'
down_revision: Union[str, Sequence[str], None] = 'm1n2o3p4q5r6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE personalidade_ia
        ADD COLUMN IF NOT EXISTS usar_vouchers BOOLEAN DEFAULT false
    """)
    op.execute("""
        ALTER TABLE personalidade_ia
        ADD COLUMN IF NOT EXISTS vouchers_estrategia TEXT
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE personalidade_ia DROP COLUMN IF EXISTS usar_vouchers")
    op.execute("ALTER TABLE personalidade_ia DROP COLUMN IF EXISTS vouchers_estrategia")
