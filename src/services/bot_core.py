from src.core.config import (
    logger, PROMETHEUS_OK, METRIC_WEBHOOKS_TOTAL, METRIC_IA_LATENCY,
    METRIC_FAST_PATH_TOTAL, METRIC_ERROS_TOTAL, METRIC_CONVERSAS_ATIVAS,
    METRIC_PLANOS_ENVIADOS, METRIC_ALUNO_DETECTADO,
    generate_latest, CONTENT_TYPE_LATEST,
    CHATWOOT_URL, CHATWOOT_TOKEN, CHATWOOT_WEBHOOK_SECRET,
    OPENROUTER_API_KEY, OPENAI_API_KEY, REDIS_URL, DATABASE_URL,
    EMPRESA_ID_PADRAO, APP_VERSION, APP_MODE,
)

import os
import io
import asyncio
import random
import re
import hmac
import hashlib
import logging
import httpx
import json
import base64
import uuid
import time
import zlib
import unicodedata
from decimal import Decimal
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any

import src.core.database as _database
from src.core.redis_client import redis_client, redis_get_json, redis_set_json
from src.utils.redis_helper import (
    get_tenant_cache, set_tenant_cache, delete_tenant_cache, exists_tenant_cache, get_tenant_key
)
from src.core.security import cb_llm
from src.utils.text_helpers import (
    normalizar, comprimir_texto, descomprimir_texto, limpar_nome,
    primeiro_nome_cliente, nome_eh_valido, extrair_nome_do_texto,
    limpar_markdown, randomizar_mensagem
)
from src.utils.intent_helpers import (
    SAUDACOES, eh_saudacao, eh_confirmacao_curta, classificar_intencao,
    _faq_compativel_com_intencao, garantir_frase_completa
)
from src.utils.time_helpers import (
    saudacao_por_horario, horario_hoje_formatado, formatar_horarios_funcionamento,
    esta_aberta_agora, ia_esta_no_horario
)
from src.services.llm_service import cliente_ia, cliente_whisper, is_provider_unavailable_error, is_openrouter_auth_error

from src.services.db_queries import (
    buscar_empresa_por_account_id, carregar_integracao, buscar_planos_ativos,
    buscar_planos_evo_da_api, sincronizar_planos_evo, formatar_planos_para_prompt,
    _is_worker_leader, listar_unidades_ativas, buscar_unidade_na_pergunta,
    carregar_unidade, carregar_personalidade, carregar_configuracao_global,
    log_db_error, bd_iniciar_conversa, bd_salvar_mensagem_local,
    bd_obter_historico_local, bd_atualizar_msg_cliente, bd_atualizar_msg_ia,
    bd_registrar_primeira_resposta, bd_registrar_evento_funil, bd_finalizar_conversa,
    _coletar_metricas_unidade, buscar_resposta_faq, carregar_faq_unidade, bd_atualizar_metricas_venda
)
from src.services.chatwoot_client import (
    simular_digitacao, formatar_mensagem_saida, suavizar_personalizacao_nome,
    atualizar_nome_contato_chatwoot, enviar_mensagem_chatwoot, validar_assinatura,
    escalar_para_humano,
)
from src.services.evo_client import verificar_status_membro_evo, criar_prospect_evo
import src.services.chatwoot_client as _chatwoot_module
from src.services.workers import (
    _log_worker_task_result, worker_sync_planos, sync_planos_manual,
    agendar_followups, worker_followup, worker_metricas_diarias, worker_resumo_ia
)
import src.services.workers as _workers_module
import src.services.uaz_client as _uaz_module
from src.services.uaz_client import UazAPIClient
from src.services.ia_processor import (
    # Constants
    ALUNO_KEYWORDS, GYMPASS_KEYWORDS, INTENCOES, USAR_CACHE_SEMANTICO,
    LUA_RELEASE_LOCK, REGEX_PEDIDO_PLANOS, REGEX_PEDIDO_END_HOR,
    REGEX_PEDIDO_CONTATO, REGEX_LISTAR_UNIDADES,
    RESPOSTAS_UNIDADES, RESPOSTAS_ENDERECO, RESPOSTAS_HORARIO, RESPOSTAS_CONTATO,
    whisper_semaphore, llm_semaphore,
    # Functions
    resolver_contexto_unidade, responder_horario, extrair_endereco_unidade,
    normalizar_lista_campo, extrair_telefone_unidade, responder_endereco,
    responder_telefone, responder_lista_unidades, responder_modalidades, gerar_resposta_inteligente,
    montar_saudacao_humanizada, detectar_tipo_cliente,
    _cosine_sim, _get_embedding, buscar_cache_semantico, salvar_cache_semantico,
    detectar_intencao, analisar_sentimento,
    carregar_memoria_cliente, formatar_memoria_para_prompt, extrair_memorias_da_conversa,
    truncar_contexto,
)
from src.services.model_router import escolher_modelo
from src.services.ab_testing import registrar_resultado_ab

# ── Módulos extraídos do bot_core (Phase 2 refactoring) ──────────────────────
from src.services.prompt_builder import (
    filtrar_planos_por_contexto, montar_prompt_sistema,
)
from src.services.message_formatter import (
    formatar_planos_bonito, dividir_em_blocos, processar_anexos_mensagens,
    extrair_json, corrigir_json, transcrever_audio, baixar_midia_com_retry,
    limpar_resposta_llm, garantir_frase_completa as _garantir_frase_completa,
)
from src.services.conversation_handler import (
    renovar_lock, coletar_mensagens_buffer,
    aguardar_escolha_unidade_ou_reencaminhar, resolver_contexto_atendimento,
    persistir_mensagens_usuario, monitorar_escolha_unidade,
)

from fastapi import FastAPI, Request, BackgroundTasks, Header, HTTPException, Response
from dotenv import load_dotenv
from openai import AsyncOpenAI
import redis.asyncio as redis
import asyncpg
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from rapidfuzz import fuzz


# ── Helper para tarefas async seguras ────────────────────────────────────────
def safe_create_task(coro, *, name: str = None):
    """Cria asyncio.Task com callback que loga exceções não tratadas."""
    task = asyncio.create_task(coro, name=name)
    task.add_done_callback(_safe_task_done)
    return task

def _safe_task_done(task: asyncio.Task):
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error(f"🔥 Exceção não tratada em task '{task.get_name()}': {type(exc).__name__}: {exc}")


# ── Middleware de Rate Limit Global ──────────────────────────────────────────
# Bloqueia IPs e empresas que abusem do endpoint /webhook
async def rate_limit_middleware(request: Request, call_next):
    """
    Rate limiting em duas camadas:
      1. Por IP  — máx 60 req/minuto   (anti-spam / DDoS básico)
      2. Por empresa — máx 300 req/minuto (anti-loop de webhook)
    Apenas para o endpoint /webhook. Outros endpoints passam livre.
    """
    if request.url.path != "/webhook" or not redis_client:
        return await call_next(request)

    try:
        await redis_client.ping()
    except Exception:
        return await call_next(request)

    async def _set_body(req: Request, b: bytes):
        async def receive():
            return {"type": "http.request", "body": b, "more_body": False}
        req._receive = receive

    client_ip = request.client.host if request.client else "unknown"

    # 1. Rate limit por IP
    ip_key     = f"rl:ip:{client_ip}"
    async with redis_client.pipeline(transaction=False) as pipe:
        pipe.incr(ip_key)
        pipe.expire(ip_key, 60)
        _ip_results = await pipe.execute()
    ip_count = _ip_results[0]
    if ip_count > 60:
        logger.warning(f"🚫 Rate limit por IP: {client_ip} ({ip_count} req/min)")
        if PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="rate_limit_ip").inc()
        from fastapi.responses import JSONResponse
        return JSONResponse({"status": "rate_limit_ip"}, status_code=429)

    # 2. Rate limit por empresa (lido do payload — extrai account_id sem ler 2x o body)
    try:
        body = await request.body()
        try:
            _payload = json.loads(body.decode() or "{}")
        except Exception:
            _payload = {}
        _account_id = _payload.get("account", {}).get("id")
        if _account_id:
            emp_key   = f"rl:account:{_account_id}"
            async with redis_client.pipeline(transaction=False) as pipe:
                pipe.incr(emp_key)
                pipe.expire(emp_key, 60)
                _emp_results = await pipe.execute()
            emp_count = _emp_results[0]
            if emp_count > 300:
                logger.warning(f"🚫 Rate limit por conta: account_id={_account_id} ({emp_count} req/min)")
                if PROMETHEUS_OK:
                    METRIC_ERROS_TOTAL.labels(tipo="rate_limit_account").inc()
                from fastapi.responses import JSONResponse
                return JSONResponse({"status": "rate_limit_account"}, status_code=429)
        # Devolve o body ao request para que o endpoint possa lê-lo normalmente
        await _set_body(request, body)
    except Exception:
        pass

    return await call_next(request)

worker_tasks: List[asyncio.Task] = []
is_shutting_down = False


async def startup_event():
    global worker_tasks, is_shutting_down
    is_shutting_down = False
    _workers_module.is_shutting_down = False

    await _database.init_db_pool()

    # Garante que tabelas do painel admin existam
    if _database.db_pool:
        try:
            await _database.db_pool.execute("""
                CREATE TABLE IF NOT EXISTS convites (
                    id SERIAL PRIMARY KEY,
                    empresa_id INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
                    email VARCHAR(255) NOT NULL,
                    token VARCHAR(64) NOT NULL UNIQUE,
                    usado BOOLEAN NOT NULL DEFAULT false,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL
                )
            """)
            await _database.db_pool.execute("CREATE INDEX IF NOT EXISTS ix_convites_token ON convites (token)")
            await _database.db_pool.execute("CREATE INDEX IF NOT EXISTS ix_convites_email ON convites (email)")
            logger.info("✅ Tabela 'convites' verificada/criada")
        except Exception as e:
            logger.error(f"❌ Erro ao criar tabela convites: {e}")

        # Corrige IDs de modelo inválidos que possam existir em registros antigos
        try:
            model_fixes = {
                "google/gemini-2.0-flash": "google/gemini-2.0-flash-001",
                "google/gemini-2.5-flash-preview": "google/gemini-2.5-flash",
                "google/gemini-pro": "google/gemini-2.0-flash-001",
            }
            for old_id, new_id in model_fixes.items():
                updated = await _database.db_pool.execute(
                    "UPDATE personalidade_ia SET modelo_preferido = $1 WHERE modelo_preferido = $2",
                    new_id, old_id
                )
                if updated != "UPDATE 0":
                    logger.info(f"🔧 Migração modelo: '{old_id}' → '{new_id}' ({updated})")
        except Exception as e:
            logger.error(f"❌ Erro ao migrar model IDs: {e}")

    _chatwoot_module.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        limits=httpx.Limits(max_keepalive_connections=20, max_connections=50)
    )
    _uaz_module.http_client = _chatwoot_module.http_client # Compartilhar o mesmo pool performático

    if OPENROUTER_API_KEY and cliente_ia:
        logger.info("🤖 OpenRouter habilitado (OPENROUTER_API_KEY carregada)")

    # Limpa cooldown de provedor no startup (destrava o bot se o usuário corrigiu a chave)
    async for key in redis_client.scan_iter("llm:provider_pause:*"):
        await redis_client.delete(key)

    logger.info(f"🚀 Iniciando Motor em modo: {APP_MODE.upper()}")

    if APP_MODE in ("worker", "both"):
        from src.services.stream_worker import run_stream_worker
        worker_tasks = [
            asyncio.create_task(worker_followup(), name="worker_followup"),
            asyncio.create_task(worker_metricas_diarias(), name="worker_metricas_diarias"),
            asyncio.create_task(worker_sync_planos(), name="worker_sync_planos"),
            asyncio.create_task(run_stream_worker(), name="stream_worker"),
            asyncio.create_task(worker_resumo_ia(), name="worker_resumo_ia"),
        ]
        for _task in worker_tasks:
            _task.add_done_callback(_log_worker_task_result)
    else:
        logger.info("⏭️  Modo API: Workers de background desativados neste processo.")

    # ⚠️  Os workers usam _worker_leader_check() internamente para garantir que
    # apenas UM processo execute em ambientes multi-worker (uvicorn --workers N).


async def shutdown_event():
    global is_shutting_down
    is_shutting_down = True
    _workers_module.is_shutting_down = True

    for task in worker_tasks:
        task.cancel()
    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        worker_tasks.clear()

    if _chatwoot_module.http_client:
        await _chatwoot_module.http_client.aclose()
    await redis_client.aclose()
    await _database.close_db_pool()
    logger.info("🛑 Servidor desligado.")


# ── Funções extraídas para módulos dedicados ─────────────────────────────────
# formatar_planos_bonito   → message_formatter.py
# filtrar_planos_por_contexto → prompt_builder.py
# renovar_lock             → conversation_handler.py
# dividir_em_blocos        → message_formatter.py
# coletar_mensagens_buffer → conversation_handler.py
# aguardar_escolha_unidade_ou_reencaminhar → conversation_handler.py
# processar_anexos_mensagens → message_formatter.py
# resolver_contexto_atendimento → conversation_handler.py
# persistir_mensagens_usuario → conversation_handler.py
# monitorar_escolha_unidade → conversation_handler.py
# extrair_json / corrigir_json → message_formatter.py
# transcrever_audio / baixar_midia_com_retry → message_formatter.py


async def despachar_resposta(
    account_id: int,
    conversation_id: int,
    content: str,
    nome_ia: str,
    integracao: dict,
    empresa_id: int,
    source: str = 'chatwoot',
    contato_fone: str = None,
    enviar_audio: bool = False,
    tts_voz: str = None
):
    """
    Despacha a resposta para o canal correto (Chatwoot ou UazAPI).
    Se enviar_audio=True e source=uazapi, também envia como áudio PTT.
    """
    if source == 'uazapi':
        # Para UazAPI, usamos o contato_fone (ou conversation_id como fallback)
        chat_id = contato_fone if contato_fone else str(conversation_id)

        uaz = UazAPIClient(integracao.get('url') or integracao.get('api_url'), integracao.get('token'), integracao.get('instance', 'default'))

        # Substitui proporção por um tempo de digitação rígido e "redondo" (solicitação do usuário)
        import random
        tempo_digitacao = random.choice([800, 1100, 1400, 1800])

        logger.info(f"📤 Despachando via UazAPI para {chat_id} (delay {tempo_digitacao}ms)")
        # Marca que o próximo fromMe=true nessa conversa é do BOT
        await set_tenant_cache(empresa_id, f"uaz_bot_sent_conv:{conversation_id}", "1", 120)
        if contato_fone:
            await redis_client.setex(f"uaz_bot_sent:{empresa_id}:{contato_fone}", 120, "1")

        # ── TTS: envia áudio PTT se cliente enviou áudio ──────────────
        if enviar_audio:
            logger.info(f"🔊 [TTS] Iniciando geração de áudio para {chat_id} (voz={tts_voz})")
            try:
                from src.services.tts_service import gerar_audio_resposta
                from src.utils.imagekit import upload_to_imagekit
                import uuid

                audio_bytes = await gerar_audio_resposta(content, voz=tts_voz)
                if audio_bytes:
                    logger.info(f"🔊 [TTS] Áudio gerado: {len(audio_bytes)} bytes, enviando para ImageKit...")
                    audio_url = await upload_to_imagekit(
                        audio_bytes,
                        f"tts_{uuid.uuid4().hex[:8]}.wav",
                        folder="/tts"
                    )
                    if audio_url:
                        ptt_ok = await uaz.send_ptt(chat_id, audio_url, delay=500)
                        if ptt_ok:
                            logger.info(f"🔊 [TTS] PTT enviado com sucesso: {audio_url}")
                        else:
                            logger.warning(f"⚠️ [TTS] send_ptt retornou False para {chat_id}")
                    else:
                        logger.warning(f"⚠️ [TTS] Upload ImageKit falhou — áudio não enviado")
                else:
                    logger.warning(f"⚠️ [TTS] gerar_audio_resposta retornou None (voz={tts_voz}, texto={len(content)} chars)")
            except Exception as e:
                logger.error(f"❌ [TTS] Erro TTS/PTT: {e}", exc_info=True)
                # Continua com envio de texto normalmente

        # Randomiza o conteúdo da mensagem de texto
        content_randomizado = randomizar_mensagem(content)
        res = await uaz.send_text(chat_id, content_randomizado, delay=tempo_digitacao)
        logger.info(f"✅ UazAPI Result: {res}")
        return res
    else:
        # ── TTS via Chatwoot → UazAPI: envia PTT antes do texto ──────────────
        if enviar_audio:
            logger.info(f"🔊 [TTS-CW] Iniciando TTS via Chatwoot→UazAPI conv={conversation_id} (voz={tts_voz})")
            try:
                from src.services.tts_service import gerar_audio_resposta
                from src.utils.imagekit import upload_to_imagekit
                import uuid

                # Busca integração UazAPI e telefone do cliente
                _uaz_integ = await carregar_integracao(empresa_id, 'uazapi')
                if _uaz_integ:
                    _fone = contato_fone
                    if not _fone:
                        _fone = await redis_client.get(f"fone_cliente:{conversation_id}")
                    if not _fone:
                        _row = await _database.db_pool.fetchrow(
                            "SELECT COALESCE(contato_fone, contato_telefone) AS fone FROM conversas WHERE conversation_id = $1",
                            conversation_id
                        )
                        _fone = _row['fone'] if _row else None

                    if _fone:
                        audio_bytes = await gerar_audio_resposta(content, voz=tts_voz)
                        if audio_bytes:
                            logger.info(f"🔊 [TTS-CW] Áudio gerado: {len(audio_bytes)} bytes")
                            audio_url = await upload_to_imagekit(
                                audio_bytes,
                                f"tts_{uuid.uuid4().hex[:8]}.wav",
                                folder="/tts"
                            )
                            if audio_url:
                                _uaz = UazAPIClient(
                                    _uaz_integ.get('url') or _uaz_integ.get('api_url'),
                                    _uaz_integ.get('token'),
                                    _uaz_integ.get('instance', 'default')
                                )
                                # Marca echo ANTES de enviar para evitar que Chatwoot pause a IA
                                await set_tenant_cache(empresa_id, f"uaz_bot_sent_conv:{conversation_id}", "1", 120)
                                if _fone:
                                    await redis_client.setex(f"uaz_bot_sent:{empresa_id}:{_fone}", 120, "1")
                                ptt_ok = await _uaz.send_ptt(str(_fone), audio_url, delay=500)
                                logger.info(f"🔊 [TTS-CW] PTT enviado: ok={ptt_ok} url={audio_url}")
                            else:
                                logger.warning(f"⚠️ [TTS-CW] Upload ImageKit falhou")
                        else:
                            logger.warning(f"⚠️ [TTS-CW] gerar_audio_resposta retornou None")
                    else:
                        logger.warning(f"⚠️ [TTS-CW] Telefone não encontrado para conv={conversation_id}")
                else:
                    logger.warning(f"⚠️ [TTS-CW] Sem integração UazAPI para empresa={empresa_id}")
            except Exception as e:
                logger.error(f"❌ [TTS-CW] Erro: {e}", exc_info=True)

        logger.info(f"📤 Despachando via Chatwoot conv={conversation_id} emp={empresa_id}")
        return await enviar_mensagem_chatwoot(
            account_id, conversation_id, content, integracao, empresa_id, nome_ia=nome_ia
        )


async def enviar_aviso_fora_horario(account_id: int, conversation_id: int, integracao: dict, empresa_id: int):
    """Envia uma mensagem automática educada se a IA for contatada fora do horário de atendimento."""
    chave_aviso = get_tenant_key(empresa_id, f"aviso_fora_horario:{conversation_id}")
    if await redis_client.get(chave_aviso):
        return
    
    mensagem = "Olá! 👋 No momento nossa IA está fora do horário de atendimento, mas sua mensagem foi recebida! Assim que voltarmos, responderemos com prioridade. Obrigado pela compreensão! ✨"
    try:
        await enviar_mensagem_chatwoot(account_id, conversation_id, mensagem, integracao, empresa_id)
        await redis_client.setex(chave_aviso, 3600, "1") # Silêncio de 1 hora para o mesmo aviso
    except Exception as e:
        logger.error(f"❌ Erro ao enviar aviso de fora de horário: {e}")

async def processar_ia_e_responder(
    account_id: int,
    conversation_id: int,
    contact_id: int,
    slug: str,
    nome_cliente: str,
    lock_val: str,
    empresa_id: int,
    integracao: dict,
    source: str = 'chatwoot',
    contato_fone: str = None
):
    logger.info(f"🧠 BotCore: processar_ia_e_responder conv={conversation_id} source={source} fone={contato_fone}")
    chave_lock = f"lock:{empresa_id}:{conversation_id}"
    chave_buffet = f"{empresa_id}:buffet:{conversation_id}"
    watchdog = asyncio.create_task(renovar_lock(chave_lock, lock_val))

    try:
        # ⏱️ Aguarda período para acumular rajada de mensagens (WhatsApp = msgs curtas em sequência)
        # Janela de 4s: captura rajadas típicas de WhatsApp (2-4 msgs em sequência)
        await asyncio.sleep(4.0)

        mensagens_acumuladas = await coletar_mensagens_buffer(conversation_id, empresa_id)
        if not mensagens_acumuladas:
            return

        # Pausa global da IA no Chatwoot por empresa (evita responder enquanto estiver desativada)
        if source == 'chatwoot' and await get_tenant_cache(empresa_id, "ia:chatwoot:paused") == "1":
            logger.info(f"⏸️ IA global Chatwoot pausada para empresa {empresa_id}; conv {conversation_id} ignorada")
            return

        # Verifica horário de atendimento da IA (prioriza cálculo direto do Banco de Dados)
        _pers_horario = await carregar_personalidade(empresa_id) or {}
        _horario_config = _pers_horario.get("horario_atendimento_ia")
        _db_esta_no_horario = _pers_horario.get("esta_no_horario", True)

        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        _agora_sp = _dt.now(_ZI("America/Sao_Paulo"))
        logger.info(
            f"🕒 [Bot Core] Horário SP={_agora_sp.strftime('%Y-%m-%d %H:%M:%S %Z')} | "
            f"DB_Check={_db_esta_no_horario} | Config: {_horario_config}"
        )

        # Decisão final baseada no Banco de Dados
        if not _db_esta_no_horario:
            _no_horario = False
        else:
            # Fallback para função Python caso o campo do banco falhe
            _no_horario = ia_esta_no_horario(_horario_config)

        logger.info(f"🕒 [Bot Core] Resultado Final Horário: {_no_horario}")
        if not _no_horario:
            logger.info(f"⏰ IA fora do horário de atendimento para empresa {empresa_id}; conv {conversation_id} ignorada (silencioso)")
            return

        if await aguardar_escolha_unidade_ou_reencaminhar(conversation_id, empresa_id, mensagens_acumuladas):
            return

        anexos = await processar_anexos_mensagens(mensagens_acumuladas)
        textos = anexos["textos"]
        transcricoes = anexos["transcricoes"]
        imagens_urls = anexos["imagens_urls"]
        mensagens_formatadas = anexos["mensagens_formatadas"]

        # ── GARANTIA DE PERSISTÊNCIA: Salva assim que coleta do buffer ────────
        await persistir_mensagens_usuario(conversation_id, empresa_id, textos, transcricoes)
        # ──────────────────────────────────────────────────────────────────────

        # ── ANÁLISE DE SENTIMENTO + AUTO-ESCALAÇÃO ───────────────────────────
        _todas_msgs_texto = textos + list(transcricoes)
        if _todas_msgs_texto:
            _sentimento = await analisar_sentimento(_todas_msgs_texto, empresa_id, conversation_id)
            if _sentimento.get("escalar"):
                logger.warning(f"🚨 Escalação automática: conv {conversation_id} ({_sentimento['motivo']})")
                _integ_cw = await carregar_integracao(empresa_id, 'chatwoot')
                if _integ_cw:
                    _nome_ia = (await carregar_personalidade(empresa_id) or {}).get("nome_ia", "Assistente")
                    await escalar_para_humano(
                        account_id, conversation_id, empresa_id,
                        _integ_cw, motivo=_sentimento["motivo"], nome_ia=_nome_ia
                    )
                    await bd_registrar_evento_funil(
                        conversation_id, empresa_id,
                        "escalacao_sentimento", _sentimento["motivo"], score_incremento=0
                    )
                    return  # IA para de responder, atendente humano assume
        # ──────────────────────────────────────────────────────────────────────

        # ── Anti-duplicata: bloqueia reprocessamento do mesmo conteúdo ──────────
        # O drain loop pode recolocar mensagens no buffer após o processamento.
        # Se o hash das mensagens atuais é igual ao que foi respondido nos últimos
        # 2 minutos, descarta silenciosamente — a resposta já foi enviada.
        _hash_msgs = hashlib.md5(mensagens_formatadas.encode()).hexdigest()
        _ultima_resp_key = get_tenant_key(empresa_id, f"last_ai_msg:{conversation_id}")
        _ultima_resp_hash = await redis_client.get(_ultima_resp_key)
        if _ultima_resp_hash and _ultima_resp_hash == _hash_msgs:
            logger.info(f"⏭️ Anti-duplicata: mensagens já respondidas, descartando conv {conversation_id}")
            return

        contexto = await resolver_contexto_atendimento(
            conversation_id=conversation_id,
            textos=textos,
            transcricoes=transcricoes,
            slug=slug,
            empresa_id=empresa_id,
        )
        slug = contexto["slug"]
        mudou_unidade = contexto["mudou_unidade"]
        primeira_mensagem = contexto["primeira_mensagem"]

        unidade = await carregar_unidade(slug, empresa_id) or {}
        pers = await carregar_personalidade(empresa_id) or {}
        nome_ia = pers.get('nome_ia') or 'Assistente Virtual'

        # ── DETECÇÃO DE NOME DO CLIENTE ──────────────────────────────
        # IA pergunta o nome na conversa. Quando o cliente responde,
        # detectamos aqui e salvamos no Redis + Chatwoot.
        _nome_já_salvo = await redis_client.get(f"nome_cliente:{empresa_id}:{conversation_id}")
        if not _nome_já_salvo:
            for _txt in (textos + transcricoes):
                _nome_det = extrair_nome_do_texto(_txt)
                if _nome_det:
                    await redis_client.setex(f"nome_cliente:{empresa_id}:{conversation_id}", 86400, _nome_det)
                    nome_cliente = _nome_det
                    logger.info(f"📝 Nome detectado e salvo: '{_nome_det}' (conv {conversation_id})")
                    # Atualiza nome no Chatwoot
                    _integ_cw = await carregar_integracao(empresa_id, 'chatwoot')
                    if _integ_cw and contact_id:
                        await atualizar_nome_contato_chatwoot(account_id, contact_id, _nome_det, _integ_cw)
                    break
        else:
            nome_cliente = _nome_já_salvo

        if not nome_eh_valido(nome_cliente):
            nome_cliente = "Cliente"
        # ─────────────────────────────────────────────────────────────

        estado_raw = await get_tenant_cache(empresa_id, f"estado:{conversation_id}")
        estado_atual = (descomprimir_texto(estado_raw) if estado_raw else None) or "neutro"

        # ── INTEGRAÇÃO EVO: Verificação de Membro ─────────────────────
        status_evo = {"is_aluno": False, "status": "lead"}
        if contato_fone:
            status_evo = await verificar_status_membro_evo(contato_fone, empresa_id, unidade.get('id'))
        
        ctx_aluno = ""
        if status_evo.get("is_aluno"):
            ctx_aluno = f"[SISTEMA: O cliente é um ALUNO {status_evo['status'].upper()}. Nome na EVO: {status_evo['nome']}. Trate-o como aluno e se ele tiver dúvidas de treino/financeiro peça para usar o App EVO.]"
        else:
            ctx_aluno = "[SISTEMA: O cliente NÃO é aluno (é um LEAD/PROSPECT). O foco é conversão e tirar dúvidas básicas.]"
        # ─────────────────────────────────────────────────────────────

        texto_norm_fast = normalizar(primeira_mensagem or "")
        resposta_texto = ""
        novo_estado = estado_atual
        fast_reply = None          # str  — mensagem única (resposta fixa, sem LLM)
        fast_reply_lista = None   # List[str] — múltiplas mensagens (ex: planos)
        contexto_precarregado = ""  # Dados buscados do BD — LLM gera a resposta humanizada
        intencao_motor = None
        _resposta_foi_truncada = False

        # Fast-path desativado: sempre seguir pelo fluxo FAQ + IA.
        texto_cliente_unificado = " ".join([t for t in (textos + transcricoes) if t]).strip()
        if texto_cliente_unificado and not imagens_urls:
            intencao_motor = detectar_intencao(texto_cliente_unificado)

        # Campos da unidade
        end_banco = extrair_endereco_unidade(unidade)
        hor_banco = unidade.get('horarios')
        _raw_link = unidade.get('link_matricula') or ''
        link_mat = _raw_link if _raw_link.startswith('http') else (unidade.get('site') if (unidade.get('site') or '').startswith('http') else '')
        tel_banco = extrair_telefone_unidade(unidade)

        # Planos ativos
        planos_ativos = await buscar_planos_ativos(empresa_id, unidade.get('id'), force_sync=True)
        if planos_ativos:
            _link_venda = planos_ativos[0].get('link_venda') or ''
            link_plano = _link_venda if _link_venda.startswith('http') else link_mat
        else:
            link_plano = link_mat

        # Fast-path desativado conforme regra de negócio.


        # Cache: usa chave por intenção APENAS para intenções factuais/estáveis.
        # Nunca usar cache por intenção para "llm"/"saudacao", senão uma resposta
        # genérica (ex: boas-vindas) pode ser repetida para perguntas diferentes.
        intencao = intencao_motor or (detectar_intencao(primeira_mensagem) if primeira_mensagem else None)
        _texto_cliente_norm = normalizar(texto_cliente_unificado or "")
        _intencao_compra = bool(re.search(
            r"(vou querer|quero (esse|este|fechar|contratar|assinar)|manda(r)? (o )?link|pode mandar o link|poderia mandar o link|tenho interesse|gostei desse preco|gostei desse preço|vamos fechar|quero me matricular)",
            _texto_cliente_norm,
        ))
        _quer_todos_planos = bool(re.search(
            r"(fora o plano|alem do prime|além do prime|outro plano|outros planos|quais planos|todos os planos|opcoes de plano|opções de plano|saber dos planos|quero ver planos|me fala dos planos)",
            _texto_cliente_norm,
        ))
        if planos_ativos and intencao in {"planos", "preco"}:
            _planos_filtrados = filtrar_planos_por_contexto(texto_cliente_unificado, planos_ativos)
            fast_reply_lista = formatar_planos_bonito(_planos_filtrados, destacar_melhor_preco=True)
            logger.info(f"⚡ Planos: envio em blocos ({len(_planos_filtrados)} planos)")

        # Pré-carrega slug para buscar unidade na pergunta de modalidades (sem fast_reply)
        if intencao == "modalidades":
            slug_modalidades = await buscar_unidade_na_pergunta(texto_cliente_unificado, empresa_id, fuzzy_threshold=82)
            if slug_modalidades and slug_modalidades != slug:
                slug = slug_modalidades
                await set_tenant_cache(empresa_id, f"unidade_escolhida:{conversation_id}", slug, 86400)

        # Pré-carrega horário com status aberta/fechada quando intenção é horário
        if intencao == "horario" and hor_banco:
            horarios_formatados = formatar_horarios_funcionamento(hor_banco)
            _aberta, _hor_hoje = esta_aberta_agora(hor_banco)
            _nome_unid = unidade.get('nome') or 'da unidade'
            if _aberta is True:
                _status_ctx = f"✅ A unidade está ABERTA agora. Horário de hoje: {_hor_hoje}"
            elif _aberta is False:
                _status_ctx = f"❌ A unidade está FECHADA no momento. Horário de hoje: {_hor_hoje}"
            else:
                _status_ctx = "Status de funcionamento não determinado."
            contexto_precarregado = (
                f"Horários de funcionamento — {_nome_unid}:\n{horarios_formatados}\n\n{_status_ctx}"
            )
            logger.info(f"📋 Horário + status pré-carregado: {_status_ctx}")

        _intencoes_cacheaveis = {
            "horario", "endereco"
        }
        _usa_cache_por_intencao = bool(intencao and intencao in _intencoes_cacheaveis)

        if _usa_cache_por_intencao:
            chave_cache_ia = f"cache:intent:{empresa_id}:{slug}:{intencao}"
        else:
            hash_pergunta = hashlib.md5(texto_norm_fast.encode('utf-8')).hexdigest()
            chave_cache_ia = f"cache:ia:{empresa_id}:{slug}:{hash_pergunta}"

        # Quando há dados pré-carregados do BD, bypassa cache completamente:
        # os dados são ao vivo (endereço/horário podem ter mudado) e o LLM precisa
        # gerar uma resposta humanizada nova — não uma resposta cacheada de outra conversa.
        if contexto_precarregado:
            resposta_cacheada = None
        else:
            resposta_cacheada = await redis_client.get(chave_cache_ia)

        # Cache semântico (embedding) — consultado apenas se não houver cache exato nem contexto live
        _cache_sem = None
        if USAR_CACHE_SEMANTICO and intencao == "llm" and not resposta_cacheada and not fast_reply and not contexto_precarregado and not imagens_urls and not mudou_unidade and primeira_mensagem:
            _cache_sem = await buscar_cache_semantico(primeira_mensagem, slug, empresa_id)

        if fast_reply:
            logger.info("⚡ Fast-Path Ativado! Respondendo sem IA.")
            resposta_texto = fast_reply
            novo_estado = estado_atual

        elif resposta_cacheada and not imagens_urls and not mudou_unidade:
            logger.info("🧠 Cache Hash HIT! Respondendo direto do Redis.")
            dados_cache = json.loads(resposta_cacheada)
            resposta_texto = dados_cache["resposta"]
            novo_estado = dados_cache["estado"]

            # Proteção anti-loop: se a resposta cacheada parece saudação, só use
            # quando a mensagem atual também for saudação.
            _msg_eh_saudacao = eh_saudacao(primeira_mensagem or "")
            _resp_norm = normalizar(resposta_texto or "")
            _resp_parece_saudacao = any(
                s in _resp_norm for s in [
                    "como posso te ajudar", "bem-vindo", "eu sou o", "eu sou a"
                ]
            )
            if _resp_parece_saudacao and not _msg_eh_saudacao:
                logger.info("⏭️ Cache ignorado: resposta de saudação para pergunta não-saudação")
                resposta_texto = ""

        elif _cache_sem and not imagens_urls and not mudou_unidade:
            logger.info("🧬 Cache Semântico HIT! Respondendo por similaridade.")
            resposta_texto = _cache_sem["resposta"]
            novo_estado = _cache_sem.get("estado", estado_atual)

        else:
            # --- FLUXO IA --- (prompt building delegado ao prompt_builder)
            _prompt_result = await montar_prompt_sistema(
                pers=pers,
                unidade=unidade,
                slug=slug,
                empresa_id=empresa_id,
                conversation_id=conversation_id,
                contato_fone=contato_fone,
                estado_atual=estado_atual,
                ctx_aluno=ctx_aluno,
                contexto_precarregado=contexto_precarregado,
                primeira_mensagem=primeira_mensagem,
                texto_cliente_unificado=texto_cliente_unificado,
                mensagens_formatadas=mensagens_formatadas,
                intencao=intencao,
                planos_ativos=planos_ativos,
                source=source,
            )
            prompt_sistema = _prompt_result["prompt_sistema"]
            todas_unidades = _prompt_result["todas_unidades"]
            _ab_info = _prompt_result["ab_info"]


            conteudo_usuario = []
            for img_url in imagens_urls:
                try:
                    # Headers de auth variam por fonte: Chatwoot usa api_access_token, UazAPI sem auth
                    _img_headers = {}
                    if source == "chatwoot":
                        _cw_token = integracao.get("token") or integracao.get("access_token") or ""
                        if _cw_token:
                            _img_headers = {"api_access_token": _cw_token}

                    resp = await baixar_midia_com_retry(
                        img_url,
                        timeout=12.0,
                        headers=_img_headers if _img_headers else None,
                    )

                    # Detecta content-type real da imagem
                    _ct = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                    if _ct not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                        _ct = "image/jpeg"

                    img_b64 = base64.b64encode(resp.content).decode("utf-8")
                    conteudo_usuario.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{_ct};base64,{img_b64}"}
                    })
                    logger.info(f"🖼️ Imagem carregada para LLM: {img_url[:60]}... ({_ct})")
                except Exception as e:
                    logger.error(f"Erro ao baixar imagem para LLM: {e}")

            # Multi-Model Routing — escolhe modelo por intenção/complexidade
            total_msgs_cliente = len(textos) + len(list(transcricoes))
            _modelo_pers = pers.get("model_name") or pers.get("modelo_preferido") or None
            modelo_escolhido = escolher_modelo(
                intencao=intencao,
                texto_cliente=texto_cliente_unificado or primeira_mensagem or "",
                modelo_personalidade=_modelo_pers,
                tem_imagens=bool(imagens_urls),
                total_mensagens=total_msgs_cliente,
            )

            temperature = float(pers.get("temperature") or pers.get("temperatura") or 0.7)
            max_tokens = int(pers.get("max_tokens") or 800)

            # ── Guard de cota do provedor LLM (cooldown) ─────────────────────
            llm_provider_pause_key = f"llm:provider_pause:{empresa_id}"
            if await redis_client.get(llm_provider_pause_key) == "1":
                resposta_texto = (
                    "Agora estamos com alto volume no atendimento automático 😕\n\n"
                    "Se quiser, me manda sua dúvida em uma frase curta que priorizo aqui pra você."
                )
                novo_estado = estado_atual
                goto_send = True
            else:
                goto_send = False

            # ── Circuit Breaker check ─────────────────────────────────────────
            if not goto_send:
                _cb_allowed = await cb_llm.is_allowed()
            else:
                _cb_allowed = True

            if not goto_send and not _cb_allowed:
                logger.warning(f"🔴 CircuitBreaker OPEN — usando resposta padrão para conv {conversation_id}")
                # Resposta de fallback quando LLM está indisponível
                resposta_texto = (
                    "Olá! 😊 Estou com uma lentidão no momento.\n\n"
                    "Pode me repetir sua dúvida em instantes? Já vou te atender! 💪"
                )
                novo_estado = estado_atual
                # Pula o bloco IA e vai direto para envio
                goto_send = True
            if not goto_send:
                if not cliente_ia:
                    resposta_texto = "Estou temporariamente sem conexão com a IA. Pode tentar novamente em instantes? 😊"
                    novo_estado = estado_atual
                    goto_send = True

            if not goto_send:
                # ── Chamada ao LLM com timeout global + circuit breaker ───────────
                start_time = time.time()


                # Monta conteúdo do role "user"
                if conteudo_usuario:
                    conteudo_usuario.append({"type": "text", "text": mensagens_formatadas})
                    user_content = conteudo_usuario
                else:
                    user_content = mensagens_formatadas

                async def _chamar_llm(model_id: str, extra_timeout: int = 25):
                        if max_tokens:
                            logger.info(f"🔢 LLM: Enviando max_tokens={max_tokens} para {model_id}")
                        
                        return await asyncio.wait_for(
                            cliente_ia.chat.completions.create(
                            model=model_id,
                            messages=[
                                {"role": "system", "content": prompt_sistema},
                                {"role": "user", "content": user_content}
                            ],
                            temperature=temperature,
                            max_tokens=max_tokens,
                        ),
                        timeout=extra_timeout
                    )

                async with llm_semaphore:
                    try:
                        logger.info(f"📡 BotCore: Chamando LLM ({modelo_escolhido}) para conv {conversation_id}")
                        response = await _chamar_llm(modelo_escolhido, extra_timeout=25)
                        resposta_bruta = response.choices[0].message.content
                        if resposta_bruta:
                            logger.info(f"✅ LLM: Resposta recebida ({len(resposta_bruta)} chars). Final: '{resposta_bruta[-20:]}'")
                        await cb_llm.record_success()

                    except asyncio.TimeoutError:
                        logger.warning(f"⏱️ Timeout LLM (25s) — tentando fallback. Conv {conversation_id}")
                        await cb_llm.record_failure()
                        if PROMETHEUS_OK:
                            METRIC_ERROS_TOTAL.labels(tipo="llm_timeout").inc()
                        try:
                            modelo_fallback = "google/gemini-2.5-flash" if imagens_urls else "google/gemini-2.5-flash-lite"
                            response = await _chamar_llm(modelo_fallback, extra_timeout=20)
                            resposta_bruta = response.choices[0].message.content
                            await cb_llm.record_success()
                        except asyncio.TimeoutError:
                            logger.error(f"❌ Timeout no fallback também. Conv {conversation_id}")
                            await cb_llm.record_failure()
                            resposta_bruta = json.dumps({
                                "resposta": "Estou com uma lentidão agora 😕 Pode tentar novamente em instantes?",
                                "estado": estado_atual
                            })
                        except Exception as e2:
                            if is_provider_unavailable_error(e2):
                                logger.warning("⚠️ Fallback de IA indisponível temporariamente")
                                await redis_client.setex(llm_provider_pause_key, 300, "1")
                            else:
                                logger.error("❌ Erro no fallback")
                            await cb_llm.record_failure()
                            resposta_bruta = json.dumps({
                                "resposta": "Estamos com alto volume de atendimentos agora 😕 Pode tentar novamente em instantes?",
                                "estado": estado_atual
                            })

                    except Exception as e:
                        erro_provedor = is_provider_unavailable_error(e)
                        if erro_provedor:
                            logger.warning("⚠️ IA indisponível temporariamente (OpenRouter)")
                            await redis_client.setex(llm_provider_pause_key, 300, "1")
                        elif is_openrouter_auth_error(e):
                            logger.warning("⚠️ Falha de autenticação OpenRouter (verifique OPENROUTER_API_KEY)")
                            await redis_client.setex(llm_provider_pause_key, 600, "1")
                        else:
                            logger.warning("⚠️ Erro LLM primário — tentando fallback")
                        await cb_llm.record_failure()
                        if PROMETHEUS_OK:
                            METRIC_ERROS_TOTAL.labels(tipo="llm_fallback").inc()

                        if erro_provedor:
                            await redis_client.setex(llm_provider_pause_key, 300, "1")
                            resposta_bruta = json.dumps({
                                "resposta": "Estamos com alto volume de atendimentos agora 😕 Pode tentar novamente em instantes?",
                                "estado": estado_atual
                            })
                        else:
                            try:
                                modelo_fallback = "google/gemini-2.5-flash" if imagens_urls else "google/gemini-2.5-flash-lite"
                                response = await _chamar_llm(modelo_fallback, extra_timeout=20)
                                resposta_bruta = response.choices[0].message.content
                                await cb_llm.record_success()
                            except Exception as e2:
                                if is_provider_unavailable_error(e2):
                                    logger.warning("⚠️ Fallback de IA indisponível temporariamente")
                                    await redis_client.setex(llm_provider_pause_key, 300, "1")
                                else:
                                    logger.error("❌ Fallback também falhou")
                                await cb_llm.record_failure()
                                resposta_bruta = json.dumps({
                                    "resposta": "Estamos com alto volume de atendimentos agora 😕 Pode tentar novamente em instantes?",
                                    "estado": estado_atual
                                })

                _latencia = time.time() - start_time
                logger.info(f"⏱️ LLM Latency: {_latencia:.2f}s")
                if PROMETHEUS_OK:
                    METRIC_IA_LATENCY.observe(_latencia)

            if not goto_send:
                # ── Limpeza e processamento da resposta (delegado ao message_formatter) ──
                _resp_result = limpar_resposta_llm(resposta_bruta, estado_atual)
                resposta_texto = _resp_result["resposta_texto"]
                novo_estado = _resp_result["novo_estado"]

                # Envio cross-unit: <SEND_IMAGE:slug> — mídia de outra unidade da rede
                _cross_img_match = re.search(r'<SEND_IMAGE:([^>]+)>', resposta_texto)
                if _cross_img_match:
                    _target_slug = _cross_img_match.group(1).strip()
                    _target_unit = next((u for u in todas_unidades if u.get('slug') == _target_slug), None)
                    _cross_foto = _target_unit.get('foto_grade') if _target_unit else None
                    resposta_texto = re.sub(r'<SEND_IMAGE:[^>]+>', '', resposta_texto).strip()
                    if _cross_foto and _target_unit:
                        try:
                            await enviar_mensagem_chatwoot(
                                account_id, conversation_id,
                                f"Enviando a grade da unidade *{_target_unit.get('nome')}*... 🖼️",
                                integracao, empresa_id, nome_ia=nome_ia,
                                contact_id=contact_id, source=source, fone=contato_fone
                            )
                            await asyncio.sleep(random.uniform(1.5, 3.5))
                            await enviar_mensagem_chatwoot(
                                account_id, conversation_id, _cross_foto, integracao,
                                empresa_id, nome_ia=nome_ia, contact_id=contact_id, source=source, fone=contato_fone,
                                is_direct_url=True
                            )
                        except Exception as e:
                            logger.error(f"Erro ao enviar imagem cross-unit ({_target_slug}): {e}")

                # Envio cross-unit: <SEND_VIDEO:slug> — tour virtual de outra unidade
                _cross_vid_match = re.search(r'<SEND_VIDEO:([^>]+)>', resposta_texto)
                if _cross_vid_match:
                    _target_slug_v = _cross_vid_match.group(1).strip()
                    _target_unit_v = next((u for u in todas_unidades if u.get('slug') == _target_slug_v), None)
                    _cross_tour = _target_unit_v.get('link_tour_virtual') if _target_unit_v else None
                    resposta_texto = re.sub(r'<SEND_VIDEO:[^>]+>', '', resposta_texto).strip()
                    if _cross_tour and _target_unit_v:
                        try:
                            await enviar_mensagem_chatwoot(
                                account_id, conversation_id,
                                f"Vou te enviar um vídeo da unidade *{_target_unit_v.get('nome')}* por dentro! 🎥",
                                integracao, empresa_id, nome_ia=nome_ia,
                                contact_id=contact_id, source=source, fone=contato_fone
                            )
                            await asyncio.sleep(random.uniform(2.0, 4.5))
                            await enviar_mensagem_chatwoot(
                                account_id, conversation_id, _cross_tour, integracao,
                                empresa_id, nome_ia=nome_ia, contact_id=contact_id, source=source, fone=contato_fone,
                                is_direct_url=True
                            )
                        except Exception as e:
                            logger.error(f"Erro ao enviar vídeo cross-unit ({_target_slug_v}): {e}")

                # Se a IA usou a tag <SEND_IMAGE> e temos a URL
                _foto_grade = unidade.get("foto_grade")
                if "<SEND_IMAGE>" in resposta_texto:
                    if _foto_grade:
                        resposta_texto = resposta_texto.replace("<SEND_IMAGE>", "").strip()
                        try:
                            await enviar_mensagem_chatwoot(
                                account_id, conversation_id,
                                f"Enviando a grade da unidade *{unidade.get('nome')}*... 🖼️",
                                integracao, empresa_id,
                                nome_ia=nome_ia,
                                contact_id=contact_id, source=source, fone=contato_fone
                            )
                            await asyncio.sleep(random.uniform(1.5, 3.5))
                            await enviar_mensagem_chatwoot(
                                account_id, conversation_id,
                                _foto_grade,
                                integracao, empresa_id,
                                nome_ia=nome_ia,
                                contact_id=contact_id, source=source, fone=contato_fone,
                                is_direct_url=True
                            )
                        except Exception as e:
                            logger.error(f"Erro ao enviar imagem da grade: {e}")
                    else:
                        resposta_texto = resposta_texto.replace("<SEND_IMAGE>", "").strip()

                # Se a IA usou a tag <SEND_VIDEO> e temos a URL
                _link_tour = unidade.get("link_tour_virtual")
                if "<SEND_VIDEO>" in resposta_texto:
                    if _link_tour:
                        resposta_texto = resposta_texto.replace("<SEND_VIDEO>", "").strip()
                        try:
                            await enviar_mensagem_chatwoot(
                                account_id, conversation_id,
                                f"Vou te enviar um vídeo mostrando nossa unidade por dentro! 🎥",
                                integracao, empresa_id,
                                nome_ia=nome_ia,
                                contact_id=contact_id, source=source, fone=contato_fone
                            )
                            await asyncio.sleep(random.uniform(2.0, 4.5))
                            await enviar_mensagem_chatwoot(
                                account_id, conversation_id,
                                _link_tour,
                                integracao, empresa_id,
                                nome_ia=nome_ia,
                                contact_id=contact_id, source=source, fone=contato_fone,
                                is_direct_url=True
                            )
                        except Exception as e:
                            logger.error(f"Erro ao enviar vídeo do tour: {e}")
                    else:
                        resposta_texto = resposta_texto.replace("<SEND_VIDEO>", "").strip()

                if _intencao_compra and link_plano and link_plano.startswith('http'):
                    _resp_norm_compra = normalizar(resposta_texto or "")
                    _tem_link = ("http://" in (resposta_texto or "")) or ("https://" in (resposta_texto or ""))
                    if not _tem_link:
                        _base = resposta_texto.strip() if resposta_texto and resposta_texto.strip() else "Perfeito! Vamos fechar agora 🚀"
                        resposta_texto = (
                            f"{_base}\n\n"
                            f"🔗 Para garantir sua matrícula agora: {link_plano}\n\n"
                            "Se quiser, também te mostro *outros planos* para você comparar rapidinho."
                        )
                    elif "outros planos" not in _resp_norm_compra:
                        resposta_texto = (
                            f"{resposta_texto.rstrip()}\n\n"
                            "Se quiser, também te mostro *outros planos* para você comparar rapidinho."
                        )
                    novo_estado = "conversao"

                if not imagens_urls and resposta_texto:
                    _cache_payload = json.dumps({"resposta": resposta_texto, "estado": novo_estado})
                    # Não persiste cache para saudações curtas para evitar repetição
                    # em consultas futuras de conteúdo diferente.
                    _mensagem_eh_saudacao = eh_saudacao(primeira_mensagem or "")
                    if not _mensagem_eh_saudacao:
                        await redis_client.setex(chave_cache_ia, 600, _cache_payload)

                    if USAR_CACHE_SEMANTICO and primeira_mensagem and not _mensagem_eh_saudacao:
                        await salvar_cache_semantico(
                            primeira_mensagem, slug,
                            {"resposta": resposta_texto, "estado": novo_estado},
                            ttl=3600
                        )

                link_enviado = bool(link_plano in resposta_texto)
                intencao = link_enviado or "matricular" in resposta_texto.lower()
                
                if intencao:
                    await bd_registrar_evento_funil(
                        conversation_id, empresa_id, "link_matricula_enviado", "Link enviado via IA", score_incremento=2
                    )
                    await bd_atualizar_metricas_venda(
                        conversation_id, empresa_id, link_venda_enviado=link_enviado, intencao_de_compra=intencao
                    )
                    
                if tel_banco and tel_banco in resposta_texto:
                    await bd_registrar_evento_funil(
                        conversation_id, empresa_id, "solicitacao_telefone", "IA forneceu telefone", score_incremento=3
                    )

        # --- Salvar estado ---
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.setex(f"estado:{empresa_id}:{conversation_id}", 86400, comprimir_texto(novo_estado))
            pipe.lpush(
                f"hist_estado:{empresa_id}:{conversation_id}",
                f"{datetime.now(ZoneInfo('America/Sao_Paulo')).isoformat()}|{novo_estado}"
            )
            pipe.ltrim(f"hist_estado:{empresa_id}:{conversation_id}", 0, 10)
            pipe.expire(f"hist_estado:{empresa_id}:{conversation_id}", 86400)
            await pipe.execute()

        _nome_valido = bool(nome_cliente and not any(p in (nome_cliente or "").lower() for p in ["cliente", "whatsapp", "lead"]))
        _trigger_crm = any(k in novo_estado for k in ("conversao", "matricula")) or \
                      (_nome_valido and novo_estado == "interessado")

        if _trigger_crm:
            # ── INTEGRAÇÃO EVO: Criar Prospect se não for aluno e for estratégico ──
            if not status_evo.get("is_aluno"):
                # Verifica se JÁ existe um prospect_id_evo para este telefone em QUALQUER conversa
                _ja_prospect = await _database.db_pool.fetchval(
                    "SELECT prospect_id_evo FROM conversas WHERE contato_fone = $1 AND prospect_id_evo IS NOT NULL LIMIT 1",
                    contato_fone
                )
                
                if not _ja_prospect:
                    await bd_registrar_evento_funil(
                        conversation_id, empresa_id, "interesse_detectado", f"Estado: {novo_estado}"
                    )
                    lead_data = {
                        "name": nome_cliente,
                        "cellphone": contato_fone,
                        "notes": f"Interesse estratégico detectado via IA (Estado: {novo_estado})",
                        "temperature": 1 if novo_estado == "interessado" else 2
                    }
                    
                    async def _criar_e_registrar():
                        res_id = await criar_prospect_evo(empresa_id, unidade.get('id'), lead_data)
                        if res_id and not isinstance(res_id, bool):
                            # Salva o ID do prospect na conversa atual para evitar duplicidade futura
                            await _database.db_pool.execute(
                                "UPDATE conversas SET prospect_id_evo = $1 WHERE conversation_id = $2",
                                res_id, conversation_id
                            )
                            logger.info(f"💾 Prospect ID {res_id} registrado para conv {conversation_id}")
                    
                    safe_create_task(_criar_e_registrar(), name="criar_prospect_evo")
                else:
                    logger.debug(f"⏭️ Prospect já existe para {contato_fone} (ID: {_ja_prospect}). Pulando criação.")
            # ─────────────────────────────────────────────────────────────

        salvar_resposta_unica = bool(resposta_texto and resposta_texto.strip() and not fast_reply_lista)
        if salvar_resposta_unica:
            await bd_salvar_mensagem_local(conversation_id, empresa_id, "assistant", resposta_texto)

        # Registra resultado do A/B testing (se ativo)
        if _ab_info:
            try:
                safe_create_task(registrar_resultado_ab(
                    teste_id=_ab_info["teste_id"],
                    conversa_id=conversation_id,
                    variante=_ab_info["variante"],
                    lead_qualificado=bool(novo_estado in ("interessado", "conversao", "matricula")),
                    intencao_compra=bool("matricula" in (novo_estado or "") or "conversao" in (novo_estado or "")),
                    score_lead=0,
                    msgs_total=total_msgs_cliente,
                ), name="registrar_ab")
            except Exception:
                pass

        is_manual = (await redis_client.get(f"atend_manual:{empresa_id}:{conversation_id}")) == "1"

        if is_manual or await redis_client.exists(f"pause_ia:{empresa_id}:{conversation_id}"):
            pass  # IA pausada, não envia

        else:
            # Buscar telefone para UazAPI se ainda não tivermos (shadowing fixed)
            if source == 'uazapi' and not contato_fone:
                from src.services.db_queries import buscar_conversa_por_fone
                # Como conversation_id pode ser fake/negativo na UazAPI, usamos o Redis ou DB
                # Se não veio via parâmetro, busca no BD como fallback
                row = await _database.db_pool.fetchrow("SELECT contato_fone FROM conversas WHERE conversation_id = $1", conversation_id)
                contato_fone = row['contato_fone'] if row else None

            # ── TTS: detecta se cliente enviou áudio → responde com áudio ──
            _tts_ativo = pers.get("tts_ativo", True) if pers else True
            _tts_voz = pers.get("tts_voz", None) if pers else None
            _cliente_enviou_audio = len(transcricoes) > 0 if transcricoes else False
            # TTS funciona para UazAPI direto OU Chatwoot com integração UazAPI (WhatsApp)
            _has_whatsapp = source == "uazapi"
            if not _has_whatsapp and source == "chatwoot":
                _uaz_check = await carregar_integracao(empresa_id, 'uazapi')
                _has_whatsapp = bool(_uaz_check)
            _enviar_audio = _cliente_enviou_audio and _tts_ativo and _has_whatsapp
            logger.info(f"🔊 [TTS Check] conv={conversation_id} | audio_cliente={_cliente_enviou_audio} | tts_ativo={_tts_ativo} | voz={_tts_voz} | source={source} | has_whatsapp={_has_whatsapp} | enviar_audio={_enviar_audio}")

            if fast_reply_lista:
                # ── Planos: cada item da lista = 1 mensagem separada ──────────────
                _total_planos = len([b for b in fast_reply_lista if b.strip()])
                _plano_idx = 0
                for i, bloco_plano in enumerate(fast_reply_lista):
                    if await exists_tenant_cache(empresa_id, f"pause_ia:{conversation_id}"):
                        break
                    if not bloco_plano.strip():
                        continue
                    _plano_idx += 1
                    await bd_salvar_mensagem_local(conversation_id, empresa_id, "assistant", bloco_plano.strip())

                    if source == 'chatwoot':
                        typing_time = min(len(bloco_plano) * 0.012, 3.0) + random.uniform(0.2, 0.6)
                        await simular_digitacao(account_id, conversation_id, integracao, typing_time)

                    # Áudio PTT apenas no último bloco (evita múltiplos áudios)
                    _audio_neste_bloco = _enviar_audio and (_plano_idx == _total_planos)
                    await despachar_resposta(
                        account_id, conversation_id, randomizar_mensagem(bloco_plano.strip()), nome_ia, integracao,
                        empresa_id, source=source, contato_fone=contato_fone,
                        enviar_audio=_audio_neste_bloco, tts_voz=_tts_voz
                    )
                    await bd_atualizar_msg_ia(conversation_id, empresa_id)
                    if i == 0:
                        await bd_registrar_primeira_resposta(conversation_id, empresa_id)

            elif fast_reply:
                if not resposta_texto:
                    resposta_texto = fast_reply if isinstance(fast_reply, str) else ""

                if source == 'chatwoot':
                    typing_time = min(len(resposta_texto) * 0.015, 3.5) + random.uniform(0.3, 0.8)
                    await simular_digitacao(account_id, conversation_id, integracao, typing_time)

                await despachar_resposta(
                    account_id, conversation_id, randomizar_mensagem(resposta_texto),
                    nome_ia, integracao, empresa_id,
                    source=source, contato_fone=contato_fone,
                    enviar_audio=_enviar_audio, tts_voz=_tts_voz
                )
                await bd_atualizar_msg_ia(conversation_id, empresa_id)
                await bd_registrar_primeira_resposta(conversation_id, empresa_id)

            else:
                if resposta_texto and resposta_texto.strip():
                    _texto_final = resposta_texto.strip()
                    _blocos = dividir_em_blocos(_texto_final)

                    for _i, _bloco in enumerate(_blocos):
                        if not _bloco:
                            continue
                        if source == 'chatwoot':
                            typing_time = min(len(_bloco) * 0.02, 4.0) + random.uniform(0.3, 0.8)
                            await simular_digitacao(account_id, conversation_id, integracao, typing_time)
                        elif _i > 0:
                            # UazAPI: simula "digitando..." antes de cada mensagem
                            _chat_id = contato_fone or str(conversation_id)
                            _uaz_typing = UazAPIClient(
                                integracao.get('url') or integracao.get('api_url'),
                                integracao.get('token'),
                                integracao.get('instance', 'default')
                            )
                            _typing_ms = min(len(_bloco) * 15, 3000) + random.randint(300, 800)
                            await _uaz_typing.set_presence(_chat_id, "composing", delay=_typing_ms)
                            await asyncio.sleep(_typing_ms / 1000)

                        # Áudio PTT apenas no último bloco
                        _audio_neste_bloco = _enviar_audio and (_i == len(_blocos) - 1)
                        await despachar_resposta(
                            account_id, conversation_id, _bloco, nome_ia, integracao,
                            empresa_id, source=source, contato_fone=contato_fone,
                            enviar_audio=_audio_neste_bloco, tts_voz=_tts_voz
                        )
                        await bd_atualizar_msg_ia(conversation_id, empresa_id)
                        if _i == 0:
                            await bd_registrar_primeira_resposta(conversation_id, empresa_id)

        # Registra hash das mensagens respondidas para bloquear duplicatas no drain
        await redis_client.setex(_ultima_resp_key, 120, _hash_msgs)

        # 💾 Extrai memórias de longo prazo das mensagens (async, sem bloquear)
        if contato_fone and textos:
            safe_create_task(
                extrair_memorias_da_conversa(textos, resposta_texto, empresa_id, contato_fone),
                name="extrair_memorias"
            )

        # 🔄 DRAIN — processa mensagens que chegaram DURANTE o processamento da IA
        # Espera janela generosa para rajada WhatsApp, depois processa INLINE
        # (antes: re-agendava novo ciclo, gerando resposta duplicada e desperdiçando tokens)
        await asyncio.sleep(3.0)

        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.lrange(chave_buffet, 0, -1)
            pipe.delete(chave_buffet)
            res_drain = await pipe.execute()
        msgs_drain = res_drain[0] or []

        if msgs_drain:
            logger.info(f"🔄 Drain: {len(msgs_drain)} msgs extras para conv {conversation_id}")

            # Extrai textos e salva no BD
            textos_drain = []
            for m_json in msgs_drain:
                m = json.loads(m_json)
                txt = m.get("text", "")
                if txt:
                    textos_drain.append(txt)
                    await bd_salvar_mensagem_local(conversation_id, empresa_id, "user", txt)

            if textos_drain and cliente_ia:
                drain_text = "\n".join(textos_drain)
                logger.info(f"🔄 Drain inline LLM: '{drain_text[:80]}...' (conv={conversation_id})")

                try:
                    # Chama LLM com contexto: system + resposta anterior + nova mensagem
                    _drain_msgs = [
                        {"role": "system", "content": prompt_sistema},
                    ]
                    if resposta_texto:
                        _drain_msgs.append({"role": "assistant", "content": resposta_texto})
                    _drain_msgs.append({"role": "user", "content": drain_text})

                    async with llm_semaphore:
                        _drain_resp = await asyncio.wait_for(
                            cliente_ia.chat.completions.create(
                                model=modelo_escolhido,
                                messages=_drain_msgs,
                                temperature=temperature,
                                max_tokens=max_tokens,
                            ),
                            timeout=35
                        )
                    _drain_bruta = _drain_resp.choices[0].message.content or ""

                    # Parse resposta (texto puro ou JSON legado)
                    _drain_texto = limpar_markdown(_drain_bruta.strip())
                    if _drain_texto.startswith('{'):
                        try:
                            _d = json.loads(corrigir_json(_drain_texto))
                            _drain_texto = limpar_markdown(_d.get("resposta", _drain_texto))
                        except (json.JSONDecodeError, ValueError):
                            pass

                    _drain_texto = _garantir_frase_completa(_drain_texto)

                    if _drain_texto and _drain_texto.strip():
                        typing_time = min(len(_drain_texto) * 0.015, 3.0) + random.uniform(0.3, 0.6)
                        await simular_digitacao(account_id, conversation_id, integracao, typing_time, empresa_id)
                        await enviar_mensagem_chatwoot(
                            account_id, conversation_id, _drain_texto.strip(),
                            integracao, empresa_id, nome_ia=nome_ia
                        )
                        await bd_salvar_mensagem_local(conversation_id, empresa_id, "assistant", _drain_texto.strip())
                        await bd_atualizar_msg_ia(conversation_id, empresa_id)
                        logger.info(f"✅ Drain inline respondido (conv={conversation_id})")

                except Exception as e_drain_llm:
                    logger.warning(f"⚠️ Erro no drain inline LLM: {e_drain_llm}")

    except Exception:
        logger.exception(f"🔥 Erro Crítico no processamento | empresa={empresa_id} conv={conversation_id} phone={contato_fone}")
    finally:
        watchdog.cancel()
        try:
            await redis_client.eval(LUA_RELEASE_LOCK, 1, chave_lock, lock_val)
        except Exception:
            pass



async def desbloquear_ia(conversation_id: int, empresa_id: int):
    if await redis_client.delete(f"pause_ia:{empresa_id}:{conversation_id}"):
        return {"status": "sucesso", "mensagem": f"✅ IA reativada para {conversation_id}!"}
    return {"status": "aviso", "mensagem": f"A conversa {conversation_id} não estava pausada."}


# rota raiz consolidada em health() abaixo


async def metrics_endpoint():
    """
    Expõe métricas no formato Prometheus para scraping.
    Requer: pip install prometheus-client
    Integra com Grafana, Datadog, etc.
    """
    if not PROMETHEUS_OK:
        return {
            "erro": "prometheus-client não instalado",
            "instrucao": "Execute: pip install prometheus-client"
        }
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


async def metricas_diagnostico(
    empresa_id: Optional[int] = None,
    data: Optional[str] = None,
    dias: int = 7
):
    """
    Diagnóstico das métricas diárias — mostra colunas preenchidas e zeradas.

    Query params:
      - empresa_id: filtra por empresa (opcional)
      - data: data específica YYYY-MM-DD (opcional, default = hoje)
      - dias: quantos dias históricos retornar (default = 7)

    Útil para verificar se o worker_metricas_diarias está populando todas as colunas.
    """
    if not _database.db_pool:
        raise HTTPException(status_code=503, detail="Banco de dados indisponível")

    try:
        hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        data_ref = datetime.strptime(data, "%Y-%m-%d").date() if data else hoje

        # ── Colunas esperadas na tabela ───────────────────────────────
        colunas_esperadas = [
            "total_conversas", "conversas_encerradas", "conversas_sem_resposta",
            "novos_contatos", "total_mensagens", "total_mensagens_ia",
            "leads_qualificados", "taxa_conversao", "tempo_medio_resposta",
            "total_solicitacoes_telefone", "total_links_enviados",
            "total_planos_enviados", "total_matriculas",
            "pico_hora", "satisfacao_media",
            "tokens_consumidos", "custo_estimado_usd",
        ]

        # ── Colunas reais no banco ────────────────────────────────────
        colunas_banco = await _database.db_pool.fetch("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'metricas_diarias'
              AND table_schema = 'public'
            ORDER BY ordinal_position
        """)
        cols_banco = [r['column_name'] for r in colunas_banco]

        colunas_presentes = [c for c in colunas_esperadas if c in cols_banco]
        colunas_ausentes  = [c for c in colunas_esperadas if c not in cols_banco]

        # ── Registros dos últimos N dias ──────────────────────────────
        filtro_empresa = "AND empresa_id = $2" if empresa_id else ""
        params_base = [dias]
        if empresa_id:
            params_base.append(empresa_id)

        registros = await _database.db_pool.fetch(f"""
            SELECT *
            FROM metricas_diarias
            WHERE data >= (CURRENT_DATE - ($1 || ' days')::interval)::date
            {filtro_empresa}
            ORDER BY data DESC, empresa_id, unidade_id
            LIMIT 200
        """, *params_base)

        # ── Estatísticas de preenchimento ─────────────────────────────
        total_registros = len(registros)
        stats_colunas = {}
        for col in colunas_presentes:
            if total_registros == 0:
                stats_colunas[col] = {"preenchidos": 0, "nulos": 0, "percentual": 0.0}
            else:
                preenchidos = sum(1 for r in registros if r[col] is not None and r[col] != 0)
                nulos = sum(1 for r in registros if r[col] is None)
                stats_colunas[col] = {
                    "preenchidos": preenchidos,
                    "nulos": nulos,
                    "percentual": round(preenchidos / total_registros * 100, 1),
                }

        # ── Última execução do worker ─────────────────────────────────
        ultima_atualizacao = await _database.db_pool.fetchval("""
            SELECT MAX(updated_at) FROM metricas_diarias
        """)

        return {
            "diagnostico": {
                "referencia_date": str(data_ref),
                "periodo_dias": dias,
                "total_registros_encontrados": total_registros,
                "ultima_atualizacao_worker": str(ultima_atualizacao) if ultima_atualizacao else None,
            },
            "colunas": {
                "presentes_no_banco": colunas_presentes,
                "ausentes_no_banco": colunas_ausentes,
                "todas_no_schema": cols_banco,
            },
            "preenchimento_por_coluna": stats_colunas,
            "alertas": [
                f"⚠️ Coluna '{c}' não existe no banco — rode a migration de ALTER TABLE"
                for c in colunas_ausentes
            ] + [
                f"📉 Coluna '{c}' está {s['percentual']}% preenchida nos últimos {dias} dias"
                for c, s in stats_colunas.items()
                if s["percentual"] < 50 and total_registros > 0
            ],
        }

    except asyncpg.PostgresError as e:
        raise HTTPException(status_code=500, detail=f"Erro PostgreSQL: {e}")
    except Exception as e:
        logger.error(f"❌ /metricas/diagnostico erro: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def status_endpoint():
    """Retorna status detalhado dos serviços."""
    redis_ok = False
    db_ok = False
    try:
        await redis_client.ping()
        redis_ok = True
    except Exception:
        pass
    try:
        if _database.db_pool:
            await _database.db_pool.fetchval("SELECT 1")
            db_ok = True
    except Exception:
        pass
    return {
        "status": "online",
        "redis": "✅ conectado" if redis_ok else "❌ offline",
        "postgres": "✅ conectado" if db_ok else "❌ offline",
        "prometheus": "✅ ativo" if PROMETHEUS_OK else "⚠️ não instalado",
        "versao": APP_VERSION,
    }


async def health():
    """
    Health check para plataformas (Render, Railway, Fly.io, etc.).
    HEAD / e GET / retornam 200 — evita falso 'unhealthy' no dashboard.
    """
    return {
        "status": "ok",
        "service": "Motor SaaS IA",
        "version": APP_VERSION
    }
