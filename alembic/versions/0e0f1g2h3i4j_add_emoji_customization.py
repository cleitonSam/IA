"""add emoji customization

Revision ID: 0e0f1g2h3i4j
Revises: f10d53f6e433
Create Date: 2026-03-19 18:22:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0e0f1g2h3i4j'
down_revision: Union[str, Sequence[str], None] = 'f10d53f6e433'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute('ALTER TABLE personalidade_ia ADD COLUMN IF NOT EXISTS emoji_tipo VARCHAR(50)')
    op.execute('ALTER TABLE personalidade_ia ADD COLUMN IF NOT EXISTS emoji_cor VARCHAR(50)')


def downgrade() -> None:
    """Downgrade schema."""
    op.execute('ALTER TABLE personalidade_ia DROP COLUMN IF EXISTS emoji_tipo')
    op.execute('ALTER TABLE personalidade_ia DROP COLUMN IF EXISTS emoji_cor')
