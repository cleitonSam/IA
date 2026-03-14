import time
import json
from typing import Any
import redis.asyncio as redis
from src.core.config import REDIS_URL, logger

# Inicialização global do redis_client
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Memória local para fallback em caso de falha no Redis
_LOCAL_REDIS_FALLBACK = {}

async def redis_get_json(key: str, default=None):
    try:
        raw = await redis_client.get(key)
    except Exception:
        raw = None

    if raw is not None:
        try:
            return json.loads(raw)
        except Exception:
            return default

    # Fallback local em memória quando Redis estiver indisponível
    now = time.time()
    item = _LOCAL_REDIS_FALLBACK.get(key)
    if item:
        exp_ts, raw_local = item
        if exp_ts >= now:
            try:
                return json.loads(raw_local)
            except Exception:
                return default
        _LOCAL_REDIS_FALLBACK.pop(key, None)
    return default


async def redis_set_json(key: str, value: Any, ttl: int):
    payload = json.dumps(value, default=str)
    try:
        await redis_client.setex(key, ttl, payload)
    except Exception:
        _LOCAL_REDIS_FALLBACK[key] = (time.time() + max(1, ttl), payload)
