"""add_flow_templates

Revision ID: h1i2j3k4l5m6
Revises: g1h2i3j4k5l6
Create Date: 2026-03-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "h1i2j3k4l5m6"
down_revision = "g1h2i3j4k5l6"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS flow_templates (
            id SERIAL PRIMARY KEY,
            nome VARCHAR(100) NOT NULL,
            categoria VARCHAR(50) NOT NULL DEFAULT 'geral',
            descricao TEXT,
            flow_data JSONB NOT NULL DEFAULT '{}',
            empresa_id INTEGER REFERENCES empresas(id) ON DELETE SET NULL,
            publico BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_flow_templates_categoria ON flow_templates(categoria);
        CREATE INDEX IF NOT EXISTS idx_flow_templates_empresa_id ON flow_templates(empresa_id);
        CREATE INDEX IF NOT EXISTS idx_flow_templates_publico ON flow_templates(publico);
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS flow_templates")
