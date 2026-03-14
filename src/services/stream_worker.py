import asyncio
import json
import uuid
import time
from src.core.config import logger, REDIS_URL, EMPRESA_ID_PADRAO
from src.core.redis_client import redis_client
from src.services.bot_core import processar_ia_e_responder
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
            # Lendo mensagens pendentes ou novas
            # id=">" significa ler apenas mensagens que ainda não foram entregues a ninguém
            streams = await redis_client.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME, {STREAM_NAME: ">"}, count=1, block=5000
            )

            if not streams:
                continue

            for stream_name, messages in streams:
                for msg_id, payload in messages:
                    try:
                        # Extrair dados do job
                        account_id = int(payload.get("account_id"))
                        conversation_id = int(payload.get("conversation_id"))
                        contact_id = int(payload.get("contact_id"))
                        slug = payload.get("slug")
                        nome_cliente = payload.get("nome_cliente")
                        empresa_id = int(payload.get("empresa_id"))
                        
                        # Lock e Integracao devem ser recuperados ou passados
                        # Como o webhook já validou a integracao, podemos recarregar aqui
                        integracao = await carregar_integracao(empresa_id, 'chatwoot')
                        
                        lock_val = str(uuid.uuid4())
                        # A aquisição do lock de processamento ainda é importante para o buffet
                        if await redis_client.set(f"lock:{conversation_id}", lock_val, nx=True, ex=180):
                            # Chama o processador principal
                            await processar_ia_e_responder(
                                account_id, conversation_id, contact_id, slug,
                                nome_cliente, lock_val, empresa_id, integracao
                            )
                        
                        # Confirmar processamento (Acknowledge)
                        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
                        # Deletar do stream para não crescer infinitamente
                        await redis_client.xdel(STREAM_NAME, msg_id)
                        
                    except Exception as e:
                        logger.error(f"❌ Erro ao processar mensagem do stream {msg_id}: {e}", exc_info=True)
                        # Opcional: Reenfileirar ou colocar em uma DLQ
                
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Erro no loop do Stream Worker: {e}")
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(run_stream_worker())
