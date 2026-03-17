"""add_enviado_em_updated_at_to_followups

Revision ID: f1a2b3c4d5e6
Revises: 5d740eb04415
Create Date: 2026-03-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = '5d740eb04415'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE followups
            ADD COLUMN IF NOT EXISTS enviado_em TIMESTAMP WITHOUT TIME ZONE,
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE
    """)


def downgrade() -> None:
    op.drop_column('followups', 'enviado_em')
    op.drop_column('followups', 'updated_at')
