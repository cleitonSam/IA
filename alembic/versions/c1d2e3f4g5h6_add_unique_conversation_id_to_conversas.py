"""add_unique_conversation_id_to_conversas

Revision ID: c1d2e3f4g5h6
Revises: 69b8030a
Create Date: 2026-03-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4g5h6'
down_revision: Union[str, Sequence[str], None] = '69b8030a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_conversas_conversation_id
        ON conversas (conversation_id)
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_conversas_conversation_id', table_name='conversas')
