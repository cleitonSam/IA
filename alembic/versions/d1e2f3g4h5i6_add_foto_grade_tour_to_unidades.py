"""add_foto_grade_tour_to_unidades

Revision ID: d1e2f3g4h5i6
Revises: c1d2e3f4g5h6
Create Date: 2026-03-16 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3g4h5i6'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4g5h6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_cols = {col['name'] for col in inspector.get_columns('unidades')}

    if 'foto_grade' not in existing_cols:
        op.add_column('unidades', sa.Column('foto_grade', sa.Text(), nullable=True))

    if 'link_tour_virtual' not in existing_cols:
        op.add_column('unidades', sa.Column('link_tour_virtual', sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_cols = {col['name'] for col in inspector.get_columns('unidades')}

    if 'link_tour_virtual' in existing_cols:
        op.drop_column('unidades', 'link_tour_virtual')

    if 'foto_grade' in existing_cols:
        op.drop_column('unidades', 'foto_grade')
