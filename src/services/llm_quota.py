"""
[ARQ-04] Quota de LLM por tenant — evita que um cliente esgote o orçamento de todos.

Uso:
    from src.services.llm_quota import check_and_reserve_llm_call, record_llm_usage

    # Antes de chamar o LLM
    ok, reason = await check_and_reserve_llm_call(empresa_id, estimated_tokens=4000)
    if not ok:
        raise HTTPException(429, detail=f"Quota LLM esgotada: {reason}")

    # Depois de chamar (com custo real)
    await record_llm_usage(empresa_id, actual_tokens=3912, actual_cost_usd=0.0039)

Limites (env):
  LLM_QUOTA_DAILY_TOKENS_PER_EMPRESA   (default: 500_000)
  LLM_QUOTA_MONTHLY_USD_PER_EMPRESA    (default: 50.0)
  LLM_QUOTA_RPM_PER_EMPRESA            (default: 60 requests/minute)
"""

import os
import time
from typing import Tuple

from src.core.config import logger
from src.core.redis_client import redis_client

DAILY_TOKENS_CAP = int(os.getenv("LLM_QUOTA_DAILY_TOKENS_PER_EMPRESA", "500000"))
MONTHLY_USD_CAP = float(os.getenv("LLM_QUOTA_MONTHLY_USD_PER_EMPRESA", "50.0"))
RPM_CAP = int(os.getenv("LLM_QUOTA_RPM_PER_EMPRESA", "60"))


def _keys(empresa_id: int) -> dict:
    day = time.strftime("%Y%m%d", time.gmtime())
    month = time.strftime("%Y%m", time.gmtime())
    minute = int(time.time() // 60)
    return {
        "daily_tokens": f"llm_quota:tokens:{empresa_id}:{day}",
        "monthly_usd_cents": f"llm_quota:usd:{empresa_id}:{month}",
        "rpm": f"llm_quota:rpm:{empresa_id}:{minute}",
    }


# [C-05] Circuit breaker pra evitar fail-open infinito em queda de Redis.
# Se 5+ falhas em 2 min, bloqueia LLM calls ("fail-closed") ate melhorar.
_CIRCUIT_BREAKER = {
    "failures": 0,
    "last_failure": 0.0,
    "state": "closed",  # closed | open | half-open
}
_CB_THRESHOLD = 5
_CB_WINDOW_S = 120       # 2 min
_CB_OPEN_COOLDOWN_S = 60  # re-tenta apos 60s em "half-open"


async def check_and_reserve_llm_call(empresa_id: int, estimated_tokens: int = 2000) -> Tuple[bool, str]:
    """
    Verifica se a chamada é permitida. Reserva (incrementa RPM) atomicamente.
    Retorna (permitido, motivo_se_negado).
    """
    import time as _time
    if not empresa_id or empresa_id <= 0:
        return False, "empresa_id_invalido"

    # Circuit breaker check (C-05)
    now = _time.time()
    if _CIRCUIT_BREAKER["state"] == "open":
        if now - _CIRCUIT_BREAKER["last_failure"] > _CB_OPEN_COOLDOWN_S:
            _CIRCUIT_BREAKER["state"] = "half-open"
            _CIRCUIT_BREAKER["failures"] = 0
            logger.warning("[C-05] llm_quota circuit breaker: half-open (tentando reconectar)")
        else:
            return False, "circuit_breaker_open_redis_down"

    k = _keys(empresa_id)

    try:
        # RPM cap (minutely)
        rpm = await redis_client.incr(k["rpm"])
        if rpm == 1:
            await redis_client.expire(k["rpm"], 90)
        if rpm > RPM_CAP:
            return False, f"rpm_cap_reached ({RPM_CAP}/min)"

        # Daily tokens — reserva o estimado (ajustado em record_llm_usage)
        tokens_used_raw = await redis_client.get(k["daily_tokens"])
        tokens_used = int(tokens_used_raw or 0)
        if tokens_used + estimated_tokens > DAILY_TOKENS_CAP:
            return False, f"daily_tokens_cap_reached ({DAILY_TOKENS_CAP}/dia)"

        # Monthly USD (em centavos para usar INCR)
        usd_cents_raw = await redis_client.get(k["monthly_usd_cents"])
        usd_cents = int(usd_cents_raw or 0)
        if usd_cents / 100.0 >= MONTHLY_USD_CAP:
            return False, f"monthly_usd_cap_reached (${MONTHLY_USD_CAP}/mes)"

        # Sucesso: reset breaker
        if _CIRCUIT_BREAKER["state"] != "closed":
            _CIRCUIT_BREAKER["state"] = "closed"
            _CIRCUIT_BREAKER["failures"] = 0
            logger.info("[C-05] llm_quota circuit breaker: closed (Redis voltou)")

        return True, ""
    except Exception as e:
        # Registra falha no breaker
        if now - _CIRCUIT_BREAKER["last_failure"] > _CB_WINDOW_S:
            _CIRCUIT_BREAKER["failures"] = 1
        else:
            _CIRCUIT_BREAKER["failures"] += 1
        _CIRCUIT_BREAKER["last_failure"] = now
        if _CIRCUIT_BREAKER["failures"] >= _CB_THRESHOLD:
            _CIRCUIT_BREAKER["state"] = "open"
            logger.error(f"[C-05] llm_quota circuit breaker: OPEN (Redis falhou {_CB_THRESHOLD}x em {_CB_WINDOW_S}s)")
            return False, "circuit_breaker_triggered"
        logger.warning(f"[ARQ-04] llm_quota check falhou (fail-open transitorio) empresa={empresa_id}: {e}")
        return True, ""


async def record_llm_usage(empresa_id: int, actual_tokens: int, actual_cost_usd: float) -> None:
    """Registra o consumo real depois da chamada ao LLM."""
    if not empresa_id or empresa_id <= 0:
        return

    k = _keys(empresa_id)
    try:
        # Tokens diarios
        await redis_client.incrby(k["daily_tokens"], max(0, int(actual_tokens)))
        await redis_client.expire(k["daily_tokens"], 90000)  # ~25h

        # Custo mensal (em centavos para atomicidade)
        cents = max(0, int(round(actual_cost_usd * 100)))
        if cents:
            await redis_client.incrby(k["monthly_usd_cents"], cents)
            await redis_client.expire(k["monthly_usd_cents"], 35 * 86400)

        # Alerta em 80% do cap mensal (so loga uma vez por empresa/mes)
        usd_cents = int(await redis_client.get(k["monthly_usd_cents"]) or 0)
        if usd_cents >= int(MONTHLY_USD_CAP * 100 * 0.8):
            alert_key = f"llm_quota:alert80:{empresa_id}:{time.strftime('%Y%m', time.gmtime())}"
            if await redis_client.set(alert_key, "1", nx=True, ex=35 * 86400):
                logger.warning(
                    f"[ARQ-04] empresa={empresa_id} atingiu 80% do cap mensal (${usd_cents/100:.2f}/{MONTHLY_USD_CAP})"
                )
    except Exception as e:
        logger.warning(f"[ARQ-04] record_llm_usage falhou empresa={empresa_id}: {e}")


async def get_empresa_usage(empresa_id: int) -> dict:
    """Retorna snapshot de uso atual para dashboard."""
    k = _keys(empresa_id)
    try:
        daily = int(await redis_client.get(k["daily_tokens"]) or 0)
        monthly_cents = int(await redis_client.get(k["monthly_usd_cents"]) or 0)
        return {
            "empresa_id": empresa_id,
            "daily_tokens_used": daily,
            "daily_tokens_cap": DAILY_TOKENS_CAP,
            "daily_pct": round(100 * daily / DAILY_TOKENS_CAP, 2) if DAILY_TOKENS_CAP else 0,
            "monthly_usd_used": monthly_cents / 100.0,
            "monthly_usd_cap": MONTHLY_USD_CAP,
            "monthly_pct": round(100 * (monthly_cents / 100.0) / MONTHLY_USD_CAP, 2) if MONTHLY_USD_CAP else 0,
        }
    except Exception as e:
        logger.warning(f"[ARQ-04] get_empresa_usage falhou: {e}")
        return {"empresa_id": empresa_id, "error": str(e)}
