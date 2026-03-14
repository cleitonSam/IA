import asyncio
import json
import uuid
import time
from src.core.config import (
    logger, REDIS_URL, EMPRESA_ID_PADRAO,
    PROMETHEUS_OK, METRIC_QUEUE_SIZE, METRIC_WORKER_LATENCY, METRIC_WORKER_PROCESSED
)
from src.core.redis_client import redis_client
from src.services.db_queries import carregar_integracao

STREAM_NAME = "ia:webhook:stream"
CONSUMER_GROUP = "ia_workers_group"
CONSUMER_NAME = f"worker-{uuid.uuid4().hex[:8]}"

async def init_stream():
    """Inicializa o Consumer Group no Redis se não existir."""
    try:
        await redis_client.xgroup_create(STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True)
        logger.info(f"✅ Consumer Group '{CONSUMER_GROUP}' criado.")
    except Exception as e:
        if "BUSYGROUP" in str(e):
            logger.info(f"ℹ️ Consumer Group '{CONSUMER_GROUP}' já existe.")
        else:
            logger.error(f"❌ Erro ao criar Consumer Group: {e}")

async def run_stream_worker():
    """Loop principal do worker que consome do Redis Streams."""
    await init_stream()
    logger.info(f"🚀 Stream Worker '{CONSUMER_NAME}' iniciado e aguardando mensagens...")

    while True:
        try:
            if PROMETHEUS_OK:
                _size = await redis_client.xlen(STREAM_NAME)
                METRIC_QUEUE_SIZE.set(_size)

            # Lendo mensagens pendentes ou novas
            streams = await redis_client.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME, {STREAM_NAME: ">"}, count=1, block=5000
            )

            if not streams:
                continue

            for stream_name, messages in streams:
                for msg_id, payload in messages:
                    _start = time.time()
                    try:
                        # Extrair dados do job (com proteção a campos None/string)
                        account_id = int(payload.get("account_id") or 0)
                        conversation_id = int(payload.get("conversation_id") or 0)
                        _raw_contact = payload.get("contact_id")
                        contact_id = int(_raw_contact) if _raw_contact and _raw_contact != "None" else None
                        slug = payload.get("slug") or None
                        nome_cliente = payload.get("nome_cliente") or None
                        empresa_id = int(payload.get("empresa_id") or 0)

                        if not account_id or not conversation_id or not empresa_id:
                            logger.error(f"❌ Job inválido no stream {msg_id}: {payload}")
                            await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
                            await redis_client.xdel(STREAM_NAME, msg_id)
                            continue
                        
                        integracao = await carregar_integracao(empresa_id, 'chatwoot')
                        
                        from src.services.bot_core import processar_ia_e_responder
                        lock_val = str(uuid.uuid4())
                        if await redis_client.set(f"lock:{conversation_id}", lock_val, nx=True, ex=180):
                            await processar_ia_e_responder(
                                account_id, conversation_id, contact_id, slug,
                                nome_cliente, lock_val, empresa_id, integracao
                            )
                        
                        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
                        await redis_client.xdel(STREAM_NAME, msg_id)
                        
                        if PROMETHEUS_OK:
                            METRIC_WORKER_PROCESSED.labels(status="success").inc()
                            METRIC_WORKER_LATENCY.observe(time.time() - _start)
                        
                    except Exception as e:
                        logger.error(f"❌ Erro ao processar mensagem do stream {msg_id}: {e}", exc_info=True)
                        if PROMETHEUS_OK:
                            METRIC_WORKER_PROCESSED.labels(status="error").inc()
                
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Erro no loop do Stream Worker: {e}")
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(run_stream_worker())
