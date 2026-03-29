"""merge_all_heads

Revision ID: 3cd6b04c5258
Revises: 2b3c4d5e6f7g, m6n7o8p9q0r1
Create Date: 2026-03-27 22:52:04.601280

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3cd6b04c5258'
down_revision: Union[str, Sequence[str], None] = ('2b3c4d5e6f7g', 'm6n7o8p9q0r1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
