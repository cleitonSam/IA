"""
[SEC-05] Rate-limit genérico com fallback in-memory.

Uso:
    from src.middleware.rate_limit import rate_limit

    @router.post("/auth/register")
    async def register(
        body: RegisterRequest,
        _rl = Depends(rate_limit(key="register", max_calls=10, window=60)),
    ):
        ...

Implementação:
  - Tenta Redis (atômico via INCR + EXPIRE).
  - Se Redis falhar, usa cachetools.TTLCache (limitado a 10k chaves).
  - Nunca silencia: loga se o fallback for usado.
"""

import time
from typing import Callable, Optional
from fastapi import Depends, HTTPException, Request, status

from src.core.config import logger
from src.core.redis_client import redis_client

try:
    from cachetools import TTLCache
    _LOCAL_CACHE: "TTLCache[str, int]" = TTLCache(maxsize=10_000, ttl=300)
    _HAS_LOCAL_CACHE = True
except ImportError:
    _LOCAL_CACHE = {}  # type: ignore[assignment]
    _HAS_LOCAL_CACHE = False


async def _increment_redis(key: str, window: int) -> Optional[int]:
    try:
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, window)
        return int(count)
    except Exception as e:
        logger.warning(f"[rate_limit] Redis indisponível para {key}: {e}")
        return None


def _increment_local(key: str) -> int:
    now = time.time()
    current = _LOCAL_CACHE.get(key)
    if isinstance(current, tuple):
        count, _ = current
        count += 1
    else:
        count = 1
    _LOCAL_CACHE[key] = (count, now)
    return count


def rate_limit(
    key: str,
    max_calls: int = 10,
    window: int = 60,
    by: str = "ip",
) -> Callable:
    """
    Retorna uma dependência FastAPI que aplica rate-limit.

    Parametros:
      key: prefixo da chave (ex: "register", "login")
      max_calls: maximo de chamadas permitidas na janela
      window: janela em segundos
      by: "ip" ou "user" (exige Authorization header)
    """
    async def _dependency(request: Request):
        if by == "ip":
            client_ip = request.client.host if request.client else "unknown"
            bucket = f"rl:{key}:ip:{client_ip}"
        elif by == "user":
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                # usa hash simples do token como chave (nao ideal mas simples)
                import hashlib
                token_hash = hashlib.sha256(auth[7:].encode()).hexdigest()[:16]
                bucket = f"rl:{key}:user:{token_hash}"
            else:
                client_ip = request.client.host if request.client else "unknown"
                bucket = f"rl:{key}:anon:{client_ip}"
        else:
            bucket = f"rl:{key}:global"

        count = await _increment_redis(bucket, window)
        if count is None:
            count = _increment_local(bucket)

        if count > max_calls:
            logger.warning(f"[rate_limit] {bucket} excedeu {max_calls}/{window}s (count={count})")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit excedido. Aguarde {window}s.",
                headers={"Retry-After": str(window)},
            )

        return {"count": count, "bucket": bucket}

    return _dependency
