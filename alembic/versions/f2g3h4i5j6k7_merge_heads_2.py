"""merge heads 2

Revision ID: f2g3h4i5j6k7
Revises: e1f2g3h4i5j6, c2d3e4f5g6h7
Create Date: 2026-03-18 00:00:00.000000

"""
from typing import Sequence, Union

revision: str = 'f2g3h4i5j6k7'
down_revision: Union[str, Sequence[str], None] = ('e1f2g3h4i5j6', 'c2d3e4f5g6h7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
