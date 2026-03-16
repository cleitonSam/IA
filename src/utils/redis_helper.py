import json
from typing import Any, Optional
from src.core.redis_client import redis_client, redis_get_json, redis_set_json
from src.core.config import logger

def get_tenant_key(empresa_id: int, key: str) -> str:
    """Gera uma chave Redis prefixada com o empresa_id."""
    return f"{empresa_id}:{key}"

async def set_tenant_cache(empresa_id: int, key: str, value: Any, ttl: int = 3600):
    """Salva um valor no cache do Redis prefixado pelo empresa_id."""
    t_key = get_tenant_key(empresa_id, key)
    if isinstance(value, (dict, list)):
        await redis_set_json(t_key, value, ttl)
    else:
        await redis_client.setex(t_key, ttl, value)

async def get_tenant_cache(empresa_id: int, key: str, is_json: bool = False) -> Any:
    """Recupera um valor do cache do Redis prefixado pelo empresa_id."""
    t_key = get_tenant_key(empresa_id, key)
    if is_json:
        return await redis_get_json(t_key)
    return await redis_client.get(t_key)

async def delete_tenant_cache(empresa_id: int, key: str):
    """Remove uma chave do cache do Redis prefixada pelo empresa_id."""
    t_key = get_tenant_key(empresa_id, key)
    await redis_client.delete(t_key)

async def exists_tenant_cache(empresa_id: int, key: str) -> bool:
    """Verifica se uma chave existe no cache do Redis prefixada pelo empresa_id."""
    t_key = get_tenant_key(empresa_id, key)
    return await redis_client.exists(t_key)
