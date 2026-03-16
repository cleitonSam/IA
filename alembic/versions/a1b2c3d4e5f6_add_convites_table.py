"""add_convites_table

Revision ID: a1b2c3d4e5f6
Revises: 89e716bfb81f
Create Date: 2026-03-14 22:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '89e716bfb81f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table('convites'):
        op.create_table(
            'convites',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('empresa_id', sa.Integer(), sa.ForeignKey('empresas.id', ondelete='CASCADE'), nullable=False),
            sa.Column('email', sa.String(255), nullable=False),
            sa.Column('token', sa.String(64), nullable=False, unique=True),
            sa.Column('usado', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index('ix_convites_token', 'convites', ['token'], unique=True)
        op.create_index('ix_convites_email', 'convites', ['email'])
    else:
        # Tabela já existe — garante que os indexes existam
        existing_indexes = {idx['name'] for idx in inspector.get_indexes('convites')}
        if 'ix_convites_token' not in existing_indexes:
            op.create_index('ix_convites_token', 'convites', ['token'], unique=True)
        if 'ix_convites_email' not in existing_indexes:
            op.create_index('ix_convites_email', 'convites', ['email'])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table('convites'):
        return

    existing_indexes = {idx['name'] for idx in inspector.get_indexes('convites')}
    if 'ix_convites_email' in existing_indexes:
        op.drop_index('ix_convites_email', table_name='convites')
    if 'ix_convites_token' in existing_indexes:
        op.drop_index('ix_convites_token', table_name='convites')

    op.drop_table('convites')
