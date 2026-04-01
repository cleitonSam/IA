"""fix uso_ia add modelo and latencia_ms columns

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-04-01

A migration z9a0b1c2d3e4 foi marcada como aplicada antes de incluir
os ALTER TABLE para modelo e latencia_ms. Esta migration garante que
as colunas existam.
"""
from alembic import op

# revision identifiers
revision = "c3d4e5f6g7h8"
down_revision = "b2c3d4e5f6g7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE uso_ia ADD COLUMN IF NOT EXISTS modelo      VARCHAR(100)")
    op.execute("ALTER TABLE uso_ia ADD COLUMN IF NOT EXISTS latencia_ms INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE uso_ia DROP COLUMN IF EXISTS latencia_ms")
    op.execute("ALTER TABLE uso_ia DROP COLUMN IF EXISTS modelo")
