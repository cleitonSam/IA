"""
Rate Limiting por empresa (tenant isolation) — Motor SaaS IA
============================================================
Usa Redis para contar requisições por empresa/endpoint/janela de tempo.
Compatível com SaaS multi-tenant: o limite é POR EMPRESA, não por IP.

Uso:
    from src.utils.rate_limit import rate_limit_empresa

    @router.post("/playground")
    @rate_limit_empresa(max_calls=10, window=60, tag="playground")
    async def playground(request: Request, ...):
        ...

O decorator lê o empresa_id do JWT via `request.state.empresa_id`
(injetado pelo get_current_user_token ao ser chamado antes).

Se o Redis estiver indisponível, a requisição passa sem rate limiting
(fail-open — melhor experiência que bloquear tudo em falha de infra).
"""
import math
import time
import functools
from typing import Callable, Optional
from fastapi import Request, HTTPException
from src.core.config import logger
from src.core.redis_client import redis_client

# Prefixo para chaves Redis de rate limit management
_RL_PREFIX = "rl:mgmt"


async def _check_rate_limit(
    empresa_id: int,
    tag: str,
    max_calls: int,
    window: int,
) -> tuple[int, int]:
    """
    Verifica e incrementa o contador de rate limit.

    Args:
        empresa_id: ID da empresa (isolamento por tenant)
        tag: Identificador do endpoint (ex: "playground", "stream")
        max_calls: Máximo de chamadas permitidas na janela
        window: Tamanho da janela em segundos

    Returns:
        (count, ttl_restante) — count atual e segundos até reset

    Raises:
        HTTPException(429) se o limite foi excedido
    """
    # Janela fixa: agrupa por bucket de `window` segundos
    bucket = math.floor(time.time() / window)
    key = f"{_RL_PREFIX}:{empresa_id}:{tag}:{bucket}"

    try:
        count = await redis_client.incr(key)
        if count == 1:
            # Primeira requisição no bucket — define TTL
            await redis_client.expire(key, window * 2)

        ttl = await redis_client.ttl(key)
        retry_after = max(ttl, 1)

        if count > max_calls:
            logger.warning(
                f"🚦 Rate limit: empresa={empresa_id} endpoint={tag} "
                f"count={count}/{max_calls} janela={window}s"
            )
            raise HTTPException(
                status_code=429,
                detail=f"Muitas requisições. Tente novamente em {retry_after}s.",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(max_calls),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + retry_after),
                },
            )

        return count, retry_after

    except HTTPException:
        raise
    except Exception as e:
        # Fail-open: Redis indisponível → não bloqueia
        logger.warning(f"⚠️ Rate limit Redis indisponível ({tag}): {e} — passando sem limite")
        return 0, window


def rate_limit_empresa(
    max_calls: int = 60,
    window: int = 60,
    tag: Optional[str] = None,
):
    """
    Decorator de rate limiting por empresa para endpoints FastAPI.

    Args:
        max_calls: Máximo de chamadas na janela (default: 60)
        window: Janela em segundos (default: 60 = 1 minuto)
        tag: Identificador do endpoint (auto-detectado pelo nome da função se omitido)

    Exemplo:
        @router.post("/playground/stream")
        @rate_limit_empresa(max_calls=5, window=60, tag="stream")
        async def stream_endpoint(request: Request, ...):
    """
    def decorator(func: Callable) -> Callable:
        endpoint_tag = tag or func.__name__

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Estratégia de extração do empresa_id (em ordem de prioridade):
            # 1. request.state.empresa_id (injetado pelo middleware de auth)
            # 2. token_payload kwarg (padrão FastAPI com Depends)
            # 3. Passa sem limite se não encontrar

            empresa_id: Optional[int] = None

            # 1. Tenta via request.state
            request: Optional[Request] = kwargs.get("request")
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            if request is not None:
                empresa_id = getattr(request.state, "empresa_id", None)

            # 2. Fallback via token_payload nos kwargs (FastAPI Depends)
            if not empresa_id:
                token_payload = kwargs.get("token_payload") or {}
                empresa_id = token_payload.get("empresa_id")

            if not empresa_id:
                # Sem empresa_id identificado → não consegue isolar por tenant → passa sem limite
                return await func(*args, **kwargs)

            await _check_rate_limit(
                empresa_id=int(empresa_id),
                tag=endpoint_tag,
                max_calls=max_calls,
                window=window,
            )

            return await func(*args, **kwargs)

        return wrapper
    return decorator


# ─── Limites pré-definidos (convenience shortcuts) ────────────────────────────

def rate_limit_playground(func: Callable) -> Callable:
    """10 req/min — para endpoints que chamam LLM (custo alto)"""
    return rate_limit_empresa(max_calls=10, window=60, tag="playground")(func)


def rate_limit_stream(func: Callable) -> Callable:
    """5 req/min — para streaming de LLM (conexão longa + custo alto)"""
    return rate_limit_empresa(max_calls=5, window=60, tag="stream")(func)


def rate_limit_tts(func: Callable) -> Callable:
    """15 req/min — para preview de voz TTS"""
    return rate_limit_empresa(max_calls=15, window=60, tag="tts")(func)


def rate_limit_preview(func: Callable) -> Callable:
    """20 req/min — para preview de prompt"""
    return rate_limit_empresa(max_calls=20, window=60, tag="preview")(func)
