"""add_tts_settings_to_personalidade

Revision ID: o8p9q0r1s2t3
Revises: n7o8p9q0r1s2
Create Date: 2026-03-27

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'o8p9q0r1s2t3'
down_revision: Union[str, Sequence[str], None] = 'n7o8p9q0r1s2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adiciona campos TTS à tabela personalidade_ia
    op.execute("""
        ALTER TABLE personalidade_ia
        ADD COLUMN IF NOT EXISTS tts_ativo BOOLEAN DEFAULT TRUE,
        ADD COLUMN IF NOT EXISTS tts_voz VARCHAR(50) DEFAULT 'Kore';
    """)

    # Comentários para documentação
    op.execute("""
        COMMENT ON COLUMN personalidade_ia.tts_ativo IS 'Ativa/desativa resposta por áudio (TTS) quando cliente envia áudio';
        COMMENT ON COLUMN personalidade_ia.tts_voz IS 'Nome da voz Gemini TTS (ex: Kore, Aoede, Orus, Charon)';
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE personalidade_ia
        DROP COLUMN IF EXISTS tts_ativo,
        DROP COLUMN IF EXISTS tts_voz;
    """)
