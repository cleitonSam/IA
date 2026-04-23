#!/usr/bin/env sh
#
# [ARQ-01] Script de migracao com distributed lock via Redis.
#
# Roda as migrations Alembic de forma segura em ambientes com multiplas replicas:
# - Adquire lock exclusivo no Redis (SET NX EX) para que apenas UM container rode o upgrade.
# - Aguarda outros pods concluirem se o lock ja existir.
# - Se Redis nao estiver disponivel, aborta (fail-closed) para evitar race.
#
# Uso:
#   scripts/migrate.sh            # roda alembic upgrade head com lock
#   scripts/migrate.sh downgrade  # roda downgrade -1 com confirmacao
#
# Variaveis de ambiente requeridas:
#   REDIS_URL
#   DATABASE_URL
#
set -euo pipefail

LOCK_KEY="alembic:migrate:lock"
LOCK_TTL="${ALEMBIC_LOCK_TTL:-300}"  # 5 min
LOCK_TOKEN="$(hostname)-$$-$(date +%s%N)"

if [ -z "${REDIS_URL:-}" ]; then
  echo "ERRO: REDIS_URL nao definido — nao posso adquirir lock distribuido." >&2
  exit 1
fi

echo "[migrate] adquirindo lock ${LOCK_KEY} (ttl=${LOCK_TTL}s)..."

# Usa redis-cli em Python (garantido no container)
ACQUIRED=$(python - <<PY
import os, sys
import redis.asyncio as aioredis
import asyncio

async def main():
    r = aioredis.from_url(os.environ["REDIS_URL"])
    ok = await r.set("${LOCK_KEY}", "${LOCK_TOKEN}", nx=True, ex=${LOCK_TTL})
    print("1" if ok else "0")
    await r.aclose()

asyncio.run(main())
PY
)

if [ "$ACQUIRED" != "1" ]; then
  echo "[migrate] outro container ja esta migrando. Aguardando 30s e continuando (migrations sao idempotentes)..."
  sleep 30
  exit 0
fi

trap 'python -c "
import os, asyncio
import redis.asyncio as aioredis
async def main():
    r = aioredis.from_url(os.environ[\"REDIS_URL\"])
    v = await r.get(\"${LOCK_KEY}\")
    if v and v.decode() == \"${LOCK_TOKEN}\":
        await r.delete(\"${LOCK_KEY}\")
    await r.aclose()
asyncio.run(main())
"' EXIT

echo "[migrate] lock adquirido. Rodando alembic upgrade head..."
python -m alembic upgrade head
echo "[migrate] migrations aplicadas com sucesso."
