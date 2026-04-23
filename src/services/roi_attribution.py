"""
[MKT-07] Atribuicao de ROI — quanto receita o bot realmente gerou.

Modelo de atribuicao:
  1. Cada conversa que cumpre criterios de "lead qualificado pelo bot" vira um
     evento roi_events(tipo='lead_qualificado').
  2. Quando a academia marca o aluno como matriculado (via webhook ou API do ERP,
     ou manualmente no dashboard), gravamos roi_events(tipo='matricula') com
     lookback: se o cliente foi qualificado pelo bot nos ultimos N dias, atribui.
  3. Se o plano tem mensalidade mensal, gravamos receita recorrente estimada.

Dashboard retorna:
  - Leads qualificados pelo bot (periodo)
  - Matriculas atribuidas (lookback 30 dias default)
  - Receita estimada (soma das mensalidades de alunos atribuidos)
  - ROI = receita / custo_do_bot (custo_do_bot = plano da empresa + custo LLM)

Uso:
    from src.services.roi_attribution import (
        record_lead_qualificado, record_matricula, compute_roi
    )

    await record_lead_qualificado(empresa_id, conversation_id, contato_fone, score=84)
    await record_matricula(empresa_id, contato_fone, plano="Mensal", valor_mensal=149.90)
    roi = await compute_roi(empresa_id, periodo_dias=30)
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

from src.core.config import logger
import src.core.database as _database


LOOKBACK_DIAS_DEFAULT = 30


async def record_lead_qualificado(
    empresa_id: int,
    conversation_id: int,
    contato_fone: str,
    score: int = 0,
    origem: str = "bot",
) -> bool:
    """Grava que o bot qualificou o lead. Idempotente por (empresa_id, conversation_id)."""
    if not _database.db_pool:
        return False
    try:
        await _database.db_pool.execute(
            """
            INSERT INTO roi_events
                (empresa_id, tipo, contato_fone, conversation_id, score, origem, valor_brl)
            VALUES ($1, 'lead_qualificado', $2, $3, $4, $5, 0)
            ON CONFLICT (empresa_id, tipo, conversation_id) DO UPDATE
                SET score = GREATEST(roi_events.score, EXCLUDED.score),
                    updated_at = NOW()
            """,
            empresa_id, contato_fone, conversation_id, score, origem,
        )
        return True
    except Exception as e:
        logger.error(f"[MKT-07] record_lead_qualificado falhou: {e}")
        return False


async def record_matricula(
    empresa_id: int,
    contato_fone: str,
    plano: Optional[str] = None,
    valor_mensal: float = 0.0,
    lookback_dias: int = LOOKBACK_DIAS_DEFAULT,
) -> Dict:
    """Grava evento de matricula. Se o cliente foi qualificado pelo bot nos
    ultimos `lookback_dias`, atribui ao bot e anota no evento."""
    if not _database.db_pool:
        return {"atribuido": False, "motivo": "no_db"}

    try:
        # Busca evento de qualificacao recente
        lead_event = await _database.db_pool.fetchrow(
            """
            SELECT id, conversation_id, score, created_at
            FROM roi_events
            WHERE empresa_id = $1 AND tipo = 'lead_qualificado'
              AND contato_fone = $2
              AND created_at > NOW() - ($3 || ' days')::interval
            ORDER BY created_at DESC
            LIMIT 1
            """,
            empresa_id, contato_fone, str(lookback_dias),
        )

        atribuido = bool(lead_event)
        valor_brl = max(0.0, float(valor_mensal or 0.0))

        await _database.db_pool.execute(
            """
            INSERT INTO roi_events
                (empresa_id, tipo, contato_fone, conversation_id, score, origem, valor_brl, plano, atribuido_bot)
            VALUES ($1, 'matricula', $2, $3, $4, $5, $6, $7, $8)
            """,
            empresa_id,
            contato_fone,
            lead_event["conversation_id"] if lead_event else None,
            lead_event["score"] if lead_event else 0,
            "bot" if atribuido else "outro",
            valor_brl,
            plano,
            atribuido,
        )

        logger.info(
            f"[MKT-07] matricula empresa={empresa_id} fone={contato_fone} "
            f"atribuido={atribuido} valor={valor_brl}"
        )
        return {
            "atribuido": atribuido,
            "valor_brl": valor_brl,
            "lead_event_id": lead_event["id"] if lead_event else None,
        }
    except Exception as e:
        logger.error(f"[MKT-07] record_matricula falhou: {e}")
        return {"atribuido": False, "erro": str(e)}


async def compute_roi(
    empresa_id: int,
    periodo_dias: int = 30,
    custo_mensal_bot_brl: float = 0.0,
) -> Dict:
    """Computa ROI do bot para o periodo. Se custo_mensal_bot_brl for 0, nao calcula ratio."""
    if not _database.db_pool:
        return {"error": "no_db"}

    try:
        # Leads qualificados
        leads = await _database.db_pool.fetchval(
            """
            SELECT COUNT(*) FROM roi_events
            WHERE empresa_id = $1 AND tipo = 'lead_qualificado'
              AND created_at > NOW() - ($2 || ' days')::interval
            """,
            empresa_id, str(periodo_dias),
        )

        # Matriculas atribuidas + receita
        row_matric = await _database.db_pool.fetchrow(
            """
            SELECT
                COUNT(*) AS total_matriculas,
                SUM(CASE WHEN atribuido_bot THEN 1 ELSE 0 END) AS matriculas_bot,
                SUM(CASE WHEN atribuido_bot THEN COALESCE(valor_brl, 0) ELSE 0 END) AS receita_bot_brl,
                SUM(COALESCE(valor_brl, 0)) AS receita_total_brl
            FROM roi_events
            WHERE empresa_id = $1 AND tipo = 'matricula'
              AND created_at > NOW() - ($2 || ' days')::interval
            """,
            empresa_id, str(periodo_dias),
        )

        matriculas_bot = int(row_matric["matriculas_bot"] or 0)
        receita_bot = float(row_matric["receita_bot_brl"] or 0)
        receita_total = float(row_matric["receita_total_brl"] or 0)

        ratio = None
        if custo_mensal_bot_brl > 0:
            # Proporcional ao periodo
            custo_no_periodo = custo_mensal_bot_brl * (periodo_dias / 30.0)
            ratio = round(receita_bot / custo_no_periodo, 2) if custo_no_periodo else None

        conv_lead_to_matricula = None
        if leads:
            conv_lead_to_matricula = round(100.0 * matriculas_bot / leads, 2)

        return {
            "periodo_dias": periodo_dias,
            "leads_qualificados": int(leads or 0),
            "matriculas_total": int(row_matric["total_matriculas"] or 0),
            "matriculas_atribuidas_bot": matriculas_bot,
            "receita_atribuida_brl": receita_bot,
            "receita_total_brl": receita_total,
            "custo_bot_no_periodo_brl": round(custo_mensal_bot_brl * (periodo_dias / 30.0), 2) if custo_mensal_bot_brl else 0,
            "roi_ratio": ratio,
            "taxa_conversao_lead_matricula_pct": conv_lead_to_matricula,
        }
    except Exception as e:
        logger.error(f"[MKT-07] compute_roi falhou: {e}")
        return {"error": str(e)}
