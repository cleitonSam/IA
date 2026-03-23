"""add estilo_comunicacao saudacao_personalizada regras_atendimento to personalidade_ia

Revision ID: k4l5m6n7o8p9
Revises: j3k4l5m6n7o8
Create Date: 2026-03-23

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'k4l5m6n7o8p9'
down_revision: Union[str, Sequence[str], None] = 'j3k4l5m6n7o8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for col, tipo in [
        ('estilo_comunicacao',   'TEXT'),
        ('saudacao_personalizada', 'TEXT'),
        ('regras_atendimento',   'TEXT'),
    ]:
        op.execute(f'ALTER TABLE personalidade_ia ADD COLUMN IF NOT EXISTS {col} {tipo}')


def downgrade() -> None:
    for col in ['regras_atendimento', 'saudacao_personalizada', 'estilo_comunicacao']:
        op.execute(f'ALTER TABLE personalidade_ia DROP COLUMN IF EXISTS {col}')
