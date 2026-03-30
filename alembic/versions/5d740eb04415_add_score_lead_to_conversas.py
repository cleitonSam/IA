"""add_score_lead_to_conversas

Revision ID: 5d740eb04415
Revises: 41c67487b635
Create Date: 2026-03-14 18:00:07.863499

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d740eb04415'
down_revision: Union[str, Sequence[str], None] = '41c67487b635'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        ALTER TABLE conversas
            ADD COLUMN IF NOT EXISTS score_lead INTEGER DEFAULT 0
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('conversas', 'score_lead')
