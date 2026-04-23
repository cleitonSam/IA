import asyncio
import json
import uuid
import time
import httpx
from src.core.config import (
    logger, REDIS_URL, EMPRESA_ID_PADRAO,
    PROMETHEUS_OK, METRIC_QUEUE_SIZE, METRIC_WORKER_LATENCY, METRIC_WORKER_PROCESSED
)
import src.core.database as _database
from src.core.redis_client import redis_client
from src.services.db_queries import carregar_integracao, buscar_conversa_por_fone, bd_iniciar_conversa
from src.services.bot_core import processar_ia_e_responder

STREAM_NAME = "ia:webhook:stream"
DEADLETTER_STREAM = "ia:webhook:deadletter"
CONSUMER_GROUP = "ia_workers_group"
CONSUMER_NAME = f"worker-{uuid.uuid4().hex[:8]}"

MAX_CONCURRENT = 10  # Máximo de conversas simultâneas
_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
_active_tasks: set = set()

# [ARQ-06] Trim do stream a cada N mensagens processadas (evita crescimento ilimitado).
STREAM_MAX_LEN = 10000
_trim_counter = 0

# [ARQ-05] Idempotencia: keys Redis de mensagens ja processadas (TTL 24h)
IDEMPOTENCY_TTL = 86400

# [ARQ-05] Limite de retries antes de mandar pro deadletter
MAX_DELIVERY_COUNT = 5

# [INF-07] Heartbeat — worker grava timestamp periodicamente; healthcheck le
HEARTBEAT_KEY = "worker:heartbeat"
HEARTBEAT_TTL = 180  # segundos


async def _write_heartbeat() -> None:
    try:
        await redis_client.setex(HEARTBEAT_KEY, HEARTBEAT_TTL, str(time.time()))
    except Exception as e:
        logger.warning(f"[heartbeat] falha ao gravar: {e}")


async def _already_processed(msg_id: str, idempotency_key: str) -> bool:
    """[ARQ-05] Retorna True se msg_id ja foi processado com sucesso."""
    key = f"stream:processed:{idempotency_key}"
    try:
        return bool(await redis_client.exists(key))
    except Exception as e:
        logger.warning(f"[idempotency] redis falhou para {key}: {e}; seguindo sem idempotencia")
        return False


async def _mark_processed(idempotency_key: str) -> None:
    key = f"stream:processed:{idempotency_key}"
    try:
        await redis_client.setex(key, IDEMPOTENCY_TTL, "1")
    except Exception as e:
        logger.warning(f"[idempotency] falha ao marcar {key}: {e}")


def _build_idempotency_key(payload: dict) -> str:
    """Gera uma chave determinística para dedup baseada no payload lógico do job."""
    source = payload.get("source", "chatwoot")
    empresa_id = payload.get("empresa_id", "0")
    if source == "uazapi":
        phone = payload.get("phone", "")
        uaz_msg_id = payload.get("msg_id", "")
        return f"{source}:{empresa_id}:{phone}:{uaz_msg_id}"
    conv_id = payload.get("conversation_id", "")
    msg_id_cw = payload.get("message_id", payload.get("id", ""))
    return f"{source}:{empresa_id}:{conv_id}:{msg_id_cw}"


async def _move_to_deadletter(msg_id: str, payload: dict, reason: str) -> None:
    """[ARQ-05] Move mensagem envenenada para deadletter stream."""
    try:
        await redis_client.xadd(
            DEADLETTER_STREAM,
            {
                "original_msg_id": msg_id,
                "reason": reason,
                "payload_json": json.dumps(payload),
                "moved_at": str(time.time()),
            },
            maxlen=5000,
        )
        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
        await redis_client.xdel(STREAM_NAME, msg_id)
        logger.error(f"[ARQ-05] msg {msg_id} movida para deadletter: {reason}")
    except Exception as e:
        logger.error(f"[ARQ-05] falha ao mover para deadletter: {e}")

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


async def _process_job(msg_id: str, payload: dict):
    """Processa um job individual do stream de forma isolada."""
    _start = time.time()

    # [ARQ-05] Idempotencia: se ja processamos este msg_id, ack e sai.
    idempotency_key = _build_idempotency_key(payload)
    if await _already_processed(msg_id, idempotency_key):
        logger.info(f"[ARQ-05] msg ja processada (idempotent): {idempotency_key}")
        try:
            await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
            await redis_client.xdel(STREAM_NAME, msg_id)
        except Exception:
            pass
        if PROMETHEUS_OK and METRIC_WORKER_PROCESSED:
            METRIC_WORKER_PROCESSED.labels(status="duplicate").inc()
        return

    try:
        try:
            await asyncio.wait_for(_semaphore.acquire(), timeout=30)
        except asyncio.TimeoutError:
            logger.warning(f"semaphore_timeout msg_id={msg_id} job descartado apos 30s")
            await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
            if PROMETHEUS_OK and METRIC_WORKER_PROCESSED:
                METRIC_WORKER_PROCESSED.labels(status="semaphore_timeout").inc()
            return
        try:
            source = payload.get("source", "chatwoot")
            empresa_id = int(payload.get("empresa_id") or 0)
            logger.info(f"📥 Job recebido no Worker: empresa={empresa_id} source={source} msg_id={msg_id}")

            if source == "uazapi":
                phone = payload.get("phone")
                conversa = await buscar_conversa_por_fone(phone, empresa_id)
                if not conversa:
                    temp_conv_id = int(time.time()) * -1
                    await bd_iniciar_conversa(
                        temp_conv_id, "uazapi", 0,
                        contato_nome=payload.get("nome_cliente"),
                        empresa_id=empresa_id,
                        contato_fone=phone
                    )
                    conversa = await buscar_conversa_por_fone(phone, empresa_id)

                contato_fone = phone

                account_id = conversa.get("account_id", 0)
                conversation_id = conversa.get("conversation_id")
                contact_id = conversa.get("contato_id")
                slug = conversa.get("unidade_slug") or "uazapi"
                nome_cliente = conversa.get("contato_nome")
            else:
                # Fluxo Chatwoot clássico
                account_id = int(payload.get("account_id") or 0)
                conversation_id = int(payload.get("conversation_id") or 0)
                _raw_contact = payload.get("contact_id")
                contact_id = int(_raw_contact) if _raw_contact and _raw_contact != "None" else None
                slug = payload.get("slug")
                nome_cliente = payload.get("nome_cliente")
                contato_fone = payload.get("contato_fone")

                # Safety net: garante que a conversa existe no BD local
                await bd_iniciar_conversa(
                    conversation_id, slug or "", account_id,
                    contato_id=contact_id,
                    contato_nome=nome_cliente,
                    empresa_id=empresa_id,
                    contato_fone=contato_fone
                )

                # Se não veio no payload, tenta buscar no BD
                if not contato_fone:
                    _db_fone = await _database.db_pool.fetchval(
                        "SELECT contato_fone FROM conversas WHERE conversation_id = $1", conversation_id
                    )
                    if _db_fone:
                        contato_fone = _db_fone

                # Se temos o telefone, responder via UazAPI (Modo Humano)
                if contato_fone and contato_fone.strip():
                    source = "uazapi"
                    logger.info(f"🔄 Redirecionando resposta da conv {conversation_id} para UazAPI (fone: {contato_fone})")

            if not conversation_id or not empresa_id:
                logger.error(f"❌ Job inválido no stream {msg_id}: {payload}")
                await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
                return

            # --- Áudio UazAPI: popular buffet com URL do áudio ---
            if source == "uazapi" and payload.get("has_audio") == "1":
                _audio_url = payload.get("audio_url", "")
                _buffet_key = f"{empresa_id}:buffet:{conversation_id}"
                if _audio_url:
                    await redis_client.rpush(_buffet_key, json.dumps({
                        "text": "",
                        "files": [{"url": _audio_url, "type": "audio"}]
                    }))
                    await redis_client.expire(_buffet_key, 60)
                    logger.info(f"🎙️ Áudio UazAPI → buffet: {contato_fone} conv={conversation_id}")
                else:
                    # Sem mediaUrl do UazAPI → busca no Chatwoot
                    _integracao_cw = await carregar_integracao(empresa_id, 'chatwoot')
                    if _integracao_cw:
                        _cw_url = _integracao_cw.get("url") or _integracao_cw.get("base_url") or ""
                        _cw_token = _integracao_cw.get("access_token") or _integracao_cw.get("token") or ""
                        _cw_account = _integracao_cw.get("account_id") or account_id
                        _cw_conv = conversation_id if conversation_id > 0 else None
                        if not _cw_conv:
                            try:
                                _row = await _database.db_pool.fetchval(
                                    "SELECT conversation_id FROM conversas WHERE contato_fone = $1 AND empresa_id = $2 AND conversation_id > 0 ORDER BY updated_at DESC LIMIT 1",
                                    contato_fone, empresa_id
                                )
                                if _row:
                                    _cw_conv = _row
                            except Exception:
                                pass

                        if _cw_url and _cw_token and _cw_account and _cw_conv:
                            logger.info(f"🎙️ Buscando áudio no Chatwoot para {contato_fone} (account={_cw_account} conv={_cw_conv})...")
                            await asyncio.sleep(5)
                            try:
                                async with httpx.AsyncClient(timeout=10.0) as _cw_client:
                                    _cw_resp = await _cw_client.get(
                                        f"{_cw_url.rstrip('/')}/api/v1/accounts/{_cw_account}/conversations/{_cw_conv}/messages",
                                        headers={"api_access_token": str(_cw_token)},
                                    )
                                    if _cw_resp.status_code == 200:
                                        _cw_msgs = _cw_resp.json().get("payload", [])
                                        for _m in _cw_msgs:
                                            for _att in (_m.get("attachments") or []):
                                                if str(_att.get("file_type", "")).startswith("audio"):
                                                    _audio_url = _att.get("data_url")
                                                    break
                                            if _audio_url:
                                                break
                                        if _audio_url:
                                            await redis_client.rpush(_buffet_key, json.dumps({
                                                "text": "",
                                                "files": [{"url": _audio_url, "type": "audio"}]
                                            }))
                                            await redis_client.expire(_buffet_key, 60)
                                            logger.info(f"🎙️ Áudio Chatwoot → buffet: {contato_fone} conv={conversation_id} | {_audio_url[:80]}...")
                                        else:
                                            logger.warning(f"⚠️ Áudio não encontrado no Chatwoot para {contato_fone}")
                                    else:
                                        logger.warning(f"⚠️ Chatwoot retornou {_cw_resp.status_code} ao buscar áudio para conv {_cw_conv}")
                            except Exception as _cw_err:
                                logger.error(f"❌ Erro ao buscar áudio no Chatwoot: {_cw_err}")
                        else:
                            logger.warning(f"⚠️ Sem dados Chatwoot para buscar áudio: url={bool(_cw_url)} token={bool(_cw_token)} account={_cw_account} conv={_cw_conv}")
                    else:
                        logger.warning(f"⚠️ Integração Chatwoot não encontrada para buscar áudio (empresa {empresa_id})")

            # --- Imagem/Vídeo UazAPI: popular buffet com URL da mídia ---
            if source == "uazapi" and payload.get("has_image") == "1":
                _image_url = payload.get("image_url", "")
                _buffet_key = f"{empresa_id}:buffet:{conversation_id}"
                if _image_url:
                    await redis_client.rpush(_buffet_key, json.dumps({
                        "text": payload.get("content", "") if payload.get("content", "") not in ("[Imagem recebida]", "[Vídeo recebido]") else "",
                        "files": [{"url": _image_url, "type": "image"}]
                    }))
                    await redis_client.expire(_buffet_key, 60)
                    logger.info(f"🖼️ Imagem UazAPI → buffet: {contato_fone} conv={conversation_id}")
                else:
                    # Sem mediaUrl do UazAPI → busca no Chatwoot
                    _integracao_cw_img = await carregar_integracao(empresa_id, 'chatwoot')
                    if _integracao_cw_img:
                        _cw_url_img = _integracao_cw_img.get("url") or _integracao_cw_img.get("base_url") or ""
                        _cw_token_img = _integracao_cw_img.get("access_token") or _integracao_cw_img.get("token") or ""
                        _cw_account_img = _integracao_cw_img.get("account_id") or account_id
                        _cw_conv_img = conversation_id if conversation_id > 0 else None
                        if not _cw_conv_img:
                            try:
                                _row_img = await _database.db_pool.fetchval(
                                    "SELECT conversation_id FROM conversas WHERE contato_fone = $1 AND empresa_id = $2 AND conversation_id > 0 ORDER BY updated_at DESC LIMIT 1",
                                    contato_fone, empresa_id
                                )
                                if _row_img:
                                    _cw_conv_img = _row_img
                            except Exception:
                                pass

                        if _cw_url_img and _cw_token_img and _cw_account_img and _cw_conv_img:
                            logger.info(f"🖼️ Buscando imagem no Chatwoot para {contato_fone}...")
                            await asyncio.sleep(5)
                            try:
                                async with httpx.AsyncClient(timeout=10.0) as _cw_client_img:
                                    _cw_resp_img = await _cw_client_img.get(
                                        f"{_cw_url_img.rstrip('/')}/api/v1/accounts/{_cw_account_img}/conversations/{_cw_conv_img}/messages",
                                        headers={"api_access_token": str(_cw_token_img)},
                                    )
                                    if _cw_resp_img.status_code == 200:
                                        _found_img_url = ""
                                        _cw_msgs_img = _cw_resp_img.json().get("payload", [])
                                        for _m_img in _cw_msgs_img:
                                            for _att_img in (_m_img.get("attachments") or []):
                                                _ft = str(_att_img.get("file_type", "")).lower()
                                                if _ft.startswith("image") or _ft.startswith("video"):
                                                    _found_img_url = _att_img.get("data_url")
                                                    break
                                            if _found_img_url:
                                                break
                                        if _found_img_url:
                                            await redis_client.rpush(_buffet_key, json.dumps({
                                                "text": "",
                                                "files": [{"url": _found_img_url, "type": "image"}]
                                            }))
                                            await redis_client.expire(_buffet_key, 60)
                                            logger.info(f"🖼️ Imagem Chatwoot → buffet: {contato_fone} conv={conversation_id}")
                                        else:
                                            logger.warning(f"⚠️ Imagem não encontrada no Chatwoot para {contato_fone}")
                            except Exception as _cw_img_err:
                                logger.error(f"❌ Erro ao buscar imagem no Chatwoot: {_cw_img_err}")
                    else:
                        logger.warning(f"⚠️ Integração Chatwoot não encontrada para buscar imagem (empresa {empresa_id})")

            # --- Texto UazAPI: garante que o conteúdo de texto entra no buffet ---
            # O Chatwoot normalmente também push o texto, mas esse safety net
            # garante funcionamento mesmo se Chatwoot estiver indisponível.
            if source == "uazapi":
                _text_content = payload.get("content", "")
                _placeholders = {"[Áudio recebido]", "[Imagem recebida]", "[Vídeo recebido]", ""}
                _buffet_key_txt = f"{empresa_id}:buffet:{conversation_id}"
                if _text_content not in _placeholders:
                    # Só empurra texto se NÃO veio junto com imagem (evita duplicação)
                    if payload.get("has_image") != "1":
                        await redis_client.rpush(_buffet_key_txt, json.dumps({
                            "text": _text_content, "files": []
                        }))
                        await redis_client.expire(_buffet_key_txt, 60)

            integracao = await carregar_integracao(empresa_id, 'chatwoot' if source == "chatwoot" else 'uazapi')
            if not integracao:
                logger.error(f"❌ Falha ao carregar integração {source} para empresa {empresa_id}. Job abortado.")
                await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
                return

            logger.info(f"⚙️ Integração {source} carregada com sucesso. Iniciando processamento IA.")
            lock_val = str(uuid.uuid4())
            lock_key = f"lock:{empresa_id}:{conversation_id}"
            if await redis_client.set(lock_key, lock_val, nx=True, ex=60):
                try:
                    async with asyncio.timeout(120):  # Timeout global de 120s por job
                        while True:
                            await processar_ia_e_responder(
                                account_id, conversation_id, contact_id, slug,
                                nome_cliente, lock_val, empresa_id, integracao,
                                source=source,
                                contato_fone=contato_fone
                            )
                            if await redis_client.llen(f"{empresa_id}:buffet:{conversation_id}") == 0:
                                break
                            logger.info(f"🔄 Novas mensagens no buffet para conv {conversation_id}, continuando loop.")
                except asyncio.TimeoutError:
                    logger.error(f"⏰ Timeout de 120s atingido para conv {conversation_id} (empresa {empresa_id}). Liberando lock.")
                finally:
                    # Libera lock atomicamente via Lua (só deleta se o valor ainda é nosso)
                    try:
                        await redis_client.eval(
                            "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end",
                            1, lock_key, lock_val
                        )
                        logger.debug(f"🔓 Lock liberado para conv {conversation_id}")
                    except Exception as _lock_err:
                        logger.warning(f"⚠️ Erro ao liberar lock para conv {conversation_id}: {_lock_err}")

            # [ARQ-05] Marca como processado ANTES do xack (evita janela de duplicacao)
            await _mark_processed(idempotency_key)
            await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
            await redis_client.xdel(STREAM_NAME, msg_id)

            if PROMETHEUS_OK:
                METRIC_WORKER_PROCESSED.labels(status="success").inc()
                METRIC_WORKER_LATENCY.observe(time.time() - _start)
        finally:
            _semaphore.release()

    except Exception as e:
        logger.error(f"stream_worker error msg_id={msg_id}: {type(e).__name__}: {e}", exc_info=True)
        if PROMETHEUS_OK:
            METRIC_WORKER_PROCESSED.labels(status="error").inc()
        # [ARQ-05] Em caso de erro, checa contagem de entregas (XPENDING).
        # Se ja passou do limite, move pra deadletter. Se nao, deixa sem ack para retry.
        try:
            pending_info = await redis_client.xpending_range(
                STREAM_NAME, CONSUMER_GROUP, min=msg_id, max=msg_id, count=1
            )
            delivery_count = pending_info[0]["times_delivered"] if pending_info else 1
            if delivery_count >= MAX_DELIVERY_COUNT:
                await _move_to_deadletter(msg_id, payload, f"max_retries_exceeded: {type(e).__name__}: {e}")
            else:
                logger.warning(f"[ARQ-05] msg {msg_id} sera re-entregue (tentativa {delivery_count}/{MAX_DELIVERY_COUNT})")
                # NAO da ack — o XPENDING garantira reentrega via XAUTOCLAIM
        except Exception as _pend_err:
            logger.error(f"[ARQ-05] erro ao consultar XPENDING: {_pend_err}")
            # Fallback conservador: ack para evitar loop infinito
            try:
                await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
            except Exception:
                pass


async def _claim_stale_messages() -> None:
    """[ARQ-06] Reclaim de mensagens 'pending' paradas em workers que cairam.
    Usa XAUTOCLAIM com min-idle-time de 2 minutos."""
    try:
        # XAUTOCLAIM foi adicionado em Redis 6.2. Retorna (next_cursor, claimed_msgs, deleted_ids)
        result = await redis_client.xautoclaim(
            name=STREAM_NAME,
            groupname=CONSUMER_GROUP,
            consumername=CONSUMER_NAME,
            min_idle_time=120_000,  # 2 minutos em ms
            count=10,
        )
        # Redis-py retorna tupla de (cursor, [claimed], [deleted])
        if isinstance(result, tuple) and len(result) >= 2:
            claimed = result[1]
            if claimed:
                logger.info(f"[ARQ-06] XAUTOCLAIM: reclaimed {len(claimed)} mensagens stuck")
                for item in claimed:
                    # item = (msg_id, payload_dict) dependendo da versao do redis-py
                    try:
                        msg_id_c, payload_c = item[0], item[1]
                        task = asyncio.create_task(_process_job(msg_id_c, payload_c))
                        _active_tasks.add(task)
                        task.add_done_callback(_active_tasks.discard)
                    except Exception as _ce:
                        logger.warning(f"[ARQ-06] falha ao processar claimed: {_ce}")
    except Exception as e:
        # Redis antigo pode nao ter XAUTOCLAIM — so logar
        if "unknown command" not in str(e).lower():
            logger.warning(f"[ARQ-06] xautoclaim falhou: {e}")


async def run_stream_worker():
    """Loop principal do worker que consome do Redis Streams com processamento concorrente."""
    global _trim_counter
    await init_stream()
    logger.info(f"stream_worker start consumer={CONSUMER_NAME} max_concurrent={MAX_CONCURRENT}")

    _last_claim = 0.0
    _last_heartbeat = 0.0

    while True:
        try:
            _now = time.time()

            # [INF-07] Heartbeat a cada 30s
            if _now - _last_heartbeat > 30:
                await _write_heartbeat()
                _last_heartbeat = _now

            if PROMETHEUS_OK:
                _size = await redis_client.xlen(STREAM_NAME)
                METRIC_QUEUE_SIZE.set(_size)

            # [ARQ-06] XAUTOCLAIM a cada 60s para mensagens paradas
            if _now - _last_claim > 60:
                await _claim_stale_messages()
                _last_claim = _now

            # Limpa tasks finalizadas
            _done = {t for t in _active_tasks if t.done()}
            for t in _done:
                try:
                    t.result()
                except Exception:
                    pass
            _active_tasks.difference_update(_done)

            # Lê até 5 mensagens por vez para processar em paralelo
            streams = await redis_client.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME, {STREAM_NAME: ">"}, count=5, block=5000
            )

            if not streams:
                continue

            for stream_name, messages in streams:
                for msg_id, payload in messages:
                    task = asyncio.create_task(_process_job(msg_id, payload))
                    _active_tasks.add(task)
                    task.add_done_callback(_active_tasks.discard)

                    # [ARQ-06] Trim do stream a cada 100 msgs
                    _trim_counter += 1
                    if _trim_counter >= 100:
                        _trim_counter = 0
                        try:
                            await redis_client.xtrim(STREAM_NAME, maxlen=STREAM_MAX_LEN, approximate=True)
                        except Exception as _te:
                            logger.warning(f"[ARQ-06] xtrim falhou: {_te}")

        except asyncio.CancelledError:
            if _active_tasks:
                logger.info(f"stream_worker shutdown aguardando {len(_active_tasks)} tasks...")
                await asyncio.gather(*_active_tasks, return_exceptions=True)
            break
        except Exception as e:
            logger.error(f"stream_worker loop_error: {type(e).__name__}: {e}")
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(run_stream_worker())
