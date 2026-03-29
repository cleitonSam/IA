"""add_coordinates_to_unidades

Revision ID: m6n7o8p9q0r1
Revises: l5m6n7o8p9q0
Create Date: 2026-03-27

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'm6n7o8p9q0r1'
down_revision: Union[str, Sequence[str], None] = 'l5m6n7o8p9q0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE unidades ADD COLUMN IF NOT EXISTS latitude FLOAT")
    op.execute("ALTER TABLE unidades ADD COLUMN IF NOT EXISTS longitude FLOAT")


def downgrade() -> None:
    op.execute("ALTER TABLE unidades DROP COLUMN IF EXISTS latitude")
    op.execute("ALTER TABLE unidades DROP COLUMN IF EXISTS longitude")
