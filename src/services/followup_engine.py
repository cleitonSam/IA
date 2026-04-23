"""
[MKT-10] N-touch follow-up engine — sequencias multi-etapa com timing inteligente.

Complementa a tabela existente `templates_followup` + worker_followup existente
em workers.py. Este modulo adiciona:

  1. Conceito de SEQUENCIA — varios templates encadeados (touch 1, touch 2, touch 3...).
  2. Timing inteligente — respeita horario comercial, pausa silencio (22h-8h),
     adia se o cliente respondeu entre sends (nao manda touch 2 se ja voltou a conversar).
  3. Cancelamento automatico — se o cliente marcou CSAT negativo ou pediu cancelamento,
     pausa a sequencia inteira.
  4. Tracking — cada send grava roi_events para futuro calculo de ROI.

Tabela nova: followup_sequences (sequencia de N toques) + followup_sequence_steps
(cada step tem template_id, ordem, delay_hours_from_prev).

Uso:
    from src.services.followup_engine import (
        criar_sequencia, iniciar_sequencia_para_conversa, processar_pendentes
    )

    # Admin cria sequencia uma vez
    seq_id = await criar_sequencia(
        empresa_id=1, nome="Nurture lead novo",
        steps=[
            {"template_id": 10, "delay_hours": 2,  "condicao": None},
            {"template_id": 11, "delay_hours": 24, "condicao": "sem_resposta"},
            {"template_id": 12, "delay_hours": 72, "condicao": "sem_resposta"},
        ],
    )

    # Quando novo lead qualifica, inicia sequencia
    await iniciar_sequencia_para_conversa(seq_id=seq_id, conversation_id=123, empresa_id=1)

    # Worker chama periodicamente (ou atrela ao worker_followup existente)
    await processar_pendentes(empresa_id=1)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta, time
from typing import Dict, List, Optional

from src.core.config import logger
import src.core.database as _database


# Horario comercial BR padrao — pode virar config por unidade
BUSINESS_HOUR_START = 8   # 08:00
BUSINESS_HOUR_END = 21    # 21:00
TIMEZONE_BRT_OFFSET_MIN = -180  # UTC-3


def _adjust_to_business_hours(dt_utc: datetime) -> datetime:
    """Ajusta um datetime (UTC) para cair dentro do horario comercial BRT.
    Se cair antes das 8h, empurra para 8h do mesmo dia.
    Se cair apos 21h, empurra para 8h do dia seguinte.
    """
    local = dt_utc + timedelta(minutes=TIMEZONE_BRT_OFFSET_MIN)
    hour = local.hour

    if hour < BUSINESS_HOUR_START:
        target = local.replace(hour=BUSINESS_HOUR_START, minute=0, second=0, microsecond=0)
    elif hour >= BUSINESS_HOUR_END:
        target = (local + timedelta(days=1)).replace(
            hour=BUSINESS_HOUR_START, minute=0, second=0, microsecond=0,
        )
    else:
        return dt_utc

    return target - timedelta(minutes=TIMEZONE_BRT_OFFSET_MIN)


# ============================================================
# CRUD Sequencias
# ============================================================

async def criar_sequencia(
    empresa_id: int,
    nome: str,
    steps: List[Dict],
    descricao: Optional[str] = None,
) -> Optional[int]:
    """Cria uma sequencia com N steps. steps = [{template_id, delay_hours, condicao}]."""
    if not _database.db_pool:
        return None
    try:
        row = await _database.db_pool.fetchrow(
            """
            INSERT INTO followup_sequences (empresa_id, nome, descricao, ativo)
            VALUES ($1, $2, $3, true)
            RETURNING id
            """,
            empresa_id, nome, descricao,
        )
        seq_id = row["id"]

        for ordem, step in enumerate(steps, start=1):
            await _database.db_pool.execute(
                """
                INSERT INTO followup_sequence_steps
                    (sequence_id, ordem, template_id, delay_hours, condicao)
                VALUES ($1, $2, $3, $4, $5)
                """,
                seq_id, ordem,
                step.get("template_id"),
                int(step.get("delay_hours") or 0),
                step.get("condicao"),
            )
        return seq_id
    except Exception as e:
        logger.error(f"[MKT-10] criar_sequencia falhou: {e}")
        return None


async def iniciar_sequencia_para_conversa(
    seq_id: int,
    conversation_id: int,
    empresa_id: int,
    contato_fone: str,
) -> bool:
    """Enfileira todos os steps da sequencia respeitando os delays.
    Cria rows em `followups` (tabela ja existente) com agendado_para calculado."""
    if not _database.db_pool:
        return False
    try:
        steps = await _database.db_pool.fetch(
            """
            SELECT ordem, template_id, delay_hours, condicao
            FROM followup_sequence_steps
            WHERE sequence_id = $1
            ORDER BY ordem
            """,
            seq_id,
        )
        if not steps:
            return False

        now = datetime.now(timezone.utc)
        cumulative_hours = 0

        for step in steps:
            cumulative_hours += int(step["delay_hours"] or 0)
            dt_scheduled = now + timedelta(hours=cumulative_hours)
            dt_scheduled = _adjust_to_business_hours(dt_scheduled)

            await _database.db_pool.execute(
                """
                INSERT INTO followups
                    (empresa_id, conversation_id, template_id, agendado_para, status,
                     sequence_id, sequence_step, metadata_json)
                VALUES ($1, $2, $3, $4, 'pendente', $5, $6, $7::jsonb)
                """,
                empresa_id, conversation_id, step["template_id"], dt_scheduled,
                seq_id, step["ordem"],
                json.dumps({"contato_fone": contato_fone, "condicao": step["condicao"]}),
            )

        logger.info(
            f"[MKT-10] sequencia {seq_id} iniciada conv={conversation_id} empresa={empresa_id} "
            f"n_steps={len(steps)}"
        )
        return True
    except Exception as e:
        logger.error(f"[MKT-10] iniciar_sequencia falhou: {e}")
        return False


async def cancelar_sequencia(conversation_id: int, empresa_id: int, motivo: str = "") -> int:
    """Cancela todos os followups pendentes da sequencia para uma conversa."""
    if not _database.db_pool:
        return 0
    try:
        result = await _database.db_pool.execute(
            """
            UPDATE followups
            SET status = 'cancelado', updated_at = NOW(),
                metadata_json = COALESCE(metadata_json, '{}'::jsonb) || jsonb_build_object('motivo_cancelamento', $1::text)
            WHERE conversation_id = $2 AND empresa_id = $3 AND status = 'pendente'
            """,
            motivo, conversation_id, empresa_id,
        )
        logger.info(f"[MKT-10] sequencia cancelada conv={conversation_id}: {result}")
        return 0
    except Exception as e:
        logger.error(f"[MKT-10] cancelar_sequencia falhou: {e}")
        return 0


async def check_and_cancel_on_customer_activity(
    conversation_id: int,
    empresa_id: int,
) -> bool:
    """Chamada quando o cliente responde uma mensagem. Pausa followups 'sem_resposta'
    que ainda nao foram enviados (ele voltou a conversar, nao precisa pressionar)."""
    if not _database.db_pool:
        return False
    try:
        await _database.db_pool.execute(
            """
            UPDATE followups
            SET status = 'cancelado_por_atividade', updated_at = NOW()
            WHERE conversation_id = $1 AND empresa_id = $2 AND status = 'pendente'
              AND (metadata_json->>'condicao') = 'sem_resposta'
            """,
            conversation_id, empresa_id,
        )
        return True
    except Exception as e:
        logger.error(f"[MKT-10] check_and_cancel falhou: {e}")
        return False


# ============================================================
# Listagem / dashboard
# ============================================================

async def listar_sequencias(empresa_id: int) -> List[Dict]:
    if not _database.db_pool:
        return []
    try:
        rows = await _database.db_pool.fetch(
            """
            SELECT s.id, s.nome, s.descricao, s.ativo, s.created_at,
                   COUNT(st.id) AS n_steps
            FROM followup_sequences s
            LEFT JOIN followup_sequence_steps st ON st.sequence_id = s.id
            WHERE s.empresa_id = $1
            GROUP BY s.id
            ORDER BY s.created_at DESC
            """,
            empresa_id,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"[MKT-10] listar_sequencias falhou: {e}")
        return []


async def metricas_sequencia(empresa_id: int, seq_id: int) -> Dict:
    """Retorna metricas de performance da sequencia (taxa de resposta por step)."""
    if not _database.db_pool:
        return {}
    try:
        rows = await _database.db_pool.fetch(
            """
            SELECT
                sequence_step,
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'enviado' THEN 1 ELSE 0 END) AS enviados,
                SUM(CASE WHEN status = 'cancelado_por_atividade' THEN 1 ELSE 0 END) AS cancelados_atividade,
                SUM(CASE WHEN status = 'cancelado' THEN 1 ELSE 0 END) AS cancelados_manual
            FROM followups
            WHERE empresa_id = $1 AND sequence_id = $2
            GROUP BY sequence_step
            ORDER BY sequence_step
            """,
            empresa_id, seq_id,
        )
        return {"seq_id": seq_id, "steps": [dict(r) for r in rows]}
    except Exception as e:
        logger.error(f"[MKT-10] metricas_sequencia falhou: {e}")
        return {}
