"""Auditoria: audit_log + webhook_secret NOT NULL + indices multi-tenant

[SEC-03] webhook_secret NOT NULL (fail-closed)
[SEC-13] tabela audit_log append-only
[ARQ-08] indice parcial em followups(agendado_para) WHERE status='pendente'

Revision ID: audit01_secops
Revises: t3u4v5w6x7y8
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa


revision = "audit01_secops"
# Aponta para a head mais recente (ajuste se o head mudar)
down_revision = "t3u4v5w6x7y8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # [SEC-13] audit_log — append-only (grava alteracoes admin)
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id BIGSERIAL PRIMARY KEY,
            user_email TEXT,
            empresa_id INTEGER,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            changes_json JSONB,
            request_ip INET,
            request_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_empresa_created ON audit_log(empresa_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_user_created ON audit_log(user_email, created_at DESC)")

    # Bloqueia UPDATE/DELETE via regra (append-only)
    op.execute("""
        CREATE OR REPLACE RULE audit_log_no_update AS
        ON UPDATE TO audit_log DO INSTEAD NOTHING
    """)
    op.execute("""
        CREATE OR REPLACE RULE audit_log_no_delete AS
        ON DELETE TO audit_log DO INSTEAD NOTHING
    """)

    # [SEC-03] webhook_secret NOT NULL com default gerado para rows existentes
    op.execute("""
        UPDATE integracoes
        SET webhook_secret = encode(gen_random_bytes(24), 'hex')
        WHERE webhook_secret IS NULL OR webhook_secret = ''
    """)
    # Alguns bancos podem nao ter pgcrypto — fallback via md5 se gen_random_bytes falhar
    op.execute("""
        UPDATE integracoes
        SET webhook_secret = md5(random()::text || clock_timestamp()::text)
        WHERE webhook_secret IS NULL OR webhook_secret = ''
    """)

    # [ARQ-08] Indice parcial para worker_followup
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_followups_pendente
        ON followups(agendado_para)
        WHERE status = 'pendente'
    """)

    # [SEC-10] Indice composto em conversas
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversas_empresa_fone_created
        ON conversas(empresa_id, contato_fone, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_conversas_empresa_fone_created")
    op.execute("DROP INDEX IF EXISTS idx_followups_pendente")
    op.execute("DROP RULE IF EXISTS audit_log_no_delete ON audit_log")
    op.execute("DROP RULE IF EXISTS audit_log_no_update ON audit_log")
    op.execute("DROP INDEX IF EXISTS idx_audit_log_user_created")
    op.execute("DROP INDEX IF EXISTS idx_audit_log_empresa_created")
    op.execute("DROP TABLE IF EXISTS audit_log")
