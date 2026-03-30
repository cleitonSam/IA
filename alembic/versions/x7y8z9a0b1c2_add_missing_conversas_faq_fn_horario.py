"""add missing conversas/faq columns and fn_ia_esta_no_horario_v2

Revision ID: x7y8z9a0b1c2
Revises: w6x7y8z9a0b1
Create Date: 2026-03-29

Corrige três erros críticos que travavam o uvicorn:

1. `column "total_mensagens_cliente" does not exist` — tabela conversas foi criada
   sem várias colunas usadas por db_queries.py e main.py. Adiciona:
     total_mensagens_cliente, total_mensagens_ia, ultima_mensagem, canal,
     resumo_ia, lead_qualificado, intencao_de_compra, score_lead, contato_fone.

2. `column f.unidades_ids does not exist` — CRASH CRÍTICO. carregar_faq_unidade
   usa unidades_ids em AMBAS as queries (principal e fallback). Um UndefinedColumnError
   em background task sobe até o uvicorn e derruba o processo. Adiciona:
     unidades_ids INTEGER[], visualizacoes INTEGER DEFAULT 0.

3. `function fn_ia_esta_no_horario_v2(jsonb) does not exist` — chamada em
   carregar_personalidade() para checar horário de atendimento da IA. Cria a
   função equivalente à ia_esta_no_horario() em src/utils/time_helpers.py:
     - NULL / tipo='dia_todo'  → TRUE (sempre ativo)
     - Verifica períodos do dia atual no fuso America/Sao_Paulo
     - dias: {"segunda"|"terca"|"quarta"|"quinta"|"sexta"|"sabado"|"domingo":
              [{"inicio": "HH:MM", "fim": "HH:MM"}, ...]}
     - "fim" 00:00 é tratado como 23:59:59 (fim do dia)
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'x7y8z9a0b1c2'
down_revision: Union[str, Sequence[str], None] = 'w6x7y8z9a0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Colunas faltantes em `conversas` ───────────────────────────────────
    op.execute("ALTER TABLE conversas ADD COLUMN IF NOT EXISTS total_mensagens_cliente INTEGER DEFAULT 0")
    op.execute("ALTER TABLE conversas ADD COLUMN IF NOT EXISTS total_mensagens_ia      INTEGER DEFAULT 0")
    op.execute("ALTER TABLE conversas ADD COLUMN IF NOT EXISTS ultima_mensagem         TIMESTAMP")
    op.execute("ALTER TABLE conversas ADD COLUMN IF NOT EXISTS canal                   VARCHAR(50)")
    op.execute("ALTER TABLE conversas ADD COLUMN IF NOT EXISTS resumo_ia               TEXT")
    op.execute("ALTER TABLE conversas ADD COLUMN IF NOT EXISTS lead_qualificado        BOOLEAN DEFAULT false")
    op.execute("ALTER TABLE conversas ADD COLUMN IF NOT EXISTS intencao_de_compra      BOOLEAN DEFAULT false")
    op.execute("ALTER TABLE conversas ADD COLUMN IF NOT EXISTS score_lead              INTEGER DEFAULT 0")
    # contato_fone: usado em INSERT/UPDATE mas inicial só tinha contato_telefone
    op.execute("ALTER TABLE conversas ADD COLUMN IF NOT EXISTS contato_fone            VARCHAR(50)")

    # ── 2. Colunas faltantes em `faq` ─────────────────────────────────────────
    op.execute("ALTER TABLE faq ADD COLUMN IF NOT EXISTS unidades_ids INTEGER[]")
    op.execute("ALTER TABLE faq ADD COLUMN IF NOT EXISTS visualizacoes INTEGER DEFAULT 0")

    # ── 3. Função fn_ia_esta_no_horario_v2(JSONB) ─────────────────────────────
    #
    # Espelha exatamente a lógica de ia_esta_no_horario() em
    # src/utils/time_helpers.py, mas executada dentro do PostgreSQL para que a
    # query em carregar_personalidade() funcione sem round-trip extra.
    #
    # Estrutura esperada do parâmetro `config`:
    # {
    #   "tipo": "dia_todo" | "horario",
    #   "dias": {
    #     "segunda": [{"inicio": "08:00", "fim": "18:00"}],
    #     "terca":   [...],
    #     ...
    #   }
    # }
    # DROP antes de CREATE OR REPLACE pois o PostgreSQL não permite mudar o
    # nome do parâmetro de uma função existente (erro InvalidFunctionDefinition)
    op.execute("DROP FUNCTION IF EXISTS fn_ia_esta_no_horario_v2(JSONB)")
    op.execute("""
        CREATE OR REPLACE FUNCTION fn_ia_esta_no_horario_v2(config JSONB)
        RETURNS BOOLEAN
        LANGUAGE plpgsql
        STABLE
        AS $func$
        DECLARE
            v_tipo      TEXT;
            v_dia_key   TEXT;
            v_periodos  JSONB;
            v_periodo   JSONB;
            v_h_ini     INT;
            v_m_ini     INT;
            v_h_fim     INT;
            v_m_fim     INT;
            v_t_ini     TIME;
            v_t_fim     TIME;
            v_hora_atual TIME;
            v_agora     TIMESTAMPTZ;
        BEGIN
            -- Config nula ou vazia → sempre ativo
            IF config IS NULL OR config = 'null'::jsonb OR config = '{}'::jsonb THEN
                RETURN TRUE;
            END IF;

            v_tipo := config->>'tipo';
            IF v_tipo IS NULL OR v_tipo = 'dia_todo' THEN
                RETURN TRUE;
            END IF;

            -- Horário atual no fuso de São Paulo
            v_agora      := NOW() AT TIME ZONE 'America/Sao_Paulo';
            v_hora_atual := v_agora::TIME;

            -- Chave do dia da semana em PT-BR (0=domingo na função DOW do PG)
            v_dia_key := CASE EXTRACT(DOW FROM v_agora)
                WHEN 1 THEN 'segunda'
                WHEN 2 THEN 'terca'
                WHEN 3 THEN 'quarta'
                WHEN 4 THEN 'quinta'
                WHEN 5 THEN 'sexta'
                WHEN 6 THEN 'sabado'
                WHEN 0 THEN 'domingo'
            END;

            v_periodos := config->'dias'->v_dia_key;

            -- Sem períodos configurados para hoje → fora do horário
            IF v_periodos IS NULL OR jsonb_array_length(v_periodos) = 0 THEN
                RETURN FALSE;
            END IF;

            FOR v_periodo IN SELECT * FROM jsonb_array_elements(v_periodos)
            LOOP
                BEGIN
                    v_h_ini := split_part(v_periodo->>'inicio', ':', 1)::INT;
                    v_m_ini := split_part(v_periodo->>'inicio', ':', 2)::INT;
                    v_h_fim := split_part(v_periodo->>'fim',    ':', 1)::INT;
                    v_m_fim := split_part(v_periodo->>'fim',    ':', 2)::INT;

                    v_t_ini := make_time(v_h_ini, v_m_ini, 0);

                    -- "fim" 00:00 → fim do dia (23:59:59)
                    IF v_h_fim = 0 AND v_m_fim = 0 THEN
                        IF v_t_ini <= v_hora_atual AND v_hora_atual <= '23:59:59'::TIME THEN
                            RETURN TRUE;
                        END IF;
                    ELSE
                        v_t_fim := make_time(v_h_fim, v_m_fim, 0);
                        -- Período inválido (inicio >= fim) → ignora
                        IF v_t_ini >= v_t_fim THEN
                            CONTINUE;
                        END IF;
                        IF v_t_ini <= v_hora_atual AND v_hora_atual < v_t_fim THEN
                            RETURN TRUE;
                        END IF;
                    END IF;
                EXCEPTION WHEN OTHERS THEN
                    CONTINUE;
                END;
            END LOOP;

            RETURN FALSE;
        END;
        $func$;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS fn_ia_esta_no_horario_v2(JSONB)")
    op.execute("ALTER TABLE faq DROP COLUMN IF EXISTS visualizacoes")
    op.execute("ALTER TABLE faq DROP COLUMN IF EXISTS unidades_ids")
    for col in [
        'contato_fone', 'score_lead', 'intencao_de_compra', 'lead_qualificado',
        'resumo_ia', 'canal', 'ultima_mensagem',
        'total_mensagens_ia', 'total_mensagens_cliente',
    ]:
        op.execute(f"ALTER TABLE conversas DROP COLUMN IF EXISTS {col}")
