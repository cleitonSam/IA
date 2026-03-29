import time
import json
from typing import Any
import redis.asyncio as redis
from src.core.config import REDIS_URL, logger

# Inicialização global do redis_client
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Memória local para fallback em caso de falha no Redis
_LOCAL_REDIS_FALLBACK: dict[str, tuple[float, str]] = {}
_FALLBACK_MAX_SIZE = 1000
_FALLBACK_OP_COUNT = 0
_FALLBACK_GC_INTERVAL = 100  # cleanup a cada N operações


def _fallback_gc():
    """Remove itens expirados do fallback local."""
    global _FALLBACK_OP_COUNT
    _FALLBACK_OP_COUNT += 1
    if _FALLBACK_OP_COUNT < _FALLBACK_GC_INTERVAL:
        return
    _FALLBACK_OP_COUNT = 0
    now = time.time()
    expired = [k for k, (exp, _) in _LOCAL_REDIS_FALLBACK.items() if exp < now]
    for k in expired:
        _LOCAL_REDIS_FALLBACK.pop(k, None)
    if expired:
        logger.debug(f"🧹 Redis fallback GC: {len(expired)} itens expirados removidos")


def _fallback_evict_if_full():
    """Evicta itens mais antigos se ultrapassar o limite."""
    while len(_LOCAL_REDIS_FALLBACK) >= _FALLBACK_MAX_SIZE:
        oldest_key = min(_LOCAL_REDIS_FALLBACK, key=lambda k: _LOCAL_REDIS_FALLBACK[k][0])
        _LOCAL_REDIS_FALLBACK.pop(oldest_key, None)


async def redis_get_json(key: str, default=None):
    _fallback_gc()
    try:
        raw = await redis_client.get(key)
    except Exception as e:
        logger.warning(f"⚠️ Redis GET falhou ({type(e).__name__}: {e}), usando fallback local")
        raw = None

    if raw is not None:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"⚠️ Redis JSON parse falhou para key={key}: {e}")
            return default

    # Fallback local em memória quando Redis estiver indisponível
    now = time.time()
    item = _LOCAL_REDIS_FALLBACK.get(key)
    if item:
        exp_ts, raw_local = item
        if exp_ts >= now:
            try:
                return json.loads(raw_local)
            except (json.JSONDecodeError, TypeError):
                return default
        _LOCAL_REDIS_FALLBACK.pop(key, None)
    return default


async def redis_set_json(key: str, value: Any, ttl: int):
    payload = json.dumps(value, default=str)
    try:
        await redis_client.setex(key, ttl, payload)
    except Exception as e:
        logger.warning(f"⚠️ Redis SET falhou ({type(e).__name__}: {e}), salvando em fallback local")
        _fallback_evict_if_full()
        _LOCAL_REDIS_FALLBACK[key] = (time.time() + max(1, ttl), payload)
