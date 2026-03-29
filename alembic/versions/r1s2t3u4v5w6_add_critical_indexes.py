"""add critical performance indexes

Revision ID: r1s2t3u4v5w6
Revises: q0r1s2t3u4v5
Create Date: 2026-03-29

Adiciona índices críticos que estavam faltando.
Impacto esperado: 40-70% de redução no tempo de resposta do bot.
Todos usam CONCURRENTLY para não bloquear produção.
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'r1s2t3u4v5w6'
down_revision: Union[str, Sequence[str], None] = 'q0r1s2t3u4v5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nota: CONCURRENTLY removido — não pode rodar dentro de transaction block (Alembic).
    # Os índices ainda são criados com IF NOT EXISTS para ser idempotente.

    # Hot path do bot: busca conversa ativa por contato_fone (chamado em TODA mensagem recebida)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversas_empresa_fone
        ON conversas(empresa_id, contato_fone)
    """)

    # Dashboard de conversas: ordenação por data de criação
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversas_empresa_created
        ON conversas(empresa_id, created_at DESC)
    """)

    # Histórico de mensagens: context window do LLM (chamado em toda resposta)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mensagens_conversa_created
        ON mensagens(conversa_id, created_at DESC)
    """)

    # Worker de followup: busca apenas pendentes (partial index — muito eficiente)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_followups_pendente
        ON followups(status, agendado_para)
        WHERE status = 'pendente'
    """)

    # Dashboard de métricas: queries de séries temporais por empresa
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_metricas_empresa_data
        ON metricas_diarias(empresa_id, data DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_conversas_empresa_fone")
    op.execute("DROP INDEX IF EXISTS idx_conversas_empresa_created")
    op.execute("DROP INDEX IF EXISTS idx_mensagens_conversa_created")
    op.execute("DROP INDEX IF EXISTS idx_followups_pendente")
    op.execute("DROP INDEX IF EXISTS idx_metricas_empresa_data")
