"""add_nome_to_templates_followup

Revision ID: 69b8030a
Revises: a1b2c3d4e5f6
Create Date: 2026-03-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '69b8030a'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        ALTER TABLE templates_followup
        ADD COLUMN IF NOT EXISTS nome VARCHAR(120)
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('templates_followup', 'nome')
