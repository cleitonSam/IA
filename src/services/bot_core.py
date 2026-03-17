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
    get_tenant_cache, set_tenant_cache, delete_tenant_cache, exists_tenant_cache
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
    esta_aberta_agora
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
    formatar_planos_bonito, filtrar_planos_por_contexto,
    _cosine_sim, _get_embedding, buscar_cache_semantico, salvar_cache_semantico,
    detectar_intencao, coletar_mensagens_buffer,
    aguardar_escolha_unidade_ou_reencaminhar, processar_anexos_mensagens,
    resolver_contexto_atendimento, persistir_mensagens_usuario,
    extrair_json, corrigir_json, transcrever_audio, baixar_midia_com_retry
)

from fastapi import FastAPI, Request, BackgroundTasks, Header, HTTPException, Response
from dotenv import load_dotenv
from openai import AsyncOpenAI
import redis.asyncio as redis
import asyncpg
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from rapidfuzz import fuzz

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
    ip_count   = await redis_client.incr(ip_key)
    if ip_count == 1:
        await redis_client.expire(ip_key, 60)
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
            emp_count = await redis_client.incr(emp_key)
            if emp_count == 1:
                await redis_client.expire(emp_key, 60)
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


# --- UTILITÁRIOS ---

def formatar_planos_bonito(planos: List[Dict], destacar_melhor_preco: bool = True) -> List[str]:
    """
    Formata os planos de forma bonita para envio ao cliente via WhatsApp/Chatwoot.
    Retorna uma LISTA de strings — cada item = uma mensagem separada no chat.

    Formato por plano:
        🏋️ *Plano Nome*

        Pitch do plano aqui.

        Você terá acesso a:

        • Diferencial 1
        • Diferencial 2
        • Diferencial 3

        Tudo isso por apenas:

        💰 *R$XX,XX por mês*

        ⚡ *Oferta: Xmeses por R$XX,XX/mês*   (se houver promoção)

        👉 Comece agora:
        https://link-aqui

        Quer saber como funciona ou tirar alguma dúvida?
    """
    if not planos:
        return ["Não temos planos disponíveis no momento. 😕"]

    # Emojis rotativos por posição para dar variedade visual
    _EMOJIS_PLANO = ["🏋️", "💪", "⚡", "🔥", "🎯", "🌟"]

    blocos: List[str] = []

    planos_ordenados = list(planos)
    if destacar_melhor_preco:
        def _valor_plano(item: Dict[str, Any]) -> float:
            raw = item.get('valor_promocional') if item.get('valor_promocional') not in (None, "") else item.get('valor')
            try:
                v = float(raw)
                return v if v > 0 else 999999.0
            except (TypeError, ValueError):
                return 999999.0

        planos_ordenados.sort(key=_valor_plano)

    for idx, p in enumerate(planos_ordenados):
        nome = p.get('nome', 'Plano')
        link = p.get('link_venda', '') or ''

        if not link.strip():
            continue  # Plano sem link de matrícula não é exibido

        # ── Valores ──────────────────────────────────────────────────
        try:
            valor_float = float(p['valor']) if p.get('valor') is not None else None
        except (TypeError, ValueError):
            valor_float = None

        try:
            promo_float = float(p['valor_promocional']) if p.get('valor_promocional') is not None else None
        except (TypeError, ValueError):
            promo_float = None

        meses_promo = p.get('meses_promocionais')

        # ── Diferenciais ─────────────────────────────────────────────
        diferenciais = p.get('diferenciais') or []
        if isinstance(diferenciais, str):
            # Tenta deserializar caso venha como JSON string
            try:
                diferenciais = json.loads(diferenciais)
            except (json.JSONDecodeError, ValueError):
                diferenciais = [d.strip() for d in diferenciais.split(',') if d.strip()]
        if not isinstance(diferenciais, list):
            diferenciais = []

        # ── Pitch/descrição ──────────────────────────────────────────
        # Ignora pitch que pareça código de banco (todo maiúsculo, igual ao nome, etc.)
        _pitch_raw = (
            p.get('descricao') or
            p.get('pitch') or
            p.get('slogan') or
            ""
        )
        _pitch_raw = str(_pitch_raw).strip()
        _e_codigo = (
            _pitch_raw == _pitch_raw.upper()         # todo maiúsculo
            or normalizar(_pitch_raw) == normalizar(nome)   # igual ao nome do plano
            or len(_pitch_raw) < 10                  # curto demais para ser um pitch real
        )
        pitch = None if _e_codigo or not _pitch_raw else _pitch_raw

        # ── Emoji do plano ───────────────────────────────────────────
        emoji = _EMOJIS_PLANO[idx % len(_EMOJIS_PLANO)]

        # ── Montagem do bloco ────────────────────────────────────────
        linhas: List[str] = []

        # Cabeçalho
        _selo = " 🏆 *MELHOR CUSTO-BENEFÍCIO*" if destacar_melhor_preco and idx == 0 else ""
        linhas.append(f"{emoji} *{nome}*{_selo}")

        # Pitch (só se existir e não for código)
        if pitch:
            linhas.append("")
            linhas.append(pitch)

        # Diferenciais
        if diferenciais:
            linhas.append("")
            linhas.append("Você terá acesso a:")
            linhas.append("")
            for dif in diferenciais:
                linhas.append(f"• {str(dif).strip()}")
            linhas.append("")
            linhas.append("Tudo isso por apenas:")
            linhas.append("")
        else:
            linhas.append("")

        # Preço principal
        if valor_float and valor_float > 0:
            valor_fmt = f"{valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            linhas.append(f"💰 *R${valor_fmt} por mês*")
        else:
            linhas.append("💰 *Consulte o valor*")

        # Promoção (opcional)
        if promo_float and promo_float > 0 and meses_promo:
            promo_fmt = f"{promo_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            linhas.append("")
            linhas.append(f"⚡ *Oferta: {meses_promo}x R${promo_fmt}/mês*")

        # Link de matrícula
        linhas.append("")
        linhas.append("👉 Comece agora:")
        linhas.append(link.strip())

        # ⚠️ SEM pergunta de fechamento aqui — vai só no último bloco (ver abaixo)

        blocos.append("\n".join(linhas))

    if not blocos:
        return ["Não temos planos disponíveis no momento. 😕"]

    # Pergunta de fechamento apenas no ÚLTIMO plano
    blocos[-1] += "\n\nQuer saber mais sobre algum plano ou tirar alguma dúvida? 😊"

    # Cada bloco = mensagem separada
    return blocos


def filtrar_planos_por_contexto(texto_cliente: str, planos: List[Dict]) -> List[Dict]:
    """Prioriza planos mais aderentes ao que o cliente pediu (ex.: aulas coletivas)."""
    if not planos:
        return []

    txt = normalizar(texto_cliente or "")
    if not txt:
        return planos

    intencoes = {
        "aulas_coletivas": ["aulas coletivas", "coletiva", "fit dance", "zumba", "pilates", "yoga", "muay thai", "aula"],
        "musculacao": ["musculacao", "musculação", "peso", "hipertrofia", "academia"],
        "premium": ["premium", "vip", "completo", "top", "melhor plano"],
        "economico": ["barato", "mais em conta", "economico", "econômico", "preco", "preço"],
    }

    pesos = {k: 0 for k in intencoes}
    for k, chaves in intencoes.items():
        for c in chaves:
            if normalizar(c) in txt:
                pesos[k] += 1

    if sum(pesos.values()) == 0:
        return planos

    ranqueados = []
    for p in planos:
        corpus = " ".join([
            str(p.get("nome") or ""),
            str(p.get("descricao") or ""),
            str(p.get("pitch") or ""),
            str(p.get("slogan") or ""),
            json.dumps(p.get("diferenciais") or "", ensure_ascii=False),
        ])
        corp_norm = normalizar(corpus)
        score = 0
        for k, chaves in intencoes.items():
            if pesos[k] <= 0:
                continue
            score += sum(2 for c in chaves if normalizar(c) in corp_norm)
        ranqueados.append((score, p))

    ranqueados.sort(key=lambda x: x[0], reverse=True)
    melhores = [p for sc, p in ranqueados if sc > 0]
    if not melhores:
        return planos

    # Limita a 3 para não poluir, mas mantém contexto comercial claro.
    return melhores[:3]


async def renovar_lock(chave: str, valor: str, intervalo: int = 40):
    try:
        while True:
            await asyncio.sleep(intervalo)
            res = await redis_client.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], 180) else return 0 end",
                1, chave, valor
            )
            if not res:
                break
    except asyncio.CancelledError:
        pass


# ── Cache Semântico por Embedding via API ────────────────────────────────────
# Usa text-embedding-3-small via OpenRouter/OpenAI (async, sem CPU local).
# 90% mais leve que SentenceTransformer — não bloqueia event loop.
# Fallback automático para cache por hash md5 se API falhar.

def _cosine_sim(a: list, b: list) -> float:
    """Similaridade de cosseno entre dois vetores (pura Python, sem numpy)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    return dot / (norm_a * norm_b) if norm_a > 0 and norm_b > 0 else 0.0


async def _get_embedding(texto: str) -> Optional[List[float]]:
    """
    Obtém embedding via API (text-embedding-3-small).
    Retorna None se a API falhar — o sistema cai no hash cache.
    """
    if not cliente_ia:
        return None
    # Textos muito curtos (saudações, "oi", "ok") não geram cache semântico útil
    # e evitam custo de API desnecessário em escala
    if len(texto.strip()) <= 15:
        return None
    try:
        resp = await cliente_ia.embeddings.create(
            model="text-embedding-3-small",
            input=texto[:512],  # Trunca para economizar tokens
        )
        return resp.data[0].embedding
    except Exception as e:
        logger.debug(f"Embedding API indisponível: {e}")
        return None


async def buscar_cache_semantico(
    texto: str,
    slug: str,
    empresa_id: int,
    threshold: float = 0.88
) -> Optional[Dict]:
    """
    Busca no Redis por uma resposta cacheada semanticamente similar à pergunta.
    Usa embedding via API (async) + SCAN (não bloqueia Redis) + cosine similarity.
    Retorna dict {"resposta": ..., "estado": ...} ou None.
    """
    emb_query = await _get_embedding(texto)
    if not emb_query:
        return None  # API indisponível — usa hash cache

    try:
        pattern = f"semcache:{empresa_id}:{slug}:*"
        melhor_score = 0.0
        melhor_key   = None
        total_scan   = 0

        # ✅ SCAN em vez de KEYS — não trava o Redis
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(cursor, match=pattern, count=50)
            for k in keys:
                total_scan += 1
                if total_scan > 300:   # limita a 300 entradas por slug
                    break
                emb_str = await redis_client.hget(k, "embedding")
                if not emb_str:
                    continue
                emb_cached = json.loads(emb_str)
                score = _cosine_sim(emb_query, emb_cached)
                if score > melhor_score:
                    melhor_score = score
                    melhor_key   = k
            if cursor == 0 or total_scan > 300:
                break

        if melhor_score >= threshold and melhor_key:
            resposta_str = await redis_client.hget(melhor_key, "resposta")
            if resposta_str:
                logger.info(f"🧠 [E:{empresa_id}] Cache semântico HIT (sim={melhor_score:.3f}) para '{texto[:40]}'")
                return json.loads(resposta_str)
    except Exception as e:
        logger.warning(f"Cache semântico erro: {e}")
    return None


async def salvar_cache_semantico(
    texto: str,
    slug: str,
    empresa_id: int,
    dados: Dict,
    ttl: int = 3600
):
    """
    Salva embedding (via API) + resposta no Redis para uso futuro.
    Chave: semcache:{empresa_id}:{slug}:{md5(texto)}
    """
    emb = await _get_embedding(texto)
    if not emb:
        return  # API indisponível — não salva embedding (hash cache ainda funciona)
    try:
        # ── Limite por slug: máx 500 entradas para evitar crescimento ilimitado ──
        _total_slug = 0
        _cur_lim = 0
        while True:
            _cur_lim, _kk_lim = await redis_client.scan(
                _cur_lim, match=f"semcache:{empresa_id}:{slug}:*", count=100
            )
            _total_slug += len(_kk_lim)
            if _cur_lim == 0 or _total_slug >= 500:
                break
        if _total_slug >= 500:
            logger.debug(f"semcache: limite 500 atingido para slug={slug}, entrada descartada")
            return

        chave = f"semcache:{empresa_id}:{slug}:{hashlib.md5(texto.encode()).hexdigest()}"
        await redis_client.hset(chave, mapping={
            "embedding": json.dumps(emb),
            "resposta":  json.dumps(dados),
            "texto":     texto[:200],
        })
        await redis_client.expire(chave, ttl)
    except Exception as e:
        logger.warning(f"Erro ao salvar cache semântico: {e}")


def detectar_intencao(texto: str) -> Optional[str]:
    """Detecta a intenção principal da pergunta do usuário usando palavras-chave e fuzzy matching"""
    if not texto:
        return None

    texto_norm = normalizar(texto)
    melhor_intencao = None
    melhor_score = 0

    for intent, palavras in INTENCOES.items():
        for palavra in palavras:
            if palavra in texto_norm:
                return intent
            score = fuzz.partial_ratio(palavra, texto_norm)
            if score > melhor_score and score > 80:
                melhor_score = score
                melhor_intencao = intent

    return melhor_intencao


async def coletar_mensagens_buffer(conversation_id: int, empresa_id: int) -> List[str]:
    """Coleta mensagens do buffer e limpa a fila da conversa.

    Faz uma coalescência curta para agrupar rajadas (2-4 mensagens seguidas)
    em uma única resposta, reduzindo respostas duplicadas e melhorando fluidez.
    """
    chave_buffet = f"buffet:{empresa_id}:{conversation_id}"

    mensagens_acumuladas: List[str] = []
    deadline = time.time() + 1.6  # janela curta para juntar burst sem aumentar muito latência

    while True:
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.lrange(chave_buffet, 0, -1)
            pipe.delete(chave_buffet)
            resultado = await pipe.execute()
        lote = resultado[0] or []
        if lote:
            mensagens_acumuladas.extend(lote)
            if len(mensagens_acumuladas) >= 8 or time.time() >= deadline:
                break
            await asyncio.sleep(0.25)
            continue
        if mensagens_acumuladas or time.time() >= deadline:
            break
        await asyncio.sleep(0.15)

    logger.info(f"📦 Buffer tem {len(mensagens_acumuladas)} mensagens para conv {conversation_id}")
    return mensagens_acumuladas


async def aguardar_escolha_unidade_ou_reencaminhar(conversation_id: int, empresa_id: int, mensagens_acumuladas: List[str]) -> bool:
    """Reencaminha buffer quando conversa ainda está aguardando escolha de unidade."""
    if not await redis_client.exists(f"esperando_unidade:{empresa_id}:{conversation_id}"):
        return False

    logger.info(f"⏳ Conv {conversation_id} [E:{empresa_id}] aguardando escolha de unidade — IA pausada")
    for m_json in mensagens_acumuladas:
        await redis_client.rpush(f"buffet:{empresa_id}:{conversation_id}", m_json)
    await redis_client.expire(f"buffet:{empresa_id}:{conversation_id}", 300)
    return True


async def processar_anexos_mensagens(mensagens_acumuladas: List[str]) -> Dict[str, Any]:
    """Extrai textos, transcrições e imagens a partir das mensagens acumuladas."""
    textos, tasks_audio, imagens_urls = [], [], []
    for m_json in mensagens_acumuladas:
        m = json.loads(m_json)
        if m.get("text"):
            textos.append(m["text"])
        for f in m.get("files", []):
            if f["type"] == "audio":
                tasks_audio.append(transcrever_audio(f["url"]))
            elif f["type"] == "image":
                imagens_urls.append(f["url"])

    transcricoes = await asyncio.gather(*tasks_audio)

    mensagens_lista = []
    for i, txt in enumerate(textos, 1):
        mensagens_lista.append(f"{i}. {txt}")
    for i, transc in enumerate(transcricoes, len(textos) + 1):
        mensagens_lista.append(f"{i}. [Áudio] {transc}")

    return {
        "textos": textos,
        "transcricoes": transcricoes,
        "imagens_urls": imagens_urls,
        "mensagens_formatadas": "\n".join(mensagens_lista) if mensagens_lista else "",
    }


async def resolver_contexto_atendimento(
    conversation_id: int,
    textos: List[str],
    transcricoes: List[str],
    slug: str,
    empresa_id: int,
) -> Dict[str, Any]:
    """Resolve slug da unidade para o atendimento atual e registra mudança de contexto."""
    primeira_mensagem = textos[0] if textos else ""
    mudou_unidade = False
    texto_unificado = " ".join([t for t in (textos + transcricoes) if t]).strip()

    if texto_unificado:
        ctx_unidade = await resolver_contexto_unidade(
            conversation_id=conversation_id,
            texto=texto_unificado,
            empresa_id=empresa_id,
            slug_atual=slug,
        )
        novo_slug = ctx_unidade.get("slug")
        if novo_slug and novo_slug != slug:
            logger.info(f"🔄 Contexto de unidade atualizado para {novo_slug}")
            slug = novo_slug
            mudou_unidade = True
            await bd_registrar_evento_funil(
                conversation_id, empresa_id, "mudanca_unidade", f"Contexto alterado para {slug}", score_incremento=1
            )

    return {"slug": slug, "mudou_unidade": mudou_unidade, "primeira_mensagem": primeira_mensagem}


async def persistir_mensagens_usuario(conversation_id: int, empresa_id: int, textos: List[str], transcricoes: List[str]):
    """Persiste histórico de mensagens do usuário (texto e áudio transcrito)."""
    logger.debug(f"💾 Persistindo {len(textos)} textos e {len(transcricoes)} áudios para conv {conversation_id}")
    for txt in textos:
        await bd_salvar_mensagem_local(conversation_id, empresa_id, "user", txt)
    for transc in transcricoes:
        await bd_salvar_mensagem_local(conversation_id, empresa_id, "user", f"[Áudio] {transc}")
        

async def monitorar_escolha_unidade(account_id: int, conversation_id: int, empresa_id: int):
    await asyncio.sleep(120)
    if not await exists_tenant_cache(empresa_id, f"esperando_unidade:{conversation_id}"):
        return
    if await exists_tenant_cache(empresa_id, f"unidade_escolhida:{conversation_id}"):
        return

    integracao = await carregar_integracao(empresa_id, 'chatwoot')
    if not integracao:
        return

    # Lembrete amigável — pergunta de novo sem listar todas as unidades
    await enviar_mensagem_chatwoot(
        account_id, conversation_id,
        "Só pra eu não te perder de vista 😊\n\nQual cidade ou bairro você prefere para treinar?",
        integracao, empresa_id, nome_ia="Assistente Virtual"
    )

    await asyncio.sleep(480)
    if not await exists_tenant_cache(empresa_id, f"esperando_unidade:{conversation_id}"):
        return
    if await exists_tenant_cache(empresa_id, f"unidade_escolhida:{conversation_id}"):
        return

    # Sem resposta após 8 min — encerra conversa
    await delete_tenant_cache(empresa_id, f"esperando_unidade:{conversation_id}")
    url_c = f"{integracao['url']}/api/v1/accounts/{account_id}/conversations/{conversation_id}"
    try:
        await _chatwoot_module.http_client.put(
            url_c, json={"status": "resolved"},
            headers={"api_access_token": integracao['token']}
        )
    except Exception as e:
        logger.warning(f"Erro ao encerrar conversa {conversation_id}: {e}")


# --- UTILITÁRIOS DE JSON ---

def extrair_json(texto: str) -> str:
    texto = texto.strip()
    inicio = texto.find('{')
    fim = texto.rfind('}')
    if inicio != -1 and fim != -1 and fim > inicio:
        return texto[inicio:fim + 1]
    return texto


def corrigir_json(texto: str) -> str:
    texto = texto.strip()
    texto = re.sub(r'^```(?:json)?\s*', '', texto)
    texto = re.sub(r'\s*```$', '', texto)
    texto = extrair_json(texto)
    return texto


# --- PROCESSAMENTO IA E ÁUDIO ---

async def transcrever_audio(url: str):
    if not cliente_whisper:
        return "[Áudio recebido, mas Whisper não configurado]"
    async with whisper_semaphore:
        try:
            resp = await baixar_midia_com_retry(url, timeout=15.0)
            audio_file = io.BytesIO(resp.content)
            audio_file.name = "audio.ogg"
            transcription = await cliente_whisper.audio.transcriptions.create(
                model="whisper-1", file=audio_file
            )
            return transcription.text
        except httpx.TimeoutException as e:
            logger.error(f"⏱️ Timeout ao baixar áudio: {e}")
            if PROMETHEUS_OK:
                METRIC_ERROS_TOTAL.labels(tipo="whisper_timeout").inc()
            return "[Erro ao baixar áudio: timeout]"
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ HTTP {e.response.status_code} ao baixar áudio: {e}")
            if PROMETHEUS_OK:
                METRIC_ERROS_TOTAL.labels(tipo="whisper_http").inc()
            return "[Erro ao baixar áudio]"
        except Exception as e:
            logger.error(f"Erro Whisper: {e}")
            if PROMETHEUS_OK:
                METRIC_ERROS_TOTAL.labels(tipo="whisper_unknown").inc()
            return "[Erro ao transcrever áudio]"


@retry(
    wait=wait_exponential(multiplier=0.5, min=1, max=4),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError)),
    reraise=True,
)
async def baixar_midia_com_retry(url: str, timeout: float = 15.0, headers: Optional[Dict[str, str]] = None) -> httpx.Response:
    """Baixa mídia com retry para mitigar falhas transitórias de rede/provedor."""
    resp = await _chatwoot_module.http_client.get(
        url,
        headers=headers,
        follow_redirects=True,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp


async def despachar_resposta(
    account_id: int,
    conversation_id: int,
    content: str,
    nome_ia: str,
    integracao: dict,
    empresa_id: int,
    source: str = 'chatwoot',
    contato_fone: str = None
):
    """
    Despacha a resposta para o canal correto (Chatwoot ou UazAPI).
    """
    if source == 'uazapi':
        # Para UazAPI, usamos o contato_fone (ou conversation_id como fallback)
        chat_id = contato_fone if contato_fone else str(conversation_id)
            
        uaz = UazAPIClient(integracao.get('url'), integracao.get('token'), integracao.get('instance', 'default'))
        
        # Substitui proporção por um tempo de digitação rígido e "redondo" (solicitação do usuário)
        import random
        tempo_digitacao = random.choice([800, 1100, 1400, 1800])

        logger.info(f"📤 Despachando via UazAPI para {chat_id} (delay {tempo_digitacao}ms)")
        # Marca que o próximo fromMe=true nessa conversa é do BOT
        await set_tenant_cache(empresa_id, f"uaz_bot_sent_conv:{conversation_id}", "1", 120)
        if contato_fone:
            await redis_client.setex(f"uaz_bot_sent:{empresa_id}:{contato_fone}", 120, "1")
        
        # Randomiza o conteúdo da mensagem de texto
        content_randomizado = randomizar_mensagem(content)
        res = await uaz.send_text(chat_id, content_randomizado, delay=tempo_digitacao)
        logger.info(f"✅ UazAPI Result: {res}")
        return res
    else:
        logger.info(f"📤 Despachando via Chatwoot conv={conversation_id} emp={empresa_id}")
        return await enviar_mensagem_chatwoot(
            account_id, conversation_id, content, integracao, empresa_id, nome_ia=nome_ia
        )


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
    chave_buffet = f"buffet:{empresa_id}:{conversation_id}"
    watchdog = asyncio.create_task(renovar_lock(chave_lock, lock_val))

    try:
        # ⏱️ Aguarda curto período para acumular mensagens sem sacrificar latência
        await asyncio.sleep(0.8)

        mensagens_acumuladas = await coletar_mensagens_buffer(conversation_id, empresa_id)
        if not mensagens_acumuladas:
            return

        # Pausa global da IA no Chatwoot por empresa (evita responder enquanto estiver desativada)
        if source == 'chatwoot' and await redis_client.get(f"ia:chatwoot:paused:{empresa_id}") == "1":
            logger.info(f"⏸️ IA global Chatwoot pausada para empresa {empresa_id}; conv {conversation_id} ignorada")
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

        # ── Anti-duplicata: bloqueia reprocessamento do mesmo conteúdo ──────────
        # O drain loop pode recolocar mensagens no buffer após o processamento.
        # Se o hash das mensagens atuais é igual ao que foi respondido nos últimos
        # 2 minutos, descarta silenciosamente — a resposta já foi enviada.
        _hash_msgs = hashlib.md5(mensagens_formatadas.encode()).hexdigest()
        _ultima_resp_key = f"last_ai_msg:{empresa_id}:{conversation_id}"
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

        estado_raw = await redis_client.get(f"estado:{empresa_id}:{conversation_id}")
        estado_atual = descomprimir_texto(estado_raw) or "neutro"

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
        link_mat = unidade.get('link_matricula') or unidade.get('site') or 'nosso site oficial'
        tel_banco = extrair_telefone_unidade(unidade)

        # Planos ativos
        planos_ativos = await buscar_planos_ativos(empresa_id, unidade.get('id'), force_sync=True)
        if planos_ativos:
            link_plano = planos_ativos[0].get('link_venda') if planos_ativos else link_mat
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
            # Sempre envia planos em blocos estruturados — nunca pelo LLM.
            # O LLM trunca respostas longas com múltiplos planos.
            _planos_filtrados = filtrar_planos_por_contexto(texto_cliente_unificado, planos_ativos)
            fast_reply_lista = formatar_planos_bonito(_planos_filtrados, destacar_melhor_preco=True)
            logger.info(f"⚡ Planos: envio em blocos ({len(_planos_filtrados)} planos)")

        # Endereça perguntas de unidades/localização sem passar no LLM (evita alucinação de bairro/cidade)
        if intencao == "unidades" and not fast_reply_lista:
            fast_reply = await responder_lista_unidades(empresa_id, texto_cliente_unificado)
            logger.info("⚡ Unidades: resposta factual direta sem LLM")

        # Perguntas de grade/modalidades: tenta responder da unidade citada na mensagem, sem LLM.
        if intencao == "modalidades" and not fast_reply_lista and not fast_reply:
            slug_modalidades = await buscar_unidade_na_pergunta(texto_cliente_unificado, empresa_id, fuzzy_threshold=82)
            if slug_modalidades:
                if slug_modalidades != slug:
                    slug = slug_modalidades
                    await redis_client.setex(f"unidade_escolhida:{conversation_id}", 86400, slug)
                unidade_modalidades = await carregar_unidade(slug_modalidades, empresa_id) or unidade
                fast_reply = responder_modalidades(unidade_modalidades)
                logger.info(f"⚡ Modalidades: resposta factual da unidade {slug_modalidades}")
            else:
                _tem_pedido_unidade = bool(re.search(r"(unidade|bairro|cidade|grade|aula|aulas)", normalizar(texto_cliente_unificado or "")))
                if _tem_pedido_unidade:
                    fast_reply = await responder_lista_unidades(empresa_id, texto_cliente_unificado)
                    logger.info("⚡ Modalidades: unidade não encontrada, retornando lista segura de unidades")

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
            # --- FLUXO IA ---
            faq = await carregar_faq_unidade(slug, empresa_id) or ""
            logger.info(f"🧠 BotCore: FAQ carregado, montando prompt para conv {conversation_id}")
            historico = await bd_obter_historico_local(conversation_id, empresa_id, limit=12) or "Sem histórico."

            todas_unidades = await listar_unidades_ativas(empresa_id)
            lista_unidades_nomes = ", ".join([u["nome"] for u in todas_unidades])

            # Resumo compacto de TODAS as unidades (endereço, infraestrutura, horários, modalidades)
            # para que a IA possa responder perguntas sobre qualquer unidade da rede
            def _resumo_unidade(u: dict) -> str:
                partes = [f"• {u.get('nome', '?')}"]
                cidade = u.get('cidade') or u.get('bairro') or ''
                estado = u.get('estado') or ''
                if cidade or estado:
                    partes.append(f"  Localização: {cidade}{', ' + estado if estado else ''}")
                end = u.get('endereco_completo') or u.get('endereco') or ''
                if end:
                    partes.append(f"  Endereço: {end}")
                tel = u.get('telefone') or u.get('whatsapp') or ''
                if tel:
                    partes.append(f"  Telefone: {tel}")
                hor = u.get('horarios')
                if hor:
                    hor_str = hor if isinstance(hor, str) else json.dumps(hor, ensure_ascii=False)
                    partes.append(f"  Horários: {hor_str}")
                infra = u.get('infraestrutura')
                if infra:
                    if isinstance(infra, dict):
                        itens = [k for k, v in infra.items() if v]
                        infra_str = ", ".join(itens) if itens else json.dumps(infra, ensure_ascii=False)
                    else:
                        infra_str = str(infra)
                    if infra_str:
                        partes.append(f"  Infraestrutura: {infra_str}")
                mods = u.get('modalidades')
                if mods:
                    if isinstance(mods, list):
                        mods_str = ", ".join(str(m) for m in mods if m)
                    elif isinstance(mods, dict):
                        mods_str = ", ".join(k for k, v in mods.items() if v)
                    else:
                        mods_str = str(mods)
                    if mods_str:
                        partes.append(f"  Modalidades: {mods_str}")
                foto = u.get('foto_grade')
                if foto:
                    partes.append(f"  Grade/Horários: imagem disponível — use <SEND_IMAGE:{u.get('slug')}> para enviar")
                tour = u.get('link_tour_virtual')
                if tour:
                    partes.append(f"  Tour Virtual: vídeo disponível — use <SEND_VIDEO:{u.get('slug')}> para enviar")
                return "\n".join(partes)

            resumo_todas_unidades = "\n\n".join(
                _resumo_unidade(u) for u in todas_unidades
            ) if todas_unidades else "A nossa rede possui diversas unidades, mas não tenho os detalhes de endereço delas agora."

            nome_empresa = unidade.get('nome_empresa') or 'Nossa Empresa'
            nome_unidade = unidade.get('nome') or 'Unidade Matriz'
            qtd_unidades_rede = len(todas_unidades or [])
            contexto_rede_unidades = (
                f"A rede {nome_empresa} possui {qtd_unidades_rede} unidades ativas. "
                "Quando fizer sentido na conversa, mencione essa quantidade para orientar o cliente."
                if qtd_unidades_rede > 1 else
                f"A rede {nome_empresa} está operando com 1 unidade ativa."
            )

            if hor_banco:
                if isinstance(hor_banco, dict):
                    horarios_str = "\n".join([f"- {dia}: {h}" for dia, h in hor_banco.items()])
                else:
                    horarios_str = str(hor_banco)
            else:
                horarios_str = "não informado"

            _aberta_agora, _horario_hoje = esta_aberta_agora(hor_banco)
            if _aberta_agora is True:
                _status_agora = f"✅ ABERTA AGORA (hoje: {_horario_hoje})"
            elif _aberta_agora is False:
                _status_agora = f"❌ FECHADA AGORA (hoje: {_horario_hoje})"
            else:
                _status_agora = "não informado"

            # Detalhes de planos para o prompt (texto simples, sem markdown)
            planos_detalhados = formatar_planos_para_prompt(planos_ativos) if planos_ativos else "não informado"
            modalidades_prompt = ", ".join(normalizar_lista_campo(unidade.get("modalidades"))) or "não informado"
            pagamentos_prompt = ", ".join(normalizar_lista_campo(unidade.get("formas_pagamento"))) or "não informado"
            convenios_prompt = ", ".join(normalizar_lista_campo(unidade.get("convenios"))) or "não informado"

            dados_unidade = f"""
DADOS COMPLETOS DA UNIDADE
Nome: {unidade.get('nome') or 'não informado'}
Empresa: {unidade.get('nome_empresa') or 'não informado'}
Endereço: {end_banco or 'não informado'}
Cidade/Estado: {unidade.get('cidade') or 'não informado'} / {unidade.get('estado') or 'não informado'}
Telefone: {tel_banco or 'não informado'}
Status atual: {_status_agora}
Horários:
{horarios_str}
Planos (com links de matricula):
{planos_detalhados}
Site: {unidade.get('site') or 'não informado'}
Instagram: {unidade.get('instagram') or 'não informado'}
Modalidades: {modalidades_prompt}
Infraestrutura: {json.dumps(unidade.get('infraestrutura', {}), ensure_ascii=False) if unidade.get('infraestrutura') else 'não informado'}
Pagamentos: {pagamentos_prompt}
Convênios: {convenios_prompt}
"""

            # ── Campos conhecidos da personalidade_ia ──────────────────────────
            tom_voz          = pers.get('tom_voz') or 'Profissional, claro e prestativo'
            estilo           = pers.get('estilo_comunicacao') or ''
            saudacao         = pers.get('saudacao_personalizada') or f"Olá! Sou {nome_ia}, como posso ajudar?"
            instrucoes_base  = pers.get('instrucoes_base') or "Atenda o cliente de forma educada."
            regras_atend     = pers.get('regras_atendimento') or "Seja breve e objetivo."

            # ── Campos extras da personalidade_ia (consumidos dinamicamente) ──
            # Qualquer coluna presente na tabela mas não listada acima é injetada
            # automaticamente no prompt — sem hardcode, sem brecha para falha.
            _CAMPOS_FIXOS = {
                'id', 'empresa_id', 'ativo', 'nome_ia', 'personalidade',
                'tom_voz', 'estilo_comunicacao', 'saudacao_personalizada',
                'instrucoes_base', 'regras_atendimento', 'modelo_preferido',
                'temperatura', 'created_at', 'updated_at', 'max_tokens',
            }
            _LABEL_MAP = {
                'objetivos_venda':     'OBJETIVOS DE VENDA',
                'metas_comerciais':    'METAS COMERCIAIS',
                'script_vendas':       'SCRIPT DE VENDAS',
                'scripts_objecoes':    'RESPOSTAS A OBJEÇÕES',
                'frases_fechamento':   'FRASES DE FECHAMENTO',
                'diferenciais':        'DIFERENCIAIS DA EMPRESA',
                'posicionamento':      'POSICIONAMENTO DE MERCADO',
                'publico_alvo':        'PÚBLICO-ALVO',
                'restricoes':         'RESTRIÇÕES',
                'linguagem_proibida':  'LINGUAGEM PROIBIDA',
                'contexto_empresa':    'CONTEXTO DA EMPRESA',
                'contexto_extra':      'CONTEXTO EXTRA',
                'abordagem_proativa':  'ABORDAGEM PROATIVA',
                'idioma':              'IDIOMA',
                'horario_ativo_inicio':'HORÁRIO ATIVO INÍCIO',
                'horario_ativo_fim':   'HORÁRIO ATIVO FIM',
                'exemplos':            'EXEMPLOS DE ATENDIMENTO',
                'palavras_proibidas':  'PALAVRAS PROIBIDAS',
                'despedida_personalizada': 'DESPEDIDA PERSONALIZADA',
            }

            _extras_prompt = ""
            for _campo, _valor in pers.items():
                if _campo in _CAMPOS_FIXOS:
                    continue
                if not _valor:
                    continue
                # Converte tipos complexos (dict/list) para string legível
                if isinstance(_valor, (dict, list)):
                    _valor_str = json.dumps(_valor, ensure_ascii=False, indent=2)
                else:
                    _valor_str = str(_valor).strip()
                if not _valor_str or _valor_str in ('null', 'None', '{}', '[]', ''):
                    continue
                _label = _LABEL_MAP.get(_campo, _campo.upper().replace('_', ' '))
                _extras_prompt += f"\n{_label}\n{_valor_str}\n"

            aviso_mudanca = (
                f"\n[AVISO]: O cliente perguntou sobre a unidade {nome_unidade}. "
                "Use os dados abaixo para responder."
            ) if mudou_unidade else ""

            contexto_precarregado_bloco = ""
            if contexto_precarregado:
                contexto_precarregado_bloco = f"""
DADOS JÁ CARREGADOS DO BANCO — USE EXATAMENTE ESSES, não invente nem altere:
{contexto_precarregado}

REGRA OBRIGATÓRIA: O cliente JÁ pediu esses dados — entregue-os DIRETAMENTE na resposta.
NUNCA pergunte "Quer que eu te passe?", "Posso te enviar?" ou qualquer variação.
NUNCA ofereça ajuda de navegação como "posso te ensinar a chegar", "te passo o caminho",
"precisa de indicações para chegar" ou similares — apenas informe o endereço/dado solicitado.
"""

            prompt_sistema = f"""
IDIOMA OBRIGATÓRIO: Responda SEMPRE em português do Brasil.
NUNCA use inglês ou qualquer outro idioma — nem uma palavra, nem no meio de frases.
NUNCA avalie respostas com frases como "is perfect", "that's great", "perfect answer" ou similares.
NÃO mostre tags internas, avisos de sistema ou colunas técnicas na mensagem final.

Seu nome é {nome_ia}.
{f"Você é atendente virtual da rede {nome_empresa}, respondendo pelo canal da unidade {nome_unidade}. Você representa TODA a rede e pode ajudar clientes de QUALQUER unidade." if slug else f"Você é consultor da rede {nome_empresa}. Como ainda não sei qual unidade o cliente prefere, fale em nome da Empresa/Rede de forma acolhedora."}

{ctx_aluno}

PERSONALIDADE
{pers.get('personalidade', 'Atendente prestativo, simpático e focado em ajudar.')}

ESTILO DE COMUNICAÇÃO
Tom de voz: {tom_voz}
Estilo: {estilo}

SAUDAÇÃO PADRÃO
{saudacao}

INSTRUÇÕES BASE
{instrucoes_base}

REGRAS DE ATENDIMENTO
{regras_atend}
{_extras_prompt}
INFORMAÇÕES DA UNIDADE
{dados_unidade}

UNIDADES DA REDE {nome_empresa.upper()}:
{resumo_todas_unidades}

CONTEXTO DA REDE:
{contexto_rede_unidades}

REGRA SOBRE OUTRAS UNIDADES: Você tem os dados acima de TODAS as unidades da rede.
Se o cliente perguntar sobre qualquer unidade específica (mesmo que não seja a que você está atendendo agora), responda DIRETAMENTE com o que você sabe (endereço, horário, modalidades).
Se você NÃO souber qual unidade ele quer, pergunte qual região fica melhor para ele, ou cite as unidades disponíveis (usando a lista acima).
NÃO peça ao cliente para escolher uma unidade ANTES de responder se a pergunta dele for específica sobre uma unidade da lista.
NUNCA diga "meu sistema é focado em [unidade X]" ou "não tenho informações de [outra unidade]" — você TEM os dados de TODAS as unidades listadas acima.
NUNCA invente proximidade geográfica ("pertinho", "próxima") sem evidência explícita nos dados.
NUNCA afirme bairro/cidade de uma unidade se essa informação não estiver exatamente nos dados fornecidos.
Se o cliente citar um bairro/cidade sem unidade correspondente nos dados, diga isso claramente e ofereça as unidades reais disponíveis.
Se uma unidade na lista acima tiver "<SEND_IMAGE:slug>", use essa tag na sua resposta quando o cliente pedir a grade de horários ou aulas dessa unidade para que a imagem seja enviada automaticamente.
Se uma unidade tiver "<SEND_VIDEO:slug>", use essa tag quando o cliente quiser conhecer a academia por dentro ou pedir o tour virtual.

FAQ — RESPOSTAS PRONTAS (USE SEMPRE QUE A PERGUNTA DO CLIENTE SE ENCAIXAR):
{faq}

HISTÓRICO DA CONVERSA
{historico}

REGRAS CRÍTICAS — ANTI-ALUCINAÇÃO (OBRIGATÓRIO):
- Para informações DETALHADAS da unidade atual ({nome_unidade}): use EXCLUSIVAMENTE "INFORMAÇÕES DA UNIDADE" acima.
- Para OUTRAS unidades da rede: use apenas os dados listados em "UNIDADES DA REDE" acima (endereço, horário, modalidades, etc.).
- Se um campo estiver como "não informado" ou ausente, diga que não tem essa informação agora.
- NUNCA invente endereços, telefones, horários ou qualquer dado não listado.
- NUNCA diga que a empresa tem "apenas uma unidade" — você não tem essa informação completa.
- Sempre trate a empresa correta ({nome_empresa}) como contexto do atendimento.
- Se a pergunta do cliente bater com algum item do FAQ acima, USE aquela resposta como base.

FLUXO DE VENDEDOR REAL (OBRIGATÓRIO):
Você é um VENDEDOR, não um robô de FAQ. Siga este fluxo:
1. Responda a pergunta do cliente de forma direta e curta
2. Depois da resposta, faça UMA pergunta de descoberta que avança a conversa
Exemplos:
  Cliente: "Tem diária?" → "Temos sim! A diária custa R$40 💪 Você pretende treinar só hoje ou está pensando em começar academia?"
  Cliente: "Qual o horário?" → "Nosso horário é seg-sex 06h às 23h 😊 Você já treina ou está começando agora?"
  Cliente: "Quanto custa?" → "Temos planos a partir de R$X! Qual seu objetivo principal — musculação, cardio, ou os dois?"
REGRAS do fluxo:
- Resposta + pergunta na MESMA mensagem, sempre
- A pergunta deve descobrir algo sobre o cliente (objetivo, frequência, localização)
- NUNCA adicione dados que o cliente NÃO pediu (ex: não jogue horários se pediu preço)
- Se o cliente já respondeu uma descoberta, avance para a próxima etapa (mostrar plano, agendar visita)

REGRAS DE TOM (OBRIGATÓRIO):
- NUNCA comece resposta com "Olá" se já houve troca de mensagens — vá direto ao ponto
- NUNCA diga "Olá! Nossos horários são:" — diga "Nosso horário é:"
- Em saudações iniciais, NÃO mencione o nome da unidade — apenas se apresente
- Quando perguntarem seu nome, responda APENAS seu nome
- Conversa casual ("tudo bem?", "e aí?"): responda naturalmente, NÃO empurre planos

FORMATAÇÃO DA RESPOSTA (OBRIGATÓRIO):
Você escreve para WhatsApp. Toda mensagem deve ser LIMPA, ORGANIZADA e FÁCIL de ler.

ESTRUTURA de cada resposta:
1. Frase de abertura curta (resposta direta à pergunta)
2. Dados/informações (se houver) — organizados com quebra de linha
3. Pergunta de descoberta (para avançar a conversa)

REGRAS DE FORMATO:
- Use *texto* para destaque (bold do WhatsApp) — NUNCA use ** ou ##
- Listas com • no início, cada item em linha separada
- Separe blocos com UMA linha em branco
- Links: sempre URL plana (ex: https://exemplo.com)
- Emojis: máximo 2-3 por mensagem, nos pontos certos (😊 💪 ✅)
- NUNCA use markdown: sem **, sem ##, sem ```código```, sem [texto](url)

TAMANHO DA RESPOSTA (CRÍTICO — RESPEITE SEMPRE):
- Tamanho ideal: 2-4 linhas. Máximo absoluto: 8 linhas
- Se a resposta ficar maior que 8 linhas, RESUMA. Nunca liste todos os dias da semana um por um.
- Horários: agrupe em UMA linha. Ex: "Seg-Sex: 06h-23h • Sáb: 09h-17h • Dom: 09h-13h"
- NUNCA liste dia por dia (Segunda: ..., Terça: ..., Quarta: ...) — SEMPRE agrupe dias com mesmo horário
- Planos: mostre no máximo 2-3 opções resumidas, não liste todos os detalhes
- Se o cliente pedir detalhes completos, AINDA resuma — ofereça enviar por link ou foto
- REGRA DE OURO: é melhor uma resposta CURTA e COMPLETA do que uma resposta LONGA e CORTADA

REGRAS DE TOM:
- Fale como pessoa real — NUNCA mencione ser IA, robô ou assistente virtual
- NUNCA se apresente novamente se já houver histórico
- SEMPRE chame o cliente pelo primeiro nome pelo menos 1 vez em cada resposta — de forma natural, não forçada
- NUNCA comece com "Olá" se a conversa já começou — vá direto ao ponto

EXEMPLO DE MENSAGEM BEM FORMATADA:
"Temos sim! A diária custa *R$40* 💪

Se quiser, pode vir treinar hoje mesmo — estamos abertos até as 23h.

Você pretende treinar só hoje ou está pensando em começar academia?"
{aviso_mudanca}

DADOS DO ATENDIMENTO:
Cliente: {nome_cliente}
Estado emocional anterior: {estado_atual}
{contexto_precarregado_bloco}
MENSAGENS DO CLIENTE (responda a TODAS):
{mensagens_formatadas}

RESPONDA com a mensagem diretamente — texto puro, sem JSON, sem ```código```, sem prefixos.
"""

            conteudo_usuario = []
            for img_url in imagens_urls:
                try:
                    resp = await baixar_midia_com_retry(
                        img_url,
                        timeout=12.0,
                        headers={"api_access_token": integracao_chatwoot['token']},
                    )
                    img_b64 = base64.b64encode(resp.content).decode("utf-8")
                    conteudo_usuario.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                    })
                except Exception as e:
                    logger.error(f"Erro ao baixar imagem: {e}")

            modelo_escolhido = pers.get("model_name") or pers.get("modelo_preferido") or (
                "google/gemini-2.0-flash" if imagens_urls else "google/gemini-2.0-flash-lite"
            )
            # Se tiver imagens, força gemini-2.0-flash para melhor suporte multimodal
            if imagens_urls and not modelo_escolhido.startswith("google/"):
                 modelo_escolhido = "google/gemini-2.0-flash"

            temperature = float(pers.get("temperature") or pers.get("temperatura") or 0.7)

            # ── Guard de cota do provedor LLM (cooldown) ─────────────────────
            llm_provider_pause_key = f"llm:provider_pause:{empresa_id}"
            if await redis_client.get(llm_provider_pause_key) == "1":
                _nome_cb = nome_cliente.split()[0].capitalize() if nome_cliente else "você"
                resposta_texto = (
                    f"{_nome_cb}, agora estamos com alto volume no atendimento automático 😕\n\n"
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
                _nome_cb = nome_cliente.split()[0].capitalize() if nome_cliente else "você"
                resposta_texto = (
                    f"Olá, {_nome_cb}! 😊 Estou com uma lentidão no momento.\n\n"
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

                # Injeta informação sobre imagem de grade se existir
                _foto_grade = unidade.get("foto_grade")
                if _foto_grade:
                    prompt_sistema += f"\n[SISTEMA]: Esta unidade TEM uma imagem da grade de aulas/horários disponível em: {_foto_grade}\n"
                    prompt_sistema += "Se o cliente quiser ver a grade ou horários, você pode dizer que está enviando a imagem agora.\n"
                    prompt_sistema += "IMPORTANTE: Para enviar a imagem, adicione a tag <SEND_IMAGE> no final da sua resposta.\n"

                # Injeta informação sobre Tour Virtual se existir
                _link_tour = unidade.get("link_tour_virtual")
                if _link_tour:
                    prompt_sistema += f"\n[SISTEMA]: Esta unidade TEM um vídeo de Tour Virtual disponível em: {_link_tour}\n"
                    prompt_sistema += "Se o cliente demonstrar interesse em conhecer a academia, ver por dentro ou perguntar por tour virtual, ofereça e envie o vídeo.\n"
                    prompt_sistema += "IMPORTANTE: Para enviar o vídeo do tour, adicione a tag <SEND_VIDEO> no final da sua resposta.\n"

                # Monta conteúdo do role "user"
                if conteudo_usuario:
                    conteudo_usuario.append({"type": "text", "text": mensagens_formatadas})
                    user_content = conteudo_usuario
                else:
                    user_content = mensagens_formatadas

                async def _chamar_llm(model_id: str, extra_timeout: int = 25):
                    return await asyncio.wait_for(
                        cliente_ia.chat.completions.create(
                            model=model_id,
                            messages=[
                                {"role": "system", "content": prompt_sistema},
                                {"role": "user", "content": user_content}
                            ],
                            temperature=temperature,
                        ),
                        timeout=extra_timeout
                    )

                async with llm_semaphore:
                    try:
                        logger.info(f"📡 BotCore: Chamando LLM ({modelo_escolhido}) para conv {conversation_id}")
                        response = await _chamar_llm(modelo_escolhido, extra_timeout=25)
                        resposta_bruta = response.choices[0].message.content
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
                # ── Garante que NENHUMA resposta saia com frase cortada ──────────
                def _garantir_frase_completa(txt: str) -> str:
                    if not txt:
                        return txt
                    txt = txt.strip()
                    if txt[-1] in '.!?😊💪✅🏋🎯':
                        return txt
                    for _sep in ['. ', '! ', '? ', '!\n', '?\n', '.\n', '\n']:
                        _pos = txt.rfind(_sep)
                        if _pos > len(txt) * 0.3:
                            return txt[:_pos + 1].strip()
                    return txt

                resposta_texto = limpar_markdown(resposta_bruta.strip())

                if resposta_texto.startswith('{'):
                    try:
                        _dados_legado = json.loads(corrigir_json(resposta_texto))
                        resposta_texto = limpar_markdown(_dados_legado.get("resposta", resposta_texto))
                        novo_estado = _dados_legado.get("estado", estado_atual).strip().lower()
                    except (json.JSONDecodeError, ValueError):
                        pass

                _resp_norm = normalizar(resposta_texto)
                if any(w in _resp_norm for w in ("matricula", "matricular", "assinar", "plano", "checkout", "comecar agora")):
                    novo_estado = "conversao"
                elif any(w in _resp_norm for w in ("parabens", "que otimo", "incrivel", "adorei", "perfeito")):
                    novo_estado = "animado"
                elif any(w in _resp_norm for w in ("entendo", "compreendo", "preocupo", "problema", "dificuldade")):
                    novo_estado = "hesitante"
                elif any(w in _resp_norm for w in ("interesse", "quero saber", "me conta", "curioso")):
                    novo_estado = "interessado"
                else:
                    novo_estado = estado_atual

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
                                integracao, nome_ia=nome_ia,
                                contact_id=contact_id, source=source, fone=contato_fone
                            )
                            await asyncio.sleep(random.uniform(1.5, 3.5))
                            if source == 'uazapi' and contato_fone:
                                try:
                                    uaz = UazAPIClient(integracao.get('url'), integracao.get('token'), integracao.get('instance', 'default'))
                                    await uaz.set_presence(contato_fone, presence="composing", delay=1500)
                                except Exception: pass
                            await enviar_mensagem_chatwoot(
                                account_id, conversation_id, _cross_foto, integracao,
                                nome_ia=nome_ia, contact_id=contact_id, source=source, fone=contato_fone,
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
                                integracao, nome_ia=nome_ia,
                                contact_id=contact_id, source=source, fone=contato_fone
                            )
                            await asyncio.sleep(random.uniform(2.0, 4.5))
                            if source == 'uazapi' and contato_fone:
                                try:
                                    uaz = UazAPIClient(integracao.get('url'), integracao.get('token'), integracao.get('instance', 'default'))
                                    await uaz.set_presence(contato_fone, presence="composing", delay=2000)
                                except Exception: pass
                            await enviar_mensagem_chatwoot(
                                account_id, conversation_id, _cross_tour, integracao,
                                nome_ia=nome_ia, contact_id=contact_id, source=source, fone=contato_fone,
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
                                integracao, 
                                nome_ia=nome_ia,
                                contact_id=contact_id, source=source, fone=contato_fone
                            )
                            await asyncio.sleep(random.uniform(1.5, 3.5))
                            if source == 'uazapi' and contato_fone:
                                try:
                                    uaz = UazAPIClient(integracao.get('url'), integracao.get('token'), integracao.get('instance', 'default'))
                                    await uaz.set_presence(contato_fone, presence="composing", delay=1500)
                                except Exception: pass
                            
                            await enviar_mensagem_chatwoot(
                                account_id, conversation_id, 
                                _foto_grade,
                                integracao,
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
                                integracao, 
                                nome_ia=nome_ia,
                                contact_id=contact_id, source=source, fone=contato_fone
                            )
                            await asyncio.sleep(random.uniform(2.0, 4.5))
                            if source == 'uazapi' and contato_fone:
                                try:
                                    uaz = UazAPIClient(integracao.get('url'), integracao.get('token'), integracao.get('instance', 'default'))
                                    await uaz.set_presence(contato_fone, presence="composing", delay=2000)
                                except Exception: pass

                            await enviar_mensagem_chatwoot(
                                account_id, conversation_id, 
                                _link_tour,
                                integracao,
                                nome_ia=nome_ia,
                                contact_id=contact_id, source=source, fone=contato_fone,
                                is_direct_url=True 
                            )
                        except Exception as e:
                            logger.error(f"Erro ao enviar vídeo do tour: {e}")
                    else:
                        resposta_texto = resposta_texto.replace("<SEND_VIDEO>", "").strip()

                if _intencao_compra and link_plano:
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
                    
                    asyncio.create_task(_criar_e_registrar())
                else:
                    logger.debug(f"⏭️ Prospect já existe para {contato_fone} (ID: {_ja_prospect}). Pulando criação.")
            # ─────────────────────────────────────────────────────────────

        salvar_resposta_unica = bool(resposta_texto and resposta_texto.strip() and not fast_reply_lista)
        if salvar_resposta_unica:
            await bd_salvar_mensagem_local(conversation_id, empresa_id, "assistant", resposta_texto)

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

            if fast_reply_lista:
                # ── Planos: cada item da lista = 1 mensagem separada ──────────────
                for i, bloco_plano in enumerate(fast_reply_lista):
                    if await exists_tenant_cache(empresa_id, f"pause_ia:{conversation_id}"):
                        break
                    if not bloco_plano.strip():
                        continue
                    await bd_salvar_mensagem_local(conversation_id, empresa_id, "assistant", bloco_plano.strip())
                    
                    if source == 'chatwoot':
                        typing_time = min(len(bloco_plano) * 0.012, 3.0) + random.uniform(0.2, 0.6)
                        await simular_digitacao(account_id, conversation_id, integracao, typing_time)
                    
                    await despachar_resposta(
                        account_id, conversation_id, randomizar_mensagem(bloco_plano.strip()), nome_ia, integracao,
                        empresa_id, source=source, contato_fone=contato_fone
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
                    source=source, contato_fone=contato_fone
                )
                await bd_atualizar_msg_ia(conversation_id, empresa_id)
                await bd_registrar_primeira_resposta(conversation_id, empresa_id)

            else:
                if resposta_texto and resposta_texto.strip():
                    _texto_final = resposta_texto.strip()
                    
                    if source == 'chatwoot':
                        typing_time = min(len(_texto_final) * 0.02, 4.0) + random.uniform(0.3, 0.8)
                        await simular_digitacao(account_id, conversation_id, integracao, typing_time)
                    
                    await despachar_resposta(
                        account_id, conversation_id, _texto_final, nome_ia, integracao,
                        empresa_id, source=source, contato_fone=contato_fone
                    )
                    await bd_atualizar_msg_ia(conversation_id, empresa_id)
                    await bd_registrar_primeira_resposta(conversation_id, empresa_id)

        # Registra hash das mensagens respondidas para bloquear duplicatas no drain
        await redis_client.setex(_ultima_resp_key, 120, _hash_msgs)

        # 🔄 DRAIN LOOP — processa mensagens que chegaram DURANTE o processamento da IA
        # Isso resolve o problema de mensagens perdidas quando o cliente digita rápido
        _drain_tentativas = 0
        while _drain_tentativas < 2:
            await asyncio.sleep(1.0)
            mensagens_pendentes = await redis_client.lrange(chave_buffet, 0, -1)
            if not mensagens_pendentes:
                break
            # Há mensagens novas — consome e repassa para o mesmo fluxo
            async with redis_client.pipeline(transaction=True) as pipe:
                pipe.lrange(chave_buffet, 0, -1)
                pipe.delete(chave_buffet)
                res_drain = await pipe.execute()
            msgs_drain = res_drain[0]
            if not msgs_drain:
                break
            logger.info(f"🔄 Drain: {len(msgs_drain)} mensagens extras para conv {conversation_id}")
            textos_drain = [json.loads(m).get("text", "") for m in msgs_drain if json.loads(m).get("text")]
            for txt in textos_drain:
                await bd_salvar_mensagem_local(conversation_id, empresa_id, "user", txt)
            # Passa essas mensagens para outro ciclo de processamento reutilizando o mesmo lock
            for m_json in msgs_drain:
                await redis_client.rpush(f"buffet_drain:{empresa_id}:{conversation_id}", m_json)
            await redis_client.expire(f"buffet_drain:{empresa_id}:{conversation_id}", 120)
            # Coloca de volta no buffet para ser pego pelo próximo webhook (lock será liberado logo)
            for m_json in msgs_drain:
                await redis_client.rpush(chave_buffet, m_json)
            await redis_client.expire(chave_buffet, 60)
            _drain_tentativas += 1

    except Exception:
        logger.exception("🔥 Erro Crítico no processamento")
    finally:
        watchdog.cancel()
        try:
            await redis_client.eval(LUA_RELEASE_LOCK, 1, chave_lock, lock_val)
        except Exception:
            pass
        # Após liberar o lock, se ainda há mensagens no buffet, agenda novo processamento
        try:
            restantes = await redis_client.lrange(chave_buffet, 0, -1)
            if restantes:
                logger.info(f"📬 {len(restantes)} mensagens no buffet após processamento — reagendando conv {conversation_id}")
                novo_lock_val = str(uuid.uuid4())
                if await redis_client.set(chave_lock, novo_lock_val, nx=True, ex=180):
                    asyncio.create_task(processar_ia_e_responder(
                        account_id, conversation_id, contact_id, slug,
                        nome_cliente, novo_lock_val, empresa_id, integracao
                    ))
        except Exception as e_drain:
            logger.error(f"Erro no drain pós-processamento: {e_drain}")


# --- WEBHOOK ENDPOINT ---
# validar_assinatura is imported from src.services.chatwoot_client

async def chatwoot_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_chatwoot_signature: str = Header(None)
):
    await validar_assinatura(request, x_chatwoot_signature)
    payload = await request.json()

    event = payload.get("event")
    id_conv = payload.get("conversation", {}).get("id") or payload.get("id")
    account_id = payload.get("account", {}).get("id")

    if PROMETHEUS_OK:
        METRIC_WEBHOOKS_TOTAL.labels(event=event or "unknown").inc()

    if not id_conv:
        return {"status": "ignorado_sem_conversation_id"}

    # Rate limiting por conversa
    # Rate limit por conversa (anti-loop de webhook)
    # Busca empresa_id mais cedo se necessário, mas aqui podemos usar o account_id para o rate limit
    # ou mover a busca do empresa_id para antes do rate limit.
    # Vamos mover a busca do empresa_id para antes.
    empresa_id = await buscar_empresa_por_account_id(account_id)
    if not empresa_id:
        logger.error(f"Account {account_id} sem empresa associada")
        return {"status": "erro_sem_empresa"}

    rate_key = f"rl:conv:{empresa_id}:{id_conv}"
    contador = await redis_client.incr(rate_key)
    if contador == 1:
        await redis_client.expire(rate_key, 10)
    if contador > 10:
        from fastapi.responses import JSONResponse
        return JSONResponse({"status": "rate_limit"}, status_code=429)

    # Carrega integração Chatwoot da empresa
    integracao = await carregar_integracao(empresa_id, 'chatwoot')
    if not integracao:
        logger.error(f"Empresa {empresa_id} sem integração Chatwoot ativa")
        return {"status": "erro_sem_integracao"}

    conv_obj = payload.get("conversation", {}) if "conversation" in payload else payload
    if conv_obj:
        is_manual = "1" if (
            conv_obj.get("assignee_id") is not None
            or conv_obj.get("status") not in ["pending", "open", None]
        ) else "0"
        await redis_client.setex(f"atend_manual:{empresa_id}:{id_conv}", 86400, is_manual)

    if event == "conversation_created":
        # Nova conversa — garante que não há estado antigo no Redis (ex: conversas reutilizadas em testes)
        await redis_client.delete(
            f"pause_ia:{empresa_id}:{id_conv}", f"estado:{empresa_id}:{id_conv}",
            f"unidade_escolhida:{empresa_id}:{id_conv}", f"esperando_unidade:{empresa_id}:{id_conv}",
            f"prompt_unidade_enviado:{empresa_id}:{id_conv}", f"nome_cliente:{empresa_id}:{id_conv}", f"aguardando_nome:{empresa_id}:{id_conv}",
            f"atend_manual:{empresa_id}:{id_conv}", f"lock:{empresa_id}:{id_conv}", f"buffet:{empresa_id}:{id_conv}"
        )
        logger.info(f"🆕 Nova conversa {id_conv} — Redis limpo")
        return {"status": "conversa_criada"}

    if event == "conversation_updated":
        status_conv = conv_obj.get("status") or payload.get("status")
        if status_conv in {"resolved", "closed"}:
            await bd_finalizar_conversa(id_conv, empresa_id)
            await redis_client.delete(
                f"pause_ia:{empresa_id}:{id_conv}", f"estado:{empresa_id}:{id_conv}",
                f"unidade_escolhida:{empresa_id}:{id_conv}", f"esperando_unidade:{empresa_id}:{id_conv}",
                f"prompt_unidade_enviado:{empresa_id}:{id_conv}", f"nome_cliente:{empresa_id}:{id_conv}", f"aguardando_nome:{empresa_id}:{id_conv}",
                f"atend_manual:{empresa_id}:{id_conv}"
            )
            return {"status": "conversa_encerrada"}
        return {"status": "conversa_atualizada"}

    if event != "message_created":
        return {"status": "ignorado"}

    message_type = payload.get("message_type")
    sender_type = payload.get("sender", {}).get("type", "").lower()
    content_attrs = payload.get("content_attributes") or {}
    is_ai_message = content_attrs.get("origin") == "ai"
    conteudo_texto = payload.get("content", "")

    contato = payload.get("sender", {})
    nome_contato_raw = contato.get("name")
    nome_contato_limpo = limpar_nome(nome_contato_raw)
    nome_contato_valido = nome_eh_valido(nome_contato_limpo)

    if message_type == "incoming":
        if nome_contato_valido:
            await redis_client.setex(f"nome_cliente:{empresa_id}:{id_conv}", 86400, nome_contato_limpo)
        else:
            _nome_informado = extrair_nome_do_texto(conteudo_texto or "")
            if _nome_informado:
                await redis_client.setex(f"nome_cliente:{empresa_id}:{id_conv}", 86400, _nome_informado)
                await redis_client.delete(f"aguardando_nome:{empresa_id}:{id_conv}")
                await atualizar_nome_contato_chatwoot(account_id, contato.get("id"), _nome_informado, integracao)
            else:
                _aguardando_nome = await get_tenant_cache(empresa_id, f"aguardando_nome:{id_conv}")
                if not _aguardando_nome:
                    msg_nome = (
                        "Antes de continuar, me fala seu *nome* pra eu te atender certinho 😊\n\n"
                        "Pode me responder só com seu primeiro nome."
                    )
                    await enviar_mensagem_chatwoot(account_id, id_conv, msg_nome, integracao, empresa_id, nome_ia="Assistente Virtual")
                    await set_tenant_cache(empresa_id, f"aguardando_nome:{id_conv}", "1", 900)
                    return {"status": "aguardando_nome"}

    # Idempotência básica: evita reprocessar o mesmo message_created em retries do webhook
    mensagem_id = payload.get("id")
    if message_type == "incoming" and mensagem_id:
        dedup_key = f"msg_incoming_processada:{empresa_id}:{id_conv}:{mensagem_id}"
        if not await redis_client.set(dedup_key, "1", nx=True, ex=120):
            logger.info(f"⏭️ Webhook duplicado ignorado conv={id_conv} msg={mensagem_id}")
            return {"status": "duplicado"}
    labels = payload.get("conversation", {}).get("labels", [])
    slug_label = next((str(l).lower().strip() for l in labels if l), None)
    slug_redis = await redis_client.get(f"unidade_escolhida:{empresa_id}:{id_conv}")
    # Regra de segurança: em operação multiunidade, NÃO usar label como fonte primária.
    # A unidade só é assumida por escolha explícita (Redis) ou por detecção no texto.
    slug = slug_redis
    slug_detectado = None
    esperando_unidade = await redis_client.get(f"esperando_unidade:{empresa_id}:{id_conv}")
    prompt_unidade_key = f"prompt_unidade_enviado:{empresa_id}:{id_conv}"

    # Detecta unidade na mensagem APENAS em dois cenários:
    # 1) Já existe um slug definido (cliente quer trocar de unidade)
    # 2) Cliente está no fluxo de escolha de unidade (esperando_unidade=1)
    # PROTEÇÃO: só roda se a mensagem contém um indicador geográfico real
    # (nome de unidade, cidade ou bairro). Mensagens genéricas NUNCA trocam o slug.
    if message_type == "incoming" and conteudo_texto and (slug or esperando_unidade):
        _msg_norm_wh = normalizar(conteudo_texto)
        _pedido_troca_unidade = any(k in _msg_norm_wh for k in (
            "unidade", "trocar", "mudar", "outra", "bairro", "cidade", "endereco", "endereço"
        ))
        _tokens_msg_wh = {t for t in _msg_norm_wh.split() if len(t) >= 4}
        _tem_geo_wh = False
        try:
            _units_wh = await listar_unidades_ativas(empresa_id)
            for _u in _units_wh:
                for _campo in ['nome', 'cidade', 'bairro']:
                    _val = normalizar(_u.get(_campo, '') or '')
                    if not _val or len(_val) < 4:
                        continue
                    # Match exato (substring) ou por tokens significativos
                    if _val in _msg_norm_wh:
                        _tem_geo_wh = True
                        break
                    _tokens_campo = {t for t in _val.split() if len(t) >= 4 and t not in {"fitness", "academia", "unidade"}}
                    if _tokens_campo and _tokens_campo & _tokens_msg_wh:
                        _tem_geo_wh = True
                        break
                if _tem_geo_wh:
                    break
        except Exception:
            pass

        # Só troca unidade fora do fluxo de escolha quando houver pedido explícito do cliente.
        if esperando_unidade or (_tem_geo_wh and _pedido_troca_unidade):
            slug_detectado = await buscar_unidade_na_pergunta(
                conteudo_texto, empresa_id, fuzzy_threshold=82 if esperando_unidade else 90
            )
            if slug_detectado and slug_detectado != slug:
                logger.info(f"🔄 Webhook mudou contexto para {slug_detectado}")
                slug = slug_detectado
                await set_tenant_cache(empresa_id, f"unidade_escolhida:{id_conv}", slug, 86400)
                if esperando_unidade:
                    await delete_tenant_cache(empresa_id, f"esperando_unidade:{id_conv}")
                await delete_tenant_cache(empresa_id, prompt_unidade_key)

    # Sem unidade ainda — tenta definir
    if not slug and message_type == "incoming":
        unidades_ativas = await listar_unidades_ativas(empresa_id)
        if not unidades_ativas:
            return {"status": "sem_unidades_ativas"}

        elif len(unidades_ativas) == 1:
            # Empresa com apenas 1 unidade — seleciona automaticamente
            slug = unidades_ativas[0]["slug"]
            await set_tenant_cache(empresa_id, f"unidade_escolhida:{id_conv}", slug, 86400)

        else:
            if not slug:
                # Múltiplas unidades — fluxo inteligente de identificação
                texto_cliente = normalizar(conteudo_texto).strip()

                # Tenta por nome/cidade/bairro já na primeira mensagem APENAS
                # quando houver indicador geográfico claro (match exato ou por tokens).
                _tokens_msg_multi = {t for t in texto_cliente.split() if len(t) >= 4}
                _tem_geo_multi = False
                for _u in unidades_ativas:
                    for _campo in ["nome", "cidade", "bairro"]:
                        _v = normalizar(_u.get(_campo, "") or "")
                        if not _v or len(_v) < 4:
                            continue
                        if _v in texto_cliente:
                            _tem_geo_multi = True
                            break
                        _tokens_campo = {t for t in _v.split() if len(t) >= 4 and t not in {"fitness", "academia", "unidade"}}
                        if _tokens_campo and _tokens_campo & _tokens_msg_multi:
                            _tem_geo_multi = True
                            break
                    if _tem_geo_multi:
                        break

                _pedido_unidade_explicito = any(k in texto_cliente for k in (
                    "unidade", "bairro", "cidade", "endereco", "endereço"
                ))
                _msg_curta_geo = len([t for t in texto_cliente.split() if t]) <= 5

                if not slug_detectado and _tem_geo_multi and (_pedido_unidade_explicito or _msg_curta_geo):
                    slug_detectado = await buscar_unidade_na_pergunta(conteudo_texto, empresa_id)

                # Tenta por número digitado (ex: "1", "2")
                if not slug_detectado and texto_cliente.isdigit():
                    idx = int(texto_cliente) - 1
                    if 0 <= idx < len(unidades_ativas):
                        slug_detectado = unidades_ativas[idx]["slug"]

                if slug_detectado:
                    # Unidade identificada — confirma com mensagem humanizada e prossegue
                    slug = slug_detectado
                    await set_tenant_cache(empresa_id, f"unidade_escolhida:{id_conv}", slug, 86400)
                    await delete_tenant_cache(empresa_id, f"esperando_unidade:{id_conv}")
                    await delete_tenant_cache(empresa_id, prompt_unidade_key)
                    contato = payload.get("sender", {})
                    _nome_contato = limpar_nome(contato.get("name"))
                    await bd_iniciar_conversa(
                        id_conv, slug, account_id,
                        contato.get("id"), _nome_contato, empresa_id
                    )
                    await bd_registrar_evento_funil(
                        id_conv, empresa_id, "unidade_escolhida", f"Cliente escolheu {slug}", 3
                    )

                    # Envia confirmação humanizada com dados da unidade
                    _unid_dados = await carregar_unidade(slug, empresa_id) or {}
                    _nome_unid = _unid_dados.get('nome') or slug
                    _end_unid = extrair_endereco_unidade(_unid_dados) or ''
                    _hor_unid = _unid_dados.get('horarios')
                    _pers_temp = await carregar_personalidade(empresa_id) or {}
                    _nome_ia_temp = _pers_temp.get('nome_ia') or 'Assistente Virtual'

                    _cumpr = saudacao_por_horario()
                    _primeiro_nome = _nome_contato.split()[0].capitalize() if _nome_contato and _nome_contato.lower() not in ("cliente", "contato", "") else ""
                    _saud = f"{_cumpr}, {_primeiro_nome}!" if _primeiro_nome else f"{_cumpr}!"

                    _horario_hoje = horario_hoje_formatado(_hor_unid)
                    _linha_horario = f"\n🕒 Hoje estamos abertos das {_horario_hoje}" if _horario_hoje else ""
                    _linha_end = f"\n📍 {_end_unid}" if _end_unid else ""

                    _msg_confirmacao = (
                        f"{_saud} Que ótimo, vou te atender pela unidade *{_nome_unid}* 🏋️"
                        f"{_linha_end}{_linha_horario}"
                        f"\n\nComo posso te ajudar? 😊"
                    )
                    await enviar_mensagem_chatwoot(
                        account_id, id_conv, _msg_confirmacao, integracao, nome_ia=_nome_ia_temp
                    )

                    lock_key = f"agendar_lock:{empresa_id}:{id_conv}"
                    if await redis_client.set(lock_key, "1", nx=True, ex=5):
                        try:
                            existe = await _database.db_pool.fetchval(
                                "SELECT 1 FROM followups f JOIN conversas c ON c.id = f.conversa_id "
                                "WHERE c.conversation_id = $1 AND c.empresa_id = $2 AND f.status = 'pendente' LIMIT 1", id_conv, empresa_id
                            )
                            if not existe:
                                await agendar_followups(id_conv, account_id, slug, empresa_id)
                        finally:
                            await redis_client.delete(lock_key)
                    # Confirmação já enviada — NÃO cai no buffer/LLM
                    return {"status": "unidade_confirmada"}
                else:
                    # Evita loop de mensagens repetidas quando já pedimos a unidade
                    # (ex.: múltiplos webhooks da mesma conversa em sequência).
                    if esperando_unidade or await redis_client.get(prompt_unidade_key) == "1":
                        # Não fica em silêncio: envia lembrete curto com throttle
                        throttle_key = f"esperando_unidade_throttle:{empresa_id}:{id_conv}"
                        if not await redis_client.get(throttle_key):
                            msg_retry = (
                                "Ainda não consegui localizar a unidade certinha 😅\n\n"
                                "Me manda um *bairro*, *cidade* ou o *nome da unidade* (ex.: Ricardo Jafet)."
                            )
                            await enviar_mensagem_chatwoot(account_id, id_conv, msg_retry, integracao, nome_ia="Assistente Virtual")
                            await redis_client.setex(throttle_key, 30, "1")
                        logger.info(f"⏭️ Aguardando unidade para conv {id_conv}, mantendo fluxo ativo")
                        return {"status": "aguardando_escolha_unidade"}

                    # Unidade não identificada — não assume uma unidade específica.
                    _qtd_unidades = len(unidades_ativas)
                    msg = (
                        "Boa pergunta! Somos sim a Red Fitness 💪\n\n"
                        f"Hoje temos *{_qtd_unidades} unidades* e quero te direcionar para a certa.\n"
                        "Me diz sua *cidade*, *bairro* ou o *nome da unidade* que você prefere."
                    )
                    await enviar_mensagem_chatwoot(account_id, id_conv, msg, integracao, empresa_id, nome_ia="Assistente Virtual")
                    await set_tenant_cache(empresa_id, f"esperando_unidade:{id_conv}", "1", 86400)
                    await set_tenant_cache(empresa_id, prompt_unidade_key, "1", 600)
                    background_tasks.add_task(monitorar_escolha_unidade, account_id, id_conv, empresa_id)
                    return {"status": "aguardando_escolha_unidade"}

    if not slug:
        return {"status": "erro_sem_unidade"}

    # Pausa IA se for mensagem de atendente humano
    if message_type == "outgoing" and sender_type == "user":
        if is_ai_message:
            return {"status": "ignorado"}
        await redis_client.setex(f"pause_ia:{empresa_id}:{id_conv}", 43200, "1")
        if _database.db_pool:
            await _database.db_pool.execute(
                "UPDATE followups SET status = 'cancelado', updated_at = NOW() "
                "WHERE conversa_id = (SELECT id FROM conversas WHERE conversation_id = $1 AND empresa_id = $2) "
                "AND status = 'pendente'", id_conv, empresa_id
            )
        return {"status": "ia_pausada"}

    if message_type != "incoming":
        return {"status": "ignorado"}

    contato = payload.get("sender", {})
    _nome_para_bd = nome_contato_limpo if nome_eh_valido(nome_contato_limpo) else (await redis_client.get(f"nome_cliente:{empresa_id}:{id_conv}")) or "Cliente"
    await bd_iniciar_conversa(
        id_conv, slug, account_id,
        contato.get("id"), _nome_para_bd, empresa_id
    )

    lock_key = f"agendar_lock:{empresa_id}:{id_conv}"
    if await redis_client.set(lock_key, "1", nx=True, ex=5):
        try:
            existe = await _database.db_pool.fetchval(
                "SELECT 1 FROM followups f JOIN conversas c ON c.id = f.conversa_id "
                "WHERE c.conversation_id = $1 AND c.empresa_id = $2 AND f.status = 'pendente' LIMIT 1", id_conv, empresa_id
            )
            if not existe:
                await agendar_followups(id_conv, account_id, slug, empresa_id)
        finally:
            await redis_client.delete(lock_key)

    await bd_atualizar_msg_cliente(id_conv, empresa_id)

    if await redis_client.exists(f"pause_ia:{empresa_id}:{id_conv}"):
        return {"status": "ignorado"}

    anexos = payload.get("attachments") or payload.get("message", {}).get("attachments", [])
    arquivos = []
    for a in anexos:
        ft = str(a.get("file_type", "")).lower()
        tipo = "image" if ft.startswith("image") else "audio" if ft.startswith("audio") else "documento"
        arquivos.append({"url": a.get("data_url"), "type": tipo})

    await redis_client.rpush(
        f"{empresa_id}:buffet:{id_conv}",
        json.dumps({"text": conteudo_texto, "files": arquivos})
    )
    await redis_client.expire(f"{empresa_id}:buffet:{id_conv}", 60)

    lock_val = str(uuid.uuid4())
    if await redis_client.set(f"lock:{empresa_id}:{id_conv}", lock_val, nx=True, ex=180):
        background_tasks.add_task(
            processar_ia_e_responder,
            account_id, id_conv, contato.get("id"), slug,
            _nome_para_bd, lock_val, empresa_id, integracao
        )
        return {"status": "processando"}

    return {"status": "acumulando_no_buffet"}


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
