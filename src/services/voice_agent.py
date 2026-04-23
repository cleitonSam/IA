"""
[MKT-06] Voice agent — chamadas telefonicas automatizadas via Vapi ou Retell.

Casos de uso:
  1. Recuperacao de aluno inativo ("oi, vi que voce nao veio nas ultimas 2 semanas...")
  2. Confirmacao de avaliacao fisica ("oi, confirmando sua avaliacao amanha 18h")
  3. Cold outbound para lead que deu telefone mas nao respondeu no WA
  4. Follow-up de matricula pendente

Providers suportados:
  - Vapi (recomendado) — orquestra LLM + TTS + telefonia; cobra US$ ~0.05/min
  - Retell (enterprise) — compliance heavy; cobra US$ ~0.07/min

Envs necessarias:
  VOICE_PROVIDER             vapi|retell|disabled (default: disabled)
  VAPI_API_KEY               chave da API Vapi
  VAPI_ASSISTANT_ID          ID do assistant criado na Vapi (default)
  VAPI_PHONE_NUMBER_ID       ID do numero Vapi que vai originar as chamadas
  RETELL_API_KEY             chave Retell
  RETELL_AGENT_ID            ID do agent

Uso:
    from src.services.voice_agent import schedule_outbound_call

    call_id = await schedule_outbound_call(
        empresa_id=1,
        contato_fone="+5511999999999",
        script_prompt="Voce e a Laura, SDR da Academia Fluxo. Ligue para confirmar...",
        metadata={"motivo": "recuperacao_inativo", "conversation_id": 123},
    )

Webhook de callback: POST /webhook/voice/{empresa_id} (ver voice_webhook.py)
"""

from __future__ import annotations

import os
from typing import Dict, Optional

import httpx

from src.core.config import logger
import src.core.database as _database


VOICE_PROVIDER = os.getenv("VOICE_PROVIDER", "disabled").lower().strip()

# Vapi
VAPI_API_KEY = os.getenv("VAPI_API_KEY", "").strip()
VAPI_ASSISTANT_ID = os.getenv("VAPI_ASSISTANT_ID", "").strip()
VAPI_PHONE_NUMBER_ID = os.getenv("VAPI_PHONE_NUMBER_ID", "").strip()
VAPI_BASE = "https://api.vapi.ai"

# Retell
RETELL_API_KEY = os.getenv("RETELL_API_KEY", "").strip()
RETELL_AGENT_ID = os.getenv("RETELL_AGENT_ID", "").strip()
RETELL_PHONE_NUMBER = os.getenv("RETELL_PHONE_NUMBER", "").strip()
RETELL_BASE = "https://api.retellai.com"


# ============================================================
# Persistencia
# ============================================================

async def _create_call_row(
    empresa_id: int,
    provider: str,
    contato_fone: str,
    motivo: str,
    metadata: Dict,
) -> Optional[int]:
    if not _database.db_pool:
        return None
    try:
        row = await _database.db_pool.fetchrow(
            """
            INSERT INTO voice_calls
                (empresa_id, provider, contato_fone, motivo, status, metadata_json)
            VALUES ($1, $2, $3, $4, 'iniciada', $5::jsonb)
            RETURNING id
            """,
            empresa_id, provider, contato_fone, motivo,
            __import__("json").dumps(metadata or {}),
        )
        return row["id"] if row else None
    except Exception as e:
        logger.error(f"[MKT-06] create_call_row falhou: {e}")
        return None


async def update_call_status(
    call_id: int,
    empresa_id: int,
    status: str,
    duracao_s: Optional[int] = None,
    transcript: Optional[str] = None,
    resultado: Optional[str] = None,
    custo_usd: Optional[float] = None,
) -> bool:
    if not _database.db_pool:
        return False
    try:
        await _database.db_pool.execute(
            """
            UPDATE voice_calls
            SET status = $1,
                duracao_s = COALESCE($2, duracao_s),
                transcript = COALESCE($3, transcript),
                resultado = COALESCE($4, resultado),
                custo_usd = COALESCE($5, custo_usd),
                updated_at = NOW()
            WHERE id = $6 AND empresa_id = $7
            """,
            status, duracao_s, transcript, resultado, custo_usd,
            call_id, empresa_id,
        )
        return True
    except Exception as e:
        logger.error(f"[MKT-06] update_call_status falhou: {e}")
        return False


# ============================================================
# Vapi
# ============================================================

async def _schedule_vapi(
    phone: str, script: str, metadata: Dict, assistant_id: Optional[str] = None,
) -> Optional[str]:
    if not (VAPI_API_KEY and VAPI_PHONE_NUMBER_ID):
        logger.error("[MKT-06] Vapi: VAPI_API_KEY ou VAPI_PHONE_NUMBER_ID ausente")
        return None

    aid = assistant_id or VAPI_ASSISTANT_ID
    payload = {
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {"number": phone},
        "assistantOverrides": {
            "firstMessage": script[:300],
            "metadata": metadata or {},
        },
    }
    if aid:
        payload["assistantId"] = aid
    else:
        # Inline assistant fallback — minimo para ligar
        payload["assistant"] = {
            "firstMessage": script[:300],
            "model": {"provider": "openai", "model": "gpt-4o-mini"},
            "voice": {"provider": "11labs", "voiceId": "21m00Tcm4TlvDq8ikWAM"},
        }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{VAPI_BASE}/call",
                json=payload,
                headers={"Authorization": f"Bearer {VAPI_API_KEY}"},
            )
            if r.status_code >= 400:
                logger.error(f"[MKT-06] Vapi erro {r.status_code}: {r.text[:200]}")
                return None
            return r.json().get("id")
    except Exception as e:
        logger.error(f"[MKT-06] Vapi exception: {e}")
        return None


# ============================================================
# Retell
# ============================================================

async def _schedule_retell(
    phone: str, script: str, metadata: Dict, agent_id: Optional[str] = None,
) -> Optional[str]:
    if not (RETELL_API_KEY and RETELL_PHONE_NUMBER):
        logger.error("[MKT-06] Retell: RETELL_API_KEY ou RETELL_PHONE_NUMBER ausente")
        return None

    aid = agent_id or RETELL_AGENT_ID
    if not aid:
        logger.error("[MKT-06] Retell: agent_id ausente")
        return None

    payload = {
        "from_number": RETELL_PHONE_NUMBER,
        "to_number": phone,
        "agent_id": aid,
        "retell_llm_dynamic_variables": {
            "first_message": script[:300],
            **(metadata or {}),
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{RETELL_BASE}/create-phone-call",
                json=payload,
                headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
            )
            if r.status_code >= 400:
                logger.error(f"[MKT-06] Retell erro {r.status_code}: {r.text[:200]}")
                return None
            return r.json().get("call_id")
    except Exception as e:
        logger.error(f"[MKT-06] Retell exception: {e}")
        return None


# ============================================================
# API publica
# ============================================================

async def schedule_outbound_call(
    empresa_id: int,
    contato_fone: str,
    script_prompt: str,
    motivo: str = "outbound",
    metadata: Optional[Dict] = None,
) -> Optional[int]:
    """Agenda uma chamada outbound. Retorna o ID local (voice_calls.id) ou None."""
    if VOICE_PROVIDER == "disabled":
        logger.info(f"[MKT-06] VOICE_PROVIDER=disabled — chamada ignorada empresa={empresa_id}")
        return None

    # Normaliza numero (E.164)
    phone = contato_fone.strip()
    if not phone.startswith("+"):
        phone = "+" + "".join(c for c in phone if c.isdigit())

    call_id = await _create_call_row(empresa_id, VOICE_PROVIDER, phone, motivo, metadata or {})

    external_id = None
    if VOICE_PROVIDER == "vapi":
        external_id = await _schedule_vapi(phone, script_prompt, metadata or {})
    elif VOICE_PROVIDER == "retell":
        external_id = await _schedule_retell(phone, script_prompt, metadata or {})
    else:
        logger.error(f"[MKT-06] VOICE_PROVIDER desconhecido: {VOICE_PROVIDER}")
        return None

    if call_id and external_id and _database.db_pool:
        try:
            await _database.db_pool.execute(
                "UPDATE voice_calls SET provider_call_id = $1 WHERE id = $2",
                external_id, call_id,
            )
        except Exception:
            pass

    if not external_id:
        await update_call_status(call_id, empresa_id, "falhou", resultado="provider_error")
        return None

    logger.info(f"[MKT-06] chamada {VOICE_PROVIDER} agendada empresa={empresa_id} fone={phone} id={call_id}")
    return call_id
