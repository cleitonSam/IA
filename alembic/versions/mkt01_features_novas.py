"""MKT features: alertas_escalacao, voice_calls, roi_events, followup_sequences

[MKT-02] alertas_escalacao
[MKT-06] voice_calls
[MKT-07] roi_events
[MKT-10] followup_sequences + followup_sequence_steps + colunas extras em followups

Revision ID: mkt01_features
Revises: audit01_secops
Create Date: 2026-04-23
"""
from alembic import op


revision = "mkt01_features"
down_revision = "audit01_secops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── [MKT-02] alertas_escalacao ───────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS alertas_escalacao (
            id              BIGSERIAL PRIMARY KEY,
            empresa_id      INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            conversation_id INTEGER,
            tipo            VARCHAR(50) NOT NULL,
            severidade      VARCHAR(20) NOT NULL DEFAULT 'media',
            mensagem        TEXT,
            contexto_json   JSONB,
            status          VARCHAR(20) NOT NULL DEFAULT 'aberto',
            resolvido_por   TEXT,
            resolvido_em    TIMESTAMPTZ,
            observacao      TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_alertas_empresa_status
        ON alertas_escalacao (empresa_id, status, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_alertas_conv
        ON alertas_escalacao (conversation_id, created_at DESC)
    """)

    # ── [MKT-06] voice_calls ─────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS voice_calls (
            id                 BIGSERIAL PRIMARY KEY,
            empresa_id         INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            provider           VARCHAR(30) NOT NULL,
            provider_call_id   TEXT,
            contato_fone       VARCHAR(30) NOT NULL,
            motivo             VARCHAR(50) DEFAULT 'outbound',
            status             VARCHAR(30) NOT NULL DEFAULT 'iniciada',
            duracao_s          INTEGER,
            transcript         TEXT,
            resultado          TEXT,
            custo_usd          NUMERIC(10,4),
            metadata_json      JSONB,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_voice_calls_empresa_created
        ON voice_calls (empresa_id, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_voice_calls_provider_id
        ON voice_calls (provider, provider_call_id)
    """)

    # ── [MKT-07] roi_events ──────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS roi_events (
            id                BIGSERIAL PRIMARY KEY,
            empresa_id        INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            tipo              VARCHAR(40) NOT NULL,
            contato_fone      VARCHAR(30),
            conversation_id   INTEGER,
            score             INTEGER DEFAULT 0,
            origem            VARCHAR(30),
            valor_brl         NUMERIC(12,2) DEFAULT 0,
            plano             VARCHAR(100),
            atribuido_bot     BOOLEAN DEFAULT false,
            metadata_json     JSONB,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_roi_lead_por_conversa
        ON roi_events (empresa_id, tipo, conversation_id)
        WHERE tipo = 'lead_qualificado' AND conversation_id IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_roi_empresa_tipo_created
        ON roi_events (empresa_id, tipo, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_roi_fone_created
        ON roi_events (contato_fone, created_at DESC)
    """)

    # ── [MKT-10] followup_sequences ──────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS followup_sequences (
            id          SERIAL PRIMARY KEY,
            empresa_id  INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            nome        VARCHAR(200) NOT NULL,
            descricao   TEXT,
            ativo       BOOLEAN NOT NULL DEFAULT true,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_fseq_empresa
        ON followup_sequences (empresa_id, ativo)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS followup_sequence_steps (
            id            SERIAL PRIMARY KEY,
            sequence_id   INTEGER NOT NULL REFERENCES followup_sequences(id) ON DELETE CASCADE,
            ordem         INTEGER NOT NULL,
            template_id   INTEGER,
            delay_hours   INTEGER NOT NULL DEFAULT 24,
            condicao      VARCHAR(50),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_fseq_steps_seq
        ON followup_sequence_steps (sequence_id, ordem)
    """)

    # ── Colunas extras em followups ──────────────────────────────────────
    op.execute("ALTER TABLE followups ADD COLUMN IF NOT EXISTS sequence_id INTEGER REFERENCES followup_sequences(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE followups ADD COLUMN IF NOT EXISTS sequence_step INTEGER")
    op.execute("ALTER TABLE followups ADD COLUMN IF NOT EXISTS metadata_json JSONB")
    op.execute("CREATE INDEX IF NOT EXISTS idx_followups_sequence ON followups (sequence_id, sequence_step)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_followups_sequence")
    op.execute("ALTER TABLE followups DROP COLUMN IF EXISTS metadata_json")
    op.execute("ALTER TABLE followups DROP COLUMN IF EXISTS sequence_step")
    op.execute("ALTER TABLE followups DROP COLUMN IF EXISTS sequence_id")
    op.execute("DROP TABLE IF EXISTS followup_sequence_steps")
    op.execute("DROP TABLE IF EXISTS followup_sequences")
    op.execute("DROP INDEX IF EXISTS idx_roi_fone_created")
    op.execute("DROP INDEX IF EXISTS idx_roi_empresa_tipo_created")
    op.execute("DROP INDEX IF EXISTS uq_roi_lead_por_conversa")
    op.execute("DROP TABLE IF EXISTS roi_events")
    op.execute("DROP INDEX IF EXISTS idx_voice_calls_provider_id")
    op.execute("DROP INDEX IF EXISTS idx_voice_calls_empresa_created")
    op.execute("DROP TABLE IF EXISTS voice_calls")
    op.execute("DROP INDEX IF EXISTS idx_alertas_conv")
    op.execute("DROP INDEX IF EXISTS idx_alertas_empresa_status")
    op.execute("DROP TABLE IF EXISTS alertas_escalacao")
