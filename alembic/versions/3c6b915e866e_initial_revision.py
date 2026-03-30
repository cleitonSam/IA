"""Initial revision — baseline schema

Revision ID: 3c6b915e866e
Revises:
Create Date: 2026-03-14 11:51:49.373447

Cria TODAS as tabelas-base do sistema com CREATE TABLE IF NOT EXISTS.
Isso permite que o banco de dados de desenvolvimento (ia_metricas_dev) seja
inicializado do zero e que as migrations subsequentes sejam aplicadas
corretamente, mesmo num banco completamente vazio.

NOTA: as colunas adicionadas pelas migrations posteriores NÃO aparecem aqui —
elas são criadas pelas próprias migrations (que usam ADD COLUMN IF NOT EXISTS).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '3c6b915e866e'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Cria o schema base completo (idempotente via IF NOT EXISTS)."""

    # ── 1. empresas ───────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS empresas (
            id              SERIAL PRIMARY KEY,
            uuid            VARCHAR(36)  UNIQUE,
            nome            VARCHAR(255) NOT NULL,
            nome_fantasia   VARCHAR(255),
            cnpj            VARCHAR(20),
            email           VARCHAR(255),
            telefone        VARCHAR(50),
            website         VARCHAR(255),
            plano           VARCHAR(50)  DEFAULT 'free',
            config          JSONB        DEFAULT '{}',
            status          VARCHAR(20)  DEFAULT 'ativo',
            created_at      TIMESTAMP    DEFAULT NOW(),
            updated_at      TIMESTAMP    DEFAULT NOW()
        )
    """)

    # ── 2. usuarios ───────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id              SERIAL PRIMARY KEY,
            empresa_id      INTEGER REFERENCES empresas(id) ON DELETE CASCADE,
            nome            VARCHAR(255) NOT NULL,
            email           VARCHAR(255) UNIQUE NOT NULL,
            senha_hash      VARCHAR(255),
            perfil          VARCHAR(50)  DEFAULT 'operador',
            ativo           BOOLEAN      DEFAULT true,
            created_at      TIMESTAMP    DEFAULT NOW(),
            updated_at      TIMESTAMP    DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_usuarios_email
        ON usuarios (email)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_usuarios_empresa_id
        ON usuarios (empresa_id)
    """)

    # ── 3. planos ─────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS planos (
            id                  SERIAL PRIMARY KEY,
            empresa_id          INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            id_externo          VARCHAR(100),
            nome                VARCHAR(255) NOT NULL,
            valor               NUMERIC(10,2),
            valor_promocional   NUMERIC(10,2),
            meses_promocionais  INTEGER,
            descricao           TEXT,
            diferenciais        TEXT,
            link_venda          VARCHAR(500),
            ativo               BOOLEAN DEFAULT true,
            ordem               INTEGER DEFAULT 0,
            created_at          TIMESTAMP DEFAULT NOW(),
            updated_at          TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_planos_empresa_id
        ON planos (empresa_id)
    """)

    # ── 4. unidades ───────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS unidades (
            id              SERIAL PRIMARY KEY,
            empresa_id      INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            nome            VARCHAR(255) NOT NULL,
            slug            VARCHAR(100),
            ativa           BOOLEAN DEFAULT true,
            descricao       TEXT,
            servicos        TEXT,
            palavras_chave  TEXT,
            link_matricula  VARCHAR(500),
            site            VARCHAR(500),
            instagram       VARCHAR(255),
            cidade          VARCHAR(100),
            bairro          VARCHAR(100),
            estado          VARCHAR(50),
            telefone        VARCHAR(50),
            whatsapp        VARCHAR(50),
            endereco        TEXT,
            horario         TEXT,
            ordem_exibicao  INTEGER DEFAULT 0,
            created_at      TIMESTAMP DEFAULT NOW(),
            updated_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_unidades_empresa_id
        ON unidades (empresa_id)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_unidades_empresa_slug
        ON unidades (empresa_id, slug)
        WHERE slug IS NOT NULL
    """)

    # ── 5. conversas ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS conversas (
            id                  SERIAL PRIMARY KEY,
            conversation_id     INTEGER,
            account_id          INTEGER,
            contato_id          INTEGER,
            contato_nome        VARCHAR(255),
            empresa_id          INTEGER REFERENCES empresas(id) ON DELETE CASCADE,
            unidade_id          INTEGER REFERENCES unidades(id) ON DELETE SET NULL,
            primeira_mensagem   TIMESTAMP,
            status              VARCHAR(50) DEFAULT 'ativa',
            contato_telefone    VARCHAR(50),
            created_at          TIMESTAMP DEFAULT NOW(),
            updated_at          TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_conversas_empresa_id
        ON conversas (empresa_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_conversas_conversation_id_idx
        ON conversas (conversation_id)
    """)

    # ── 6. mensagens ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mensagens (
            id          SERIAL PRIMARY KEY,
            conversa_id INTEGER NOT NULL REFERENCES conversas(id) ON DELETE CASCADE,
            role        VARCHAR(50)  NOT NULL,
            tipo        VARCHAR(50)  DEFAULT 'texto',
            conteudo    TEXT,
            url_midia   TEXT,
            created_at  TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_mensagens_conversa_id
        ON mensagens (conversa_id)
    """)

    # ── 7. integracoes ────────────────────────────────────────────────────────
    # IMPORTANTE: o nome do constraint deve ser exatamente 'integracoes_empresa_id_tipo_key'
    # pois a migration 89e716bfb81f usa op.drop_constraint com este nome.
    op.execute("""
        CREATE TABLE IF NOT EXISTS integracoes (
            id          SERIAL PRIMARY KEY,
            empresa_id  INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            tipo        VARCHAR(50) NOT NULL,
            config      JSONB DEFAULT '{}',
            ativo       BOOLEAN DEFAULT true,
            created_at  TIMESTAMP DEFAULT NOW(),
            CONSTRAINT integracoes_empresa_id_tipo_key UNIQUE (empresa_id, tipo)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_integracoes_empresa_id
        ON integracoes (empresa_id)
    """)

    # ── 8. personalidade_ia ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS personalidade_ia (
            id                  SERIAL PRIMARY KEY,
            empresa_id          INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            nome_ia             VARCHAR(255),
            personalidade       TEXT,
            instrucoes_base     TEXT,
            tom_voz             VARCHAR(100),
            modelo_preferido    VARCHAR(100) DEFAULT 'gpt-4o-mini',
            temperatura         FLOAT DEFAULT 0.7,
            max_tokens          INTEGER DEFAULT 500,
            ativo               BOOLEAN DEFAULT true,
            created_at          TIMESTAMP DEFAULT NOW(),
            updated_at          TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_personalidade_ia_empresa_id
        ON personalidade_ia (empresa_id)
    """)

    # ── 9. templates_followup ─────────────────────────────────────────────────
    # NOTA: coluna 'nome' é adicionada pela migration 69b8030a
    op.execute("""
        CREATE TABLE IF NOT EXISTS templates_followup (
            id              SERIAL PRIMARY KEY,
            empresa_id      INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            mensagem        TEXT NOT NULL,
            delay_minutos   INTEGER DEFAULT 30,
            ordem           INTEGER DEFAULT 0,
            tipo            VARCHAR(50) DEFAULT 'texto',
            ativo           BOOLEAN DEFAULT true,
            unidade_id      INTEGER REFERENCES unidades(id) ON DELETE CASCADE,
            created_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_templates_followup_empresa_id
        ON templates_followup (empresa_id)
    """)

    # ── 10. followups ─────────────────────────────────────────────────────────
    # NOTA: colunas 'enviado_em' e 'updated_at' são adicionadas pela migration f1a2b3c4d5e6
    op.execute("""
        CREATE TABLE IF NOT EXISTS followups (
            id              SERIAL PRIMARY KEY,
            conversa_id     INTEGER REFERENCES conversas(id) ON DELETE CASCADE,
            empresa_id      INTEGER REFERENCES empresas(id) ON DELETE CASCADE,
            unidade_id      INTEGER REFERENCES unidades(id) ON DELETE SET NULL,
            template_id     INTEGER REFERENCES templates_followup(id) ON DELETE SET NULL,
            tipo            VARCHAR(50) DEFAULT 'texto',
            mensagem        TEXT,
            ordem           INTEGER DEFAULT 0,
            agendado_para   TIMESTAMP,
            status          VARCHAR(50) DEFAULT 'pendente',
            created_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_followups_empresa_id
        ON followups (empresa_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_followups_status
        ON followups (status)
    """)

    # ── 11. faq ───────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS faq (
            id              SERIAL PRIMARY KEY,
            empresa_id      INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            pergunta        TEXT NOT NULL,
            resposta        TEXT NOT NULL,
            unidade_id      INTEGER REFERENCES unidades(id) ON DELETE CASCADE,
            todas_unidades  BOOLEAN DEFAULT false,
            prioridade      INTEGER DEFAULT 0,
            ativo           BOOLEAN DEFAULT true,
            created_at      TIMESTAMP DEFAULT NOW(),
            updated_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_faq_empresa_id
        ON faq (empresa_id)
    """)

    # ── 12. metricas_diarias ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS metricas_diarias (
            id                              SERIAL PRIMARY KEY,
            empresa_id                      INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            unidade_id                      INTEGER REFERENCES unidades(id) ON DELETE CASCADE,
            data                            DATE NOT NULL,
            total_conversas                 INTEGER DEFAULT 0,
            conversas_encerradas            INTEGER DEFAULT 0,
            conversas_sem_resposta          INTEGER DEFAULT 0,
            novos_contatos                  INTEGER DEFAULT 0,
            total_mensagens                 INTEGER DEFAULT 0,
            total_mensagens_ia              INTEGER DEFAULT 0,
            leads_qualificados              INTEGER DEFAULT 0,
            taxa_conversao                  FLOAT DEFAULT 0,
            tempo_medio_resposta            FLOAT DEFAULT 0,
            total_solicitacoes_telefone     INTEGER DEFAULT 0,
            total_links_enviados            INTEGER DEFAULT 0,
            total_planos_enviados           INTEGER DEFAULT 0,
            total_matriculas                INTEGER DEFAULT 0,
            pico_hora                       INTEGER,
            satisfacao_media                FLOAT,
            updated_at                      TIMESTAMP DEFAULT NOW(),
            CONSTRAINT metricas_diarias_empresa_unidade_data_key
                UNIQUE (empresa_id, unidade_id, data)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_metricas_diarias_empresa_data
        ON metricas_diarias (empresa_id, data DESC)
    """)

    # ── 13. cache_respostas ───────────────────────────────────────────────────
    # Esta tabela é REMOVIDA pela migration 41c67487b635.
    # Precisa existir para que essa migration consiga fazer DROP TABLE.
    op.execute("""
        CREATE TABLE IF NOT EXISTS cache_respostas (
            id                  SERIAL PRIMARY KEY,
            empresa_id          INTEGER,
            unidade_id          INTEGER,
            hash_pergunta       VARCHAR,
            pergunta_original   TEXT,
            resposta            TEXT,
            modelo_utilizado    VARCHAR,
            tokens_utilizados   INTEGER,
            vezes_utilizado     INTEGER DEFAULT 1,
            ultimo_uso          TIMESTAMP,
            expires_at          TIMESTAMP,
            created_at          TIMESTAMP DEFAULT NOW()
        )
    """)


def downgrade() -> None:
    """Remove todas as tabelas-base (cuidado: destrói todos os dados)."""
    op.execute("DROP TABLE IF EXISTS cache_respostas CASCADE")
    op.execute("DROP TABLE IF EXISTS metricas_diarias CASCADE")
    op.execute("DROP TABLE IF EXISTS faq CASCADE")
    op.execute("DROP TABLE IF EXISTS followups CASCADE")
    op.execute("DROP TABLE IF EXISTS templates_followup CASCADE")
    op.execute("DROP TABLE IF EXISTS personalidade_ia CASCADE")
    op.execute("DROP TABLE IF EXISTS integracoes CASCADE")
    op.execute("DROP TABLE IF EXISTS mensagens CASCADE")
    op.execute("DROP TABLE IF EXISTS conversas CASCADE")
    op.execute("DROP TABLE IF EXISTS unidades CASCADE")
    op.execute("DROP TABLE IF EXISTS planos CASCADE")
    op.execute("DROP TABLE IF EXISTS usuarios CASCADE")
    op.execute("DROP TABLE IF EXISTS empresas CASCADE")
