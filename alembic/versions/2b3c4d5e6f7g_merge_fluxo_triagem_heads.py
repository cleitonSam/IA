"""merge fluxo triagem heads

Revision ID: 2b3c4d5e6f7g
Revises: 1a2b3c4d5e6f, g1h2i3j4k5l6
Create Date: 2026-03-20 10:30:00.000000

"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2b3c4d5e6f7g'
down_revision: Union[str, Sequence[str], None] = ('1a2b3c4d5e6f', 'g1h2i3j4k5l6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
