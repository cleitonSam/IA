"""
[MKT-06] Webhook de callback dos providers de voice (Vapi e Retell).

Recebe eventos quando a chamada termina:
  - call_ended / call_analysis: duracao, transcript, gravacao, custo
  - call_failed: razao da falha

Atualiza tabela voice_calls e, se o callback trouxer insight comercial (ex: aluno
aceitou voltar, nao atendeu, pediu para ligar depois), pode disparar acoes (criar
follow-up, atualizar score_lead).
"""

from __future__ import annotations

import os
from fastapi import APIRouter, Request, HTTPException

from src.core.config import logger
from src.services.voice_agent import update_call_status
import src.core.database as _database


router = APIRouter()

VOICE_WEBHOOK_SECRET = os.getenv("VOICE_WEBHOOK_SECRET", "").strip()


@router.post("/webhook/voice/{empresa_id}")
async def voice_webhook(empresa_id: int, request: Request):
    """Recebe callback do provider de voice. Valida secret via query ?secret=."""
    secret = request.query_params.get("secret", "")
    if VOICE_WEBHOOK_SECRET and secret != VOICE_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid secret")

    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored", "reason": "invalid_json"}

    # Vapi schema (reliable fields)
    vapi_type = (payload.get("message") or {}).get("type") or payload.get("type")
    vapi_call = (payload.get("message") or {}).get("call") or payload.get("call") or {}
    vapi_analysis = (payload.get("message") or {}).get("analysis") or {}
    vapi_provider_id = vapi_call.get("id")

    # Retell schema
    retell_event = payload.get("event") or payload.get("call_status")
    retell_call = payload.get("call") or payload

    provider_call_id = vapi_provider_id or retell_call.get("call_id")
    if not provider_call_id:
        return {"status": "ignored", "reason": "no_provider_call_id"}

    # Busca a linha correspondente em voice_calls
    if not _database.db_pool:
        return {"status": "no_db"}
    try:
        row = await _database.db_pool.fetchrow(
            "SELECT id FROM voice_calls WHERE empresa_id = $1 AND provider_call_id = $2",
            empresa_id, provider_call_id,
        )
    except Exception as e:
        logger.error(f"[MKT-06] voice_webhook lookup falhou: {e}")
        return {"status": "error"}

    if not row:
        logger.warning(f"[MKT-06] voice_webhook: call nao encontrada id={provider_call_id}")
        return {"status": "not_found"}

    call_id = row["id"]

    # Extrai campos do payload (varia entre providers)
    status = "finalizada"
    duracao = None
    transcript = None
    resultado = None
    custo = None

    if vapi_type == "end-of-call-report" or vapi_type == "call.ended":
        duracao = vapi_call.get("duration")
        transcript = vapi_call.get("transcript") or vapi_call.get("messages_text")
        resultado = vapi_analysis.get("summary") or vapi_call.get("endedReason")
        custo = vapi_call.get("cost") or vapi_call.get("costUsd")
        status = "finalizada" if vapi_call.get("endedReason") not in ("failed", "error") else "falhou"

    elif vapi_type in ("call.failed", "call.no-answer"):
        status = "falhou"
        resultado = vapi_call.get("endedReason") or "no_answer"

    elif retell_event in ("call_ended", "call_analyzed"):
        duracao = retell_call.get("duration_ms", 0) // 1000 if retell_call.get("duration_ms") else None
        transcript = retell_call.get("transcript")
        resultado = (retell_call.get("call_analysis") or {}).get("call_summary")
        custo = retell_call.get("call_cost", {}).get("combined_cost")

    elif retell_event == "call_not_answered":
        status = "falhou"
        resultado = "no_answer"

    await update_call_status(
        call_id, empresa_id,
        status=status,
        duracao_s=int(duracao) if duracao else None,
        transcript=transcript[:10000] if transcript else None,
        resultado=resultado[:500] if resultado else None,
        custo_usd=float(custo) if custo else None,
    )

    logger.info(f"[MKT-06] voice_webhook empresa={empresa_id} call={call_id} status={status}")
    return {"status": "ok"}
