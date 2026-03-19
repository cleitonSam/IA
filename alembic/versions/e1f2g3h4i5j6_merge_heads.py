"""merge heads

Revision ID: e1f2g3h4i5j6
Revises: a2b3c4d5e6f7, d1e2f3g4h5i6
Create Date: 2026-03-18 00:00:00.000000

"""
from typing import Sequence, Union

revision: str = 'e1f2g3h4i5j6'
down_revision: Union[str, Sequence[str], None] = ('a2b3c4d5e6f7', 'd1e2f3g4h5i6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
