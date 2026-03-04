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
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Request, BackgroundTasks, Header, HTTPException
from dotenv import load_dotenv
from openai import AsyncOpenAI
import redis.asyncio as redis
import asyncpg
from tenacity import retry, wait_exponential, stop_after_attempt
from rapidfuzz import fuzz

# --- CONFIGURAÇÃO DE LOG ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("motor-saas-ia")

load_dotenv()

# 🧯 Segurança: Validar variáveis críticas
CHATWOOT_URL = os.getenv("CHATWOOT_URL")
CHATWOOT_TOKEN = os.getenv("CHATWOOT_TOKEN")
if not CHATWOOT_URL or not CHATWOOT_TOKEN:
    raise RuntimeError("🚨 Configuração crítica ausente: CHATWOOT_URL ou CHATWOOT_TOKEN não definidos no .env")

app = FastAPI()

# --- CONFIGURAÇÕES E VARIÁVEIS DE AMBIENTE ---
CHATWOOT_WEBHOOK_SECRET = os.getenv("CHATWOOT_WEBHOOK_SECRET")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") 
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")         
REDIS_URL = os.getenv("REDIS_URL")
DATABASE_URL = os.getenv("DATABASE_URL")

# Constantes
EMPRESA_ID_PADRAO = 1  # Enquanto não temos mapeamento account_id -> empresa_id

# 🎯 MAPEAMENTO DE INTENÇÕES PARA CACHE SEMÂNTICO
INTENCOES = {
    "preco": ["preco", "preço", "valor", "quanto custa", "mensalidade", "planos", "promoção", "promocao", "valores", "custa"],
    "horario": ["horario", "horário", "funcionamento", "abre", "fecha", "que horas", "aberto", "funciona", "horarios"],
    "endereco": ["endereco", "endereço", "local", "localização", "fica", "onde fica", "como chegar", "localizacao"],
    "telefone": ["telefone", "contato", "whatsapp", "numero", "número", "ligar", "falar", "telefone"],
    "unidades": ["unidades", "outras unidades", "lista de unidades", "quantas unidades", "onde tem", "tem em", "unidade"],
    "modalidades": ["modalidades", "atividades", "exercícios", "treinos", "aulas", "musculação", "cardio", "spinning", "alongamento", "crossfit", "funcional"],
    "infraestrutura": ["estacionamento", "vestiário", "chuveiro", "armários", "sauna", "piscina", "acessibilidade", "infraestrutura"],
    "matricula": ["matricula", "matrícula", "inscrição", "cadastro", "se inscrever", "assinar", "contratar"]
}

# Clientes de IA
cliente_ia = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
cliente_whisper = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Clientes Globais de Conexão
http_client: httpx.AsyncClient = None
redis_client: redis.Redis = None
db_pool: asyncpg.Pool = None

# --- CONTROLE DE CONCORRÊNCIA ---
whisper_semaphore = asyncio.Semaphore(5)
llm_semaphore = asyncio.Semaphore(15)

LUA_RELEASE_LOCK = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

@app.on_event("startup")
async def startup_event():
    global http_client, redis_client, db_pool
    http_client = httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(max_keepalive_connections=20, max_connections=50))
    
    try:
        redis_client = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
        await redis_client.ping()
        logger.info("🚀 Conexão com Redis estabelecida com sucesso!")
    except Exception as e:
        logger.error(f"❌ Erro ao conectar no Redis: {e}")
        raise e

    if DATABASE_URL:
        try:
            db_pool = await asyncpg.create_pool(DATABASE_URL)
            logger.info("🐘 Conexão com PostgreSQL estabelecida com sucesso!")
        except Exception as e:
            logger.error(f"❌ Erro ao conectar no PostgreSQL: {e}")
    else:
        logger.warning("⚠️ DATABASE_URL não definida. As métricas não serão salvas.")
    
    asyncio.create_task(worker_followup())
    asyncio.create_task(worker_metricas_diarias())  # Worker para métricas diárias

@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()
    await redis_client.aclose()
    if db_pool: await db_pool.close()
    logger.info("🛑 Servidor desligado.")

# --- UTILITÁRIOS ---
def normalizar(texto: str) -> str:
    """Remove acentos e converte para minúsculas"""
    if not texto: return ""
    return unicodedata.normalize("NFD", str(texto).lower()).encode("ascii", "ignore").decode("utf-8")

def comprimir_texto(texto: str) -> str:
    if not texto: return ""
    dados = zlib.compress(texto.encode('utf-8'))
    return base64.b64encode(dados).decode('utf-8')

def descomprimir_texto(texto_comprimido: str) -> str:
    if not texto_comprimido: return ""
    try:
        dados = base64.b64decode(texto_comprimido)
        return zlib.decompress(dados).decode('utf-8')
    except:
        return texto_comprimido 

def limpar_nome(nome):
    if not nome: return "Cliente"
    return re.sub(r"[^a-zA-ZÀ-ÿ\s]", "", str(nome)).strip()

async def renovar_lock(chave: str, valor: str, intervalo: int = 40):
    try:
        while True:
            await asyncio.sleep(intervalo)
            res = await redis_client.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], 180) else return 0 end",
                1, chave, valor
            )
            if not res: break
    except asyncio.CancelledError:
        pass

# 🎯 FUNÇÃO PARA DETECTAR INTENÇÃO
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

# --- FUNÇÃO CENTRALIZADA DE ENVIO PARA O CHATWOOT ---
async def enviar_mensagem_chatwoot(account_id: int, conversation_id: int, content: str, nome_ia: str = "Assistente Virtual"):
    url_m = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    payload = {
        "content": content, 
        "message_type": "outgoing",
        "content_attributes": {"origin": "ai", "ai_agent": nome_ia, "ignore_webhook": True}
    }
    headers = {"api_access_token": CHATWOOT_TOKEN}
    try:
        resp = await http_client.post(url_m, json=payload, headers=headers)
        resp.raise_for_status()
        logger.info(f"📤 Mensagem enviada para conversa {conversation_id}")
        return resp
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem para Chatwoot: {e}")
        return None

# --- BACKGROUND JOBS & FOLLOW-UP ---
async def agendar_followups(conversation_id: int, account_id: int, slug: str, empresa_id: int = EMPRESA_ID_PADRAO):
    """Agenda follow-ups para a conversa com base nos templates da unidade (ou gerais da empresa)."""
    if not db_pool:
        return
    try:
        # Cancelar follow-ups pendentes anteriores
        await db_pool.execute("""
            UPDATE followups SET status = 'cancelado' 
            WHERE conversa_id = (SELECT id FROM conversas WHERE conversation_id = $1) 
              AND status = 'pendente'
        """, conversation_id)

        # Buscar templates aplicáveis
        templates = await db_pool.fetch("""
            SELECT t.* 
            FROM templates_followup t
            LEFT JOIN unidades u ON u.id = t.unidade_id
            WHERE t.empresa_id = $1 
              AND t.ativo = true 
              AND (t.unidade_id IS NULL OR u.slug = $2)
            ORDER BY t.unidade_id NULLS LAST, t.ordem
        """, empresa_id, slug)

        agora = datetime.now(ZoneInfo("America/Sao_Paulo")).replace(tzinfo=None)
        for t in templates:
            agendado_para = agora + timedelta(minutes=t["delay_minutos"])
            await db_pool.execute("""
                INSERT INTO followups 
                    (conversa_id, empresa_id, unidade_id, template_id, tipo, mensagem, ordem, agendado_para, status)
                VALUES (
                    (SELECT id FROM conversas WHERE conversation_id = $1),
                    $2, 
                    (SELECT id FROM unidades WHERE slug = $3),
                    $4, $5, $6, $7, $8, 'pendente'
                )
            """, conversation_id, empresa_id, slug, t["id"], t["tipo"], t["mensagem"], t["ordem"], agendado_para)
        logger.info(f"📅 {len(templates)} follow-ups agendados para conversa {conversation_id}")
    except Exception as e:
        logger.error(f"Erro ao agendar followups: {e}")

async def worker_followup():
    """Worker que processa follow-ups agendados."""
    while True:
        await asyncio.sleep(30)
        if not db_pool:
            continue
        try:
            agora = datetime.now(ZoneInfo("America/Sao_Paulo")).replace(tzinfo=None)
            
            pendentes = await db_pool.fetch("""
                SELECT f.*, c.conversation_id, c.account_id, u.slug
                FROM followups f
                JOIN conversas c ON c.id = f.conversa_id
                JOIN unidades u ON u.id = f.unidade_id
                WHERE f.status = 'pendente' AND f.agendado_para <= $1
                LIMIT 20
            """, agora)

            for f in pendentes:
                if await redis_client.get(f"atend_manual:{f['conversation_id']}") == "1" or \
                   await redis_client.get(f"pause_ia:{f['conversation_id']}") == "1":
                    await db_pool.execute("UPDATE followups SET status = 'cancelado' WHERE id = $1", f['id'])
                    continue

                respondeu = await db_pool.fetchval("""
                    SELECT 1 FROM mensagens 
                    WHERE conversa_id = $1 AND role = 'user' AND created_at > NOW() - interval '5 minutes'
                """, f['conversa_id'])
                if respondeu:
                    await db_pool.execute("UPDATE followups SET status = 'cancelado' WHERE id = $1", f['id'])
                    continue

                await enviar_mensagem_chatwoot(f['account_id'], f['conversation_id'], f['mensagem'])
                await db_pool.execute("""
                    UPDATE followups SET status = 'enviado', enviado_em = NOW() 
                    WHERE id = $1
                """, f['id'])
        except Exception as e:
            logger.error(f"Erro no worker de follow-up: {e}")

async def monitorar_escolha_unidade(account_id: int, conversation_id: int):
    """Monitora se o cliente escolheu uma unidade após a mensagem de boas-vindas."""
    await asyncio.sleep(120)
    if not await redis_client.exists(f"esperando_unidade:{conversation_id}"):
        return
    if await redis_client.exists(f"unidade_escolhida:{conversation_id}"):
        return

    await enviar_mensagem_chatwoot(account_id, conversation_id, "Só pra eu não perder seu contato, qual unidade fica melhor para você? 🙂")

    await asyncio.sleep(480)
    if not await redis_client.exists(f"esperando_unidade:{conversation_id}"):
        return
    if await redis_client.exists(f"unidade_escolhida:{conversation_id}"):
        return

    await redis_client.delete(f"esperando_unidade:{conversation_id}")
    url_c = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}"
    await http_client.put(url_c, json={"status": "resolved"}, headers={"api_access_token": CHATWOOT_TOKEN})

# --- FUNÇÕES DE BUSCA DINÂMICA ---
async def listar_unidades_ativas(empresa_id: int = EMPRESA_ID_PADRAO) -> List[Dict[str, Any]]:
    if not db_pool:
        return []
    cache_key = f"cfg:unidades:lista:empresa:{empresa_id}"
    cache = await redis_client.get(cache_key)
    if cache:
        return json.loads(cache)

    try:
        query = """
            SELECT 
                u.id,
                u.uuid,
                u.slug,
                u.nome,
                u.nome_abreviado,
                u.cidade,
                u.bairro,
                u.estado,
                u.endereco || ', ' || COALESCE(u.numero, '') as endereco_completo,
                u.telefone_principal as telefone,
                u.whatsapp,
                u.horarios,
                u.modalidades,
                u.planos,
                u.formas_pagamento,
                u.convenios,
                u.infraestrutura,
                u.servicos,
                u.palavras_chave,
                u.link_matricula,
                u.site,
                u.instagram,
                e.nome as nome_empresa
            FROM unidades u
            JOIN empresas e ON e.id = u.empresa_id
            WHERE u.ativa = true AND u.empresa_id = $1
            ORDER BY u.ordem_exibicao, u.nome
        """
        rows = await db_pool.fetch(query, empresa_id)
        data = [dict(r) for r in rows]
        await redis_client.setex(cache_key, 300, json.dumps(data, default=str))
        logger.info(f"📦 {len(data)} unidades carregadas do banco")
        return data
    except Exception as e:
        logger.error(f"Erro ao listar unidades: {e}")
        return []

async def buscar_unidade_na_pergunta(texto: str, empresa_id: int = EMPRESA_ID_PADRAO) -> Optional[str]:
    if not db_pool or not texto:
        return None

    try:
        query = "SELECT unidade_slug FROM buscar_unidades_por_texto($1, $2) LIMIT 1"
        row = await db_pool.fetchrow(query, empresa_id, texto)
        if row:
            logger.info(f"🔍 Busca SQL encontrou: {row['unidade_slug']} para o texto: {texto[:50]}")
            return row['unidade_slug']
    except Exception as e:
        logger.error(f"Erro na busca SQL: {e}")

    unidades = await listar_unidades_ativas(empresa_id)
    texto_norm = normalizar(texto)

    for u in unidades:
        nome_norm = normalizar(u.get('nome', ''))
        cidade_norm = normalizar(u.get('cidade', ''))
        palavras = [normalizar(p) for p in u.get('palavras_chave', [])]

        if nome_norm and nome_norm in texto_norm:
            return u['slug']
        if cidade_norm and cidade_norm in texto_norm:
            return u['slug']
        if any(palavra in texto_norm for palavra in palavras):
            return u['slug']

    melhor_slug = None
    maior_score = 0
    for u in unidades:
        nome_norm = normalizar(u.get('nome', ''))
        score = fuzz.partial_ratio(nome_norm, texto_norm) if nome_norm else 0
        if score > maior_score:
            maior_score = score
            melhor_slug = u['slug']

    if maior_score > 70:
        return melhor_slug

    return None

async def carregar_unidade(slug: str, empresa_id: int = EMPRESA_ID_PADRAO) -> Dict[str, Any]:
    if not db_pool:
        return {}
    cache_key = f"cfg:unidade:{slug}:v2"
    cache = await redis_client.get(cache_key)
    if cache:
        return json.loads(cache)

    try:
        query = """
            SELECT 
                u.*,
                e.nome as nome_empresa,
                e.config as config_empresa
            FROM unidades u
            JOIN empresas e ON e.id = u.empresa_id
            WHERE u.slug = $1 AND u.ativa = true AND u.empresa_id = $2
        """
        row = await db_pool.fetchrow(query, slug, empresa_id)
        if row:
            dados = dict(row)
            await redis_client.setex(cache_key, 300, json.dumps(dados, default=str))
            return dados
        return {}
    except Exception as e:
        logger.error(f"Erro ao carregar unidade {slug}: {e}")
        return {}

async def carregar_faq_unidade(slug: str, empresa_id: int = EMPRESA_ID_PADRAO) -> str:
    if not db_pool:
        return ""
    cache_key = f"cfg:faq:{slug}:v2"
    cache = await redis_client.get(cache_key)
    if cache:
        return cache

    try:
        query = """
            SELECT f.pergunta, f.resposta
            FROM faq f
            JOIN unidades u ON u.id = f.unidade_id
            WHERE u.slug = $1 AND u.empresa_id = $2 AND f.ativo = true
            ORDER BY f.prioridade DESC, f.visualizacoes DESC
        """
        rows = await db_pool.fetch(query, slug, empresa_id)
        if not rows:
            return ""
        faq_formatado = "\n".join([
            f"Pergunta: {r['pergunta']}\nResposta: {r['resposta']}"
            for r in rows
        ])
        await redis_client.setex(cache_key, 300, faq_formatado)
        return faq_formatado
    except Exception as e:
        logger.error(f"Erro ao carregar FAQ da unidade {slug}: {e}")
        return ""

async def carregar_personalidade(slug: str, empresa_id: int = EMPRESA_ID_PADRAO) -> Dict[str, Any]:
    """
    Carrega a personalidade da IA para a unidade, respeitando o campo 'ativo'.
    Se estiver inativa, retorna vazio e invalida o cache.
    """
    if not db_pool:
        return {}
    cache_key = f"cfg:pers:{slug}:v2"
    
    # Tenta buscar do cache
    cache = await redis_client.get(cache_key)
    if cache:
        dados_cache = json.loads(cache)
        # Verifica se no cache o campo ativo é True; se não, considera expirado
        if dados_cache.get('ativo') is True:
            return dados_cache
        else:
            # Se no cache estiver inativo, invalida e busca do banco
            await redis_client.delete(cache_key)

    try:
        query = """
            SELECT p.*
            FROM personalidade_ia p
            JOIN unidades u ON u.id = p.unidade_id
            WHERE u.slug = $1 AND u.empresa_id = $2 AND p.ativo = true
            LIMIT 1
        """
        row = await db_pool.fetchrow(query, slug, empresa_id)
        if row:
            dados = dict(row)
            # Só cacheia se estiver ativo
            await redis_client.setex(cache_key, 300, json.dumps(dados, default=str))
            return dados
        else:
            # Se não encontrou ativo, pode ser que exista mas esteja inativo; cacheia vazio por pouco tempo para evitar repetição
            await redis_client.setex(cache_key, 60, json.dumps({}))
            return {}
    except Exception as e:
        logger.error(f"Erro ao carregar personalidade da unidade {slug}: {e}")
        return {}

async def carregar_configuracao_global(empresa_id: int = EMPRESA_ID_PADRAO) -> Dict[str, Any]:
    if not db_pool:
        return {}
    cache_key = f"cfg:global:empresa:{empresa_id}"
    cache = await redis_client.get(cache_key)
    if cache:
        return json.loads(cache)

    try:
        query = "SELECT config, nome, plano FROM empresas WHERE id = $1"
        row = await db_pool.fetchrow(query, empresa_id)
        if row:
            config = row['config'] or {}
            config['nome_empresa'] = row['nome']
            config['plano'] = row['plano']
            await redis_client.setex(cache_key, 3600, json.dumps(config, default=str))
            return config
        return {}
    except Exception as e:
        logger.error(f"Erro ao carregar config global: {e}")
        return {}

# --- AUXILIARES BANCO DE DADOS (COM CORREÇÕES) ---
def log_db_error(retry_state):
    logger.error(f"Erro BD após {retry_state.attempt_number} tentativas: {retry_state.outcome.exception()}")
    return None

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_iniciar_conversa(conversation_id: int, slug: str, account_id: int, contato_id: int = None, contato_nome: str = None, empresa_id: int = EMPRESA_ID_PADRAO):
    """Registra o início de uma conversa na tabela conversas. Garante que a conversa exista."""
    if not db_pool:
        return
    try:
        # Primeiro, obter o ID da unidade
        unidade = await db_pool.fetchrow("SELECT id FROM unidades WHERE slug = $1 AND empresa_id = $2", slug, empresa_id)
        if not unidade:
            logger.error(f"Unidade {slug} não encontrada para empresa {empresa_id}")
            return
        unidade_id = unidade['id']

        await db_pool.execute("""
            INSERT INTO conversas (conversation_id, account_id, contato_id, contato_nome, empresa_id, unidade_id, primeira_mensagem, status)
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), 'ativa')
            ON CONFLICT (conversation_id) DO UPDATE SET
                contato_nome = EXCLUDED.contato_nome,
                unidade_id = EXCLUDED.unidade_id,
                status = 'ativa',
                updated_at = NOW()
        """, conversation_id, account_id, contato_id, contato_nome, empresa_id, unidade_id)
        logger.info(f"✅ Conversa {conversation_id} iniciada/atualizada no banco")
    except Exception as e:
        logger.error(f"❌ Erro ao iniciar conversa {conversation_id}: {e}")

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_salvar_mensagem_local(conversation_id: int, role: str, content: str, tipo: str = 'texto', url_midia: str = None):
    """Salva uma mensagem na tabela mensagens. Se a conversa não existir, tenta criá-la (fallback)."""
    if not db_pool:
        return
    try:
        # Obter conversa_id interno
        conversa = await db_pool.fetchrow("SELECT id FROM conversas WHERE conversation_id = $1", conversation_id)
        if not conversa:
            logger.warning(f"Conversa {conversation_id} não encontrada para salvar mensagem. Tentando criar...")
            # Fallback: criar conversa com slug padrão? Não temos slug aqui, então não é possível.
            # Melhor logar erro e abortar.
            logger.error(f"Não é possível salvar mensagem sem conversa existente. Conv ID: {conversation_id}")
            return
        conversa_id = conversa['id']

        await db_pool.execute("""
            INSERT INTO mensagens (conversa_id, role, tipo, conteudo, url_midia, created_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
        """, conversa_id, role, tipo, content, url_midia)
        logger.info(f"💬 Mensagem {role} salva para conversa {conversation_id} (id interno: {conversa_id})")
    except Exception as e:
        logger.error(f"Erro ao salvar mensagem para conversa {conversation_id}: {e}")

async def bd_obter_historico_local(conversation_id: int, limit: int = 30) -> Optional[str]:
    if not db_pool:
        return None
    try:
        rows = await db_pool.fetch("""
            SELECT role, conteudo 
            FROM mensagens m
            JOIN conversas c ON c.id = m.conversa_id
            WHERE c.conversation_id = $1
            ORDER BY m.created_at DESC
            LIMIT $2
        """, conversation_id, limit)
        msgs = list(reversed(rows))
        return "\n".join([
            f"{'Cliente' if r['role'] == 'user' else 'Atendente'}: {r['conteudo']}"
            for r in msgs
        ])
    except Exception as e:
        logger.error(f"Erro ao obter histórico: {e}")
        return None

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_atualizar_msg_cliente(conversation_id: int):
    if not db_pool:
        return
    try:
        await db_pool.execute("""
            UPDATE conversas 
            SET total_mensagens_cliente = total_mensagens_cliente + 1, ultima_mensagem = NOW(), updated_at = NOW()
            WHERE conversation_id = $1
        """, conversation_id)
    except Exception as e:
        logger.error(f"Erro ao atualizar msg cliente {conversation_id}: {e}")

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_atualizar_msg_ia(conversation_id: int):
    if not db_pool:
        return
    try:
        await db_pool.execute("""
            UPDATE conversas 
            SET total_mensagens_ia = total_mensagens_ia + 1, ultima_mensagem = NOW(), updated_at = NOW()
            WHERE conversation_id = $1
        """, conversation_id)
    except Exception as e:
        logger.error(f"Erro ao atualizar msg ia {conversation_id}: {e}")

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_registrar_primeira_resposta(conversation_id: int):
    if not db_pool:
        return
    try:
        await db_pool.execute("""
            UPDATE conversas 
            SET primeira_resposta_em = NOW(), updated_at = NOW()
            WHERE conversation_id = $1 AND primeira_resposta_em IS NULL
        """, conversation_id)
    except Exception as e:
        logger.error(f"Erro ao registrar primeira resposta {conversation_id}: {e}")

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_registrar_evento_funil(conversation_id: int, tipo_evento: str, descricao: str, score_incremento: int = 5):
    """Registra um evento de funil. Garante que a conversa exista."""
    if not db_pool:
        return
    try:
        conversa = await db_pool.fetchrow("SELECT id FROM conversas WHERE conversation_id = $1", conversation_id)
        if not conversa:
            logger.error(f"Evento de funil não registrado: conversa {conversation_id} não existe.")
            return
        conversa_id = conversa['id']

        if tipo_evento == "interesse_detectado":
            existe = await db_pool.fetchval("""
                SELECT 1 FROM eventos_funil 
                WHERE conversa_id = $1 AND tipo_evento = $2
            """, conversa_id, tipo_evento)
            if existe:
                return

        await db_pool.execute("""
            INSERT INTO eventos_funil (conversa_id, tipo_evento, descricao, score_incremento, created_at)
            VALUES ($1, $2, $3, $4, NOW())
        """, conversa_id, tipo_evento, descricao, score_incremento)

        await db_pool.execute("""
            UPDATE conversas 
            SET score_interesse = score_interesse + $2, updated_at = NOW()
            WHERE id = $1
        """, conversa_id, score_incremento)

        if tipo_evento == "interesse_detectado":
            await db_pool.execute("""
                UPDATE conversas SET lead_qualificado = TRUE WHERE id = $1
            """, conversa_id)
        
        logger.info(f"📊 Evento {tipo_evento} registrado para conversa {conversation_id}")
    except Exception as e:
        logger.error(f"Erro ao registrar evento funil {conversation_id}: {e}")

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_finalizar_conversa(conversation_id: int):
    if not db_pool:
        return
    try:
        await db_pool.execute("""
            UPDATE conversas 
            SET status = 'encerrada', encerrada_em = NOW(), updated_at = NOW()
            WHERE conversation_id = $1
        """, conversation_id)
        await db_pool.execute("""
            UPDATE followups SET status = 'cancelado'
            WHERE conversa_id = (SELECT id FROM conversas WHERE conversation_id = $1)
              AND status = 'pendente'
        """, conversation_id)
        logger.info(f"✅ Conversa {conversation_id} finalizada")
    except Exception as e:
        logger.error(f"Erro ao finalizar conversa {conversation_id}: {e}")

# --- WORKER DE MÉTRICAS DIÁRIAS ---
async def worker_metricas_diarias():
    """Worker que atualiza as métricas diárias a cada hora."""
    while True:
        await asyncio.sleep(3600)  # 1 hora
        if not db_pool:
            continue
        try:
            hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
            # Buscar todas as empresas (ou fixo)
            empresas = await db_pool.fetch("SELECT id FROM empresas")
            for emp in empresas:
                empresa_id = emp['id']
                # Buscar todas as unidades da empresa
                unidades = await db_pool.fetch("SELECT id FROM unidades WHERE empresa_id = $1", empresa_id)
                for unid in unidades:
                    unidade_id = unid['id']
                    # Calcular métricas do dia
                    total_conversas = await db_pool.fetchval("""
                        SELECT COUNT(*) FROM conversas 
                        WHERE empresa_id = $1 AND unidade_id = $2 AND DATE(created_at) = $3
                    """, empresa_id, unidade_id, hoje)
                    total_mensagens = await db_pool.fetchval("""
                        SELECT COUNT(*) FROM mensagens m
                        JOIN conversas c ON c.id = m.conversa_id
                        WHERE c.empresa_id = $1 AND c.unidade_id = $2 AND DATE(m.created_at) = $3
                    """, empresa_id, unidade_id, hoje)
                    leads = await db_pool.fetchval("""
                        SELECT COUNT(*) FROM conversas
                        WHERE empresa_id = $1 AND unidade_id = $2 AND lead_qualificado = true AND DATE(created_at) = $3
                    """, empresa_id, unidade_id, hoje)
                    tempo_medio = await db_pool.fetchval("""
                        SELECT AVG(EXTRACT(EPOCH FROM (primeira_resposta_em - primeira_mensagem))) 
                        FROM conversas
                        WHERE empresa_id = $1 AND unidade_id = $2 AND primeira_resposta_em IS NOT NULL AND DATE(created_at) = $3
                    """, empresa_id, unidade_id, hoje)
                    
                    await db_pool.execute("""
                        INSERT INTO metricas_diarias (empresa_id, unidade_id, data, total_conversas, total_mensagens, leads_qualificados, tempo_medio_resposta)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (empresa_id, unidade_id, data) DO UPDATE SET
                            total_conversas = EXCLUDED.total_conversas,
                            total_mensagens = EXCLUDED.total_mensagens,
                            leads_qualificados = EXCLUDED.leads_qualificados,
                            tempo_medio_resposta = EXCLUDED.tempo_medio_resposta,
                            updated_at = NOW()
                    """, empresa_id, unidade_id, hoje, total_conversas, total_mensagens, leads, tempo_medio)
            logger.info("📊 Métricas diárias atualizadas")
        except Exception as e:
            logger.error(f"Erro no worker de métricas diárias: {e}")

# --- PROCESSAMENTO IA E ÁUDIO ---
async def transcrever_audio(url: str):
    if not cliente_whisper:
        return "[Áudio recebido, mas Whisper não configurado]"
    async with whisper_semaphore:
        try:
            resp = await http_client.get(url, follow_redirects=True)
            audio_file = io.BytesIO(resp.content)
            audio_file.name = "audio.ogg"
            transcription = await cliente_whisper.audio.transcriptions.create(model="whisper-1", file=audio_file)
            return transcription.text
        except Exception as e:
            logger.error(f"Erro Whisper: {e}")
            return "[Erro ao transcrever áudio]"

async def processar_ia_e_responder(
    account_id: int, 
    conversation_id: int, 
    contact_id: int, 
    slug: str, 
    nome_cliente: str, 
    lock_val: str,
    empresa_id: int = EMPRESA_ID_PADRAO
):
    chave_lock = f"lock:{conversation_id}"
    watchdog = asyncio.create_task(renovar_lock(chave_lock, lock_val))
    
    try:
        await asyncio.sleep(2) 
        
        chave_buffet = f"buffet:{conversation_id}"
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.lrange(chave_buffet, 0, -1)
            pipe.delete(chave_buffet)
            resultado = await pipe.execute()
        
        mensagens_acumuladas = resultado[0]
        logger.info(f"📦 Buffer tem {len(mensagens_acumuladas)} mensagens para conv {conversation_id}")
        
        if not mensagens_acumuladas:
            return

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
        pergunta_final = " ".join(textos + list(transcricoes)).strip()
        if not pergunta_final and not imagens_urls:
            return

        # 🔄 RECHECAGEM DE CONTEXTO
        slug_detectado = await buscar_unidade_na_pergunta(pergunta_final, empresa_id)
        mudou_unidade = False
        
        if slug_detectado and slug_detectado != slug:
            logger.info(f"🔄 IA mudou contexto de {slug} para unidade: {slug_detectado}")
            slug = slug_detectado
            mudou_unidade = True
            await redis_client.setex(f"unidade_escolhida:{conversation_id}", 86400, slug)
            await bd_registrar_evento_funil(conversation_id, "mudanca_unidade", f"Contexto alterado para {slug}", score_incremento=1)

        # Salvar mensagem do usuário
        await bd_salvar_mensagem_local(conversation_id, "user", pergunta_final if pergunta_final else "[Enviou uma imagem]")

        unidade = await carregar_unidade(slug, empresa_id) or {}
        pers = await carregar_personalidade(slug, empresa_id) or {}
        nome_ia = pers.get('nome_ia') or 'Assistente Virtual'
        
        estado_raw = await redis_client.get(f"estado:{conversation_id}")
        estado_atual = descomprimir_texto(estado_raw) or "neutro"
        
        texto_norm_fast = normalizar(pergunta_final)
        fast_reply = None
        
        # Extrair campos da unidade
        end_banco = unidade.get('endereco_completo') or unidade.get('endereco')
        hor_banco = unidade.get('horarios')
        pre_banco = unidade.get('planos')
        link_mat = unidade.get('link_matricula') or unidade.get('site') or 'nosso site oficial'
        tel_banco = unidade.get('telefone') or unidade.get('whatsapp')
        
        # ⚡ FAST-PATH
        if not imagens_urls:
            if re.search(r"(quais (sao as )?unidades|quantas unidades|unidades voces tem|tem outras unidades|lista de unidades|onde (voces )?tem academia)", texto_norm_fast):
                todas_ativas = await listar_unidades_ativas(empresa_id)
                lista_str = "\n".join([f"• {u['nome']}" + (f" ({u['cidade']})" if u.get('cidade') else "") for u in todas_ativas])
                fast_reply = f"🏢 Nós temos as seguintes unidades disponíveis:\n\n{lista_str}\n\nQual delas você quer conhecer melhor?"
                logger.info(f"⚡ Fast-path: listar unidades acionado")
            
            elif unidade:
                if re.search(r"(endereco|enderco|local|localizacao|fica onde|onde fica|como chego|qual o local)", texto_norm_fast):
                    if end_banco and str(end_banco).strip().lower() not in ['não informado', 'none', '']:
                        fast_reply = f"📍 Nossa unidade fica em:\n{end_banco}\n\nPosso te ajudar com mais alguma dúvida?"
                        logger.info(f"⚡ Fast-path: endereço acionado")
                
                elif re.search(r"(horario|funcionamento|abre|fecha|que horas|ta aberto)", texto_norm_fast):
                    if hor_banco:
                        if isinstance(hor_banco, dict):
                            horario_str = "\n".join([f"{dia}: {h}" for dia, h in hor_banco.items()])
                        else:
                            horario_str = str(hor_banco)
                        fast_reply = f"🕒 Nosso horário de funcionamento é:\n{horario_str}\n\nSe quiser, posso te ajudar com planos e valores também!"
                        logger.info(f"⚡ Fast-path: horários acionado")

                elif re.search(r"(preco|valor|quanto custa|mensalidade|planos|promocao)", texto_norm_fast):
                    if pre_banco:
                        if isinstance(pre_banco, dict):
                            planos_str = "\n".join([f"• {k}: R${v.get('preco', 'consultar')} - {v.get('descricao', '')}" for k, v in pre_banco.items()])
                        else:
                            planos_str = str(pre_banco)
                        fast_reply = f"💰 Sobre nossos planos:\n{planos_str}\n\nVocê pode ver os detalhes e se matricular por aqui: {link_mat}"
                        logger.info(f"⚡ Fast-path: planos acionado")

                elif re.search(r"(telefone|contato|whatsapp|numero|ligar)", texto_norm_fast):
                    if tel_banco and str(tel_banco).strip().lower() not in ['não informado', 'none', '']:
                        fast_reply = f"📞 Claro! Nosso número de contato é:\n{tel_banco}\n\nPosso ajudar com mais algo?"
                        logger.info(f"⚡ Fast-path: contato acionado")

        # 🎯 DETECÇÃO DE INTENÇÃO PARA CACHE
        intencao = detectar_intencao(pergunta_final)
        
        if intencao:
            chave_cache_ia = f"cache:intent:{slug}:{intencao}"
            logger.info(f"🎯 Intenção detectada: {intencao} - usando chave: {chave_cache_ia}")
        else:
            hash_pergunta = hashlib.md5(texto_norm_fast.encode('utf-8')).hexdigest()
            chave_cache_ia = f"cache:ia:{slug}:{hash_pergunta}"
            
        resposta_cacheada = await redis_client.get(chave_cache_ia)

        if fast_reply:
            logger.info(f"⚡ Fast-Path Ativado! Respondendo sem IA.")
            resposta_texto = fast_reply
            novo_estado = estado_atual
            
        elif resposta_cacheada and not imagens_urls and not mudou_unidade:
            logger.info(f"🧠 Cache Hit! Respondendo direto do Redis. Chave: {chave_cache_ia}")
            dados_cache = json.loads(resposta_cacheada)
            resposta_texto = dados_cache["resposta"]
            novo_estado = dados_cache["estado"]
            
        else:
            # --- FLUXO IA ---
            faq = await carregar_faq_unidade(slug, empresa_id) or ""
            historico = await bd_obter_historico_local(conversation_id) or "Sem histórico."
            
            todas_unidades = await listar_unidades_ativas(empresa_id)
            lista_unidades_nomes = ", ".join([u["nome"] for u in todas_unidades])
            
            nome_empresa = unidade.get('nome_empresa') or 'Nossa Empresa'
            nome_unidade = unidade.get('nome') or 'Unidade Matriz'
            link_principal = unidade.get('link_matricula') or unidade.get('site') or 'nosso site oficial'
            
            # Formatar dados
            horarios_str = ""
            if hor_banco:
                if isinstance(hor_banco, dict):
                    horarios_str = "\n".join([f"- {dia}: {h}" for dia, h in hor_banco.items()])
                else:
                    horarios_str = str(hor_banco)
            else:
                horarios_str = "não informado"
                
            planos_str = ""
            if pre_banco:
                if isinstance(pre_banco, dict):
                    planos_str = "\n".join([f"- {k}: R${v.get('preco', 'consultar')} - {v.get('descricao', '')}" for k, v in pre_banco.items()])
                else:
                    planos_str = str(pre_banco)
            else:
                planos_str = "não informado"
            
            dados_unidade = f"""
            DADOS COMPLETOS DA UNIDADE
            Nome da unidade: {unidade.get('nome') or 'não informado'}
            Empresa: {unidade.get('nome_empresa') or 'não informado'}
            Endereço: {end_banco or 'não informado'}
            Cidade/Estado: {unidade.get('cidade') or 'não informado'} / {unidade.get('estado') or 'não informado'}
            CEP: {unidade.get('cep') or 'não informado'}
            Telefone: {tel_banco or 'não informado'}
            Horários:
            {horarios_str}
            Link de matrícula: {link_principal}
            Link do site: {unidade.get('site') or 'não informado'}
            Instagram: {unidade.get('instagram') or 'não informado'}
            Modalidades disponíveis: {', '.join(unidade.get('modalidades', [])) if unidade.get('modalidades') else 'não informado'}
            Planos disponíveis:
            {planos_str}
            Infraestrutura: {json.dumps(unidade.get('infraestrutura', {}), ensure_ascii=False) if unidade.get('infraestrutura') else 'não informado'}
            Serviços: {json.dumps(unidade.get('servicos', {}), ensure_ascii=False) if unidade.get('servicos') else 'não informado'}
            Formas de pagamento aceitas: {', '.join(unidade.get('formas_pagamento', [])) if unidade.get('formas_pagamento') else 'não informado'}
            Convênios aceitos: {', '.join(unidade.get('convenios', [])) if unidade.get('convenios') else 'não informado'}
            Descrição da unidade: {unidade.get('descricao') or 'não informado'}
            """
            
            tom_voz = pers.get('tom_voz') or 'Profissional, claro e prestativo'
            instrucoes_base = pers.get('instrucoes_base') or f"Atenda o cliente de forma educada e tire dúvidas sobre os serviços da {nome_empresa}."
            
            regras_padrao = (
                "1. Seja breve e objetivo.\n"
                "2. Se a informação existir nos DADOS DA UNIDADE, responda diretamente sem sugerir acessar o site ou ligar.\n"
                "3. Forneça respostas diretas baseadas no FAQ e nos Dados da Unidade.\n"
                "4. Formate SEMPRE sua resposta com parágrafos curtos, tópicos/listas (se aplicável) e quebras de linha para facilitar a leitura."
            )
            regras_atendimento = pers.get('regras_atendimento') or regras_padrao

            aviso_mudanca = f"\n[AVISO DE SISTEMA]: O cliente acaba de solicitar informações especificamente sobre a unidade {nome_unidade}. Baseie sua próxima resposta SOMENTE nos dados abaixo e reconheça essa mudança de forma natural se necessário." if mudou_unidade else ""

            prompt_sistema = f"""Você é {nome_ia}, assistente virtual da empresa {nome_empresa} (Unidade atual: {nome_unidade}).
            Personalidade e Tom de Voz: {tom_voz}
            {aviso_mudanca}
            
            UNIDADES DISPONÍVEIS NA REDE:
            {lista_unidades_nomes}
            
            INSTRUÇÕES GERAIS:
            {instrucoes_base}
            
            REGRAS DE ATENDIMENTO (Siga estritamente):
            {regras_atendimento}
            * Se o cliente demonstrar intenção clara de compra ou conversão (matrícula/agendamento), direcione para o link principal: {link_principal}.
            
            {dados_unidade}

            FAQ DA UNIDADE ({nome_unidade}):
            {faq if faq else 'Nenhum FAQ cadastrado.'}
            
            DADOS DO ATENDIMENTO ATUAL:
            Nome do Cliente: {nome_cliente}
            Estado/Sentimento Anterior: {estado_atual}
            
            MUITO IMPORTANTE:
            Você deve SEMPRE responder estritamente no formato JSON válido.
            Formato exigido:
            {{
                "resposta": "a sua mensagem final formatada para o cliente",
                "estado": "qual o estado atual do cliente numa única palavra"
            }}
            """

            conteudo_usuario = []
            if pergunta_final:
                conteudo_usuario.append({"type": "text", "text": f"Histórico:\n{historico}\n\nCliente diz: {pergunta_final}"})
            else:
                conteudo_usuario.append({"type": "text", "text": f"Histórico:\n{historico}\n\nO cliente enviou uma imagem. Analise-a."})
                
            for img_url in imagens_urls:
                try:
                    resp = await http_client.get(img_url, headers={"api_access_token": CHATWOOT_TOKEN}, follow_redirects=True)
                    if resp.status_code == 200:
                        img_b64 = base64.b64encode(resp.content).decode("utf-8")
                        mime_type = "image/png" if ".png" in img_url.lower() else "image/webp" if ".webp" in img_url.lower() else "image/jpeg"
                        conteudo_usuario.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_b64}"}})
                except Exception as e:
                    logger.error(f"Erro ao baixar imagem: {e}")

            modelo_escolhido = "google/gemini-2.5-flash" if imagens_urls else "google/gemini-2.5-flash-lite"

            start_time = time.time()
            async with llm_semaphore:
                try:
                    response = await cliente_ia.chat.completions.create(
                        model=modelo_escolhido, 
                        messages=[{"role": "system", "content": prompt_sistema}, {"role": "user", "content": conteudo_usuario}],
                        temperature=0.7, timeout=30, response_format={"type": "json_object"}
                    )
                    resposta_bruta = response.choices[0].message.content
                except Exception as e:
                    logger.warning(f"Fallback para Gemini Flash devido a erro: {e}")
                    response = await cliente_ia.chat.completions.create(
                        model="google/gemini-2.5-flash",
                        messages=[{"role": "system", "content": prompt_sistema}, {"role": "user", "content": conteudo_usuario}],
                        temperature=0.7, response_format={"type": "json_object"}
                    )
                    resposta_bruta = response.choices[0].message.content
            
            logger.info(f"⏱️ LLM Latency ({modelo_escolhido}): {time.time() - start_time:.2f}s | Conv: {conversation_id}")

            # Limpeza de markdown
            resposta_bruta = resposta_bruta.strip()
            if resposta_bruta.startswith("```"):
                resposta_bruta = re.sub(r'^```(?:json)?\s*', '', resposta_bruta)
                resposta_bruta = re.sub(r'\s*```$', '', resposta_bruta)
                resposta_bruta = resposta_bruta.strip()
                logger.info("🧹 Bloco de código markdown removido do JSON")

            try:
                dados_ia = json.loads(resposta_bruta)
                resposta_texto = dados_ia.get("resposta", "Desculpe, não consegui processar a informação.")
                novo_estado = dados_ia.get("estado", estado_atual).strip().lower()
                
                if not imagens_urls:
                    await redis_client.setex(chave_cache_ia, 600, json.dumps({"resposta": resposta_texto, "estado": novo_estado}))
                    logger.info(f"💾 Resposta em cache com chave: {chave_cache_ia}")
                    
            except json.JSONDecodeError:
                logger.error(f"❌ Erro ao decodificar JSON da IA. Resposta bruta: {resposta_bruta[:200]}...")
                resposta_texto = "Desculpe, tive um problema ao processar sua solicitação. Pode reformular?"
                novo_estado = estado_atual

        # Aplicar estado
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.setex(f"estado:{conversation_id}", 86400, comprimir_texto(novo_estado))
            pipe.lpush(f"hist_estado:{conversation_id}", f"{datetime.now(ZoneInfo('America/Sao_Paulo')).isoformat()}|{novo_estado}")
            pipe.ltrim(f"hist_estado:{conversation_id}", 0, 10)
            pipe.expire(f"hist_estado:{conversation_id}", 86400)
            await pipe.execute()

        if "interessado" in novo_estado or "conversao" in novo_estado or "matricula" in novo_estado:
            await bd_registrar_evento_funil(conversation_id, "interesse_detectado", f"Detectou estado: {novo_estado}")

        await bd_salvar_mensagem_local(conversation_id, "assistant", resposta_texto)

        is_manual_atendimento = (await redis_client.get(f"atend_manual:{conversation_id}")) == "1"
        pedacos = [p.strip() for p in resposta_texto.split("\n") if p.strip()]
        
        # Envio da mensagem
        for i, p in enumerate(pedacos):
            if is_manual_atendimento or await redis_client.exists(f"pause_ia:{conversation_id}"):
                break
            await asyncio.sleep(min(len(p) * 0.04, 4) + random.uniform(0.5, 1.5))
            
            await enviar_mensagem_chatwoot(account_id, conversation_id, p, nome_ia)
            
            await bd_atualizar_msg_ia(conversation_id)
            if i == 0:
                await bd_registrar_primeira_resposta(conversation_id)
        
        if not is_manual_atendimento:
            await agendar_followups(conversation_id, account_id, slug, empresa_id)

    except Exception as e:
        logger.error(f"🔥 Erro Crítico: {e}", exc_info=True)
    finally:
        watchdog.cancel()
        try:
            await redis_client.eval(LUA_RELEASE_LOCK, 1, chave_lock, lock_val)
        except:
            pass

# --- WEBHOOK ENDPOINT ---
async def validar_assinatura(request: Request, signature: str):
    if not CHATWOOT_WEBHOOK_SECRET:
        return
    body = await request.body()
    expected = hmac.new(CHATWOOT_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature or "", expected):
        raise HTTPException(status_code=401, detail="Assinatura inválida")

@app.post("/webhook")
async def chatwoot_webhook(request: Request, background_tasks: BackgroundTasks, x_chatwoot_signature: str = Header(None)):
    await validar_assinatura(request, x_chatwoot_signature)
    payload = await request.json()
    
    event = payload.get("event")
    id_conv = payload.get("conversation", {}).get("id") or payload.get("id")
    account_id = payload.get("account", {}).get("id")

    rate_key = f"rate:{id_conv}"
    contador = await redis_client.incr(rate_key)
    if contador == 1:
        await redis_client.expire(rate_key, 10)
    if contador > 10:
        return {"status": "rate_limit"}

    conv_obj = payload.get("conversation", {}) if "conversation" in payload else payload
    if conv_obj:
        is_manual = "1" if (conv_obj.get("assignee_id") is not None or conv_obj.get("status") not in ["pending", "open", None]) else "0"
        await redis_client.setex(f"atend_manual:{id_conv}", 86400, is_manual)

    if event == "conversation_updated":
        if conv_obj.get("status") == "resolved":
            await bd_finalizar_conversa(id_conv)
            await redis_client.delete(
                f"pause_ia:{id_conv}", 
                f"estado:{id_conv}", 
                f"unidade_escolhida:{id_conv}", 
                f"esperando_unidade:{id_conv}"
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

    labels = payload.get("conversation", {}).get("labels", [])
    
    slug_label = next((str(l).lower().strip() for l in labels if l), None)
    slug_redis = await redis_client.get(f"unidade_escolhida:{id_conv}")
    slug = slug_redis or slug_label

    slug_detectado = None

    if message_type == "incoming" and conteudo_texto:
        slug_detectado = await buscar_unidade_na_pergunta(conteudo_texto, EMPRESA_ID_PADRAO)
        if slug_detectado and slug_detectado != slug:
            logger.info(f"🔄 Webhook interceptou mudança de contexto para: {slug_detectado}")
            slug = slug_detectado
            await redis_client.setex(f"unidade_escolhida:{id_conv}", 86400, slug)

    if not slug and message_type == "incoming":
        unidades_ativas = await listar_unidades_ativas(EMPRESA_ID_PADRAO)
        
        if not unidades_ativas:
            return {"status": "sem_unidades_ativas"}
            
        elif len(unidades_ativas) == 1:
            slug = unidades_ativas[0]["slug"]
            await redis_client.setex(f"unidade_escolhida:{id_conv}", 86400, slug)
            
        else:
            texto_cliente = normalizar(conteudo_texto).strip()
            
            if not slug_detectado and texto_cliente.isdigit():
                idx = int(texto_cliente) - 1
                if 0 <= idx < len(unidades_ativas):
                    slug_detectado = unidades_ativas[idx]["slug"]
                        
            if slug_detectado:
                slug = slug_detectado
                await redis_client.setex(f"unidade_escolhida:{id_conv}", 86400, slug)
                await redis_client.delete(f"esperando_unidade:{id_conv}")
                contato = payload.get("sender", {})
                await bd_iniciar_conversa(
                    id_conv, slug, account_id, 
                    contato.get("id"), limpar_nome(contato.get("name")), 
                    EMPRESA_ID_PADRAO
                )
                await bd_registrar_evento_funil(id_conv, "unidade_escolhida", f"Cliente escolheu a unidade {slug}", score_incremento=3)
                
            else:
                cfg = await carregar_configuracao_global(EMPRESA_ID_PADRAO)
                boas_vindas = cfg.get("mensagem_boas_vindas") or "Olá! 😊 Seja bem-vindo."
                
                nomes_unidades = "\n".join([f"• {u['nome']}" + (f" ({u['cidade']})" if u.get('cidade') else "") for u in unidades_ativas])
                
                mensagem = f"""{boas_vindas}

Só pra eu te direcionar melhor 🙂
Qual unidade você quer falar?

{nomes_unidades}

Se preferir, pode me dizer o nome ou a cidade também."""
                
                await enviar_mensagem_chatwoot(account_id, id_conv, mensagem)
                await redis_client.setex(f"esperando_unidade:{id_conv}", 86400, "1")
                background_tasks.add_task(monitorar_escolha_unidade, account_id, id_conv)
                return {"status": "aguardando_escolha_unidade"}

    if not slug:
        return {"status": "erro_sem_unidade"}

    if message_type == "outgoing" and sender_type == "user":
        if is_ai_message:
            return {"status": "ignorado_mensagem_ia"}
        await redis_client.setex(f"pause_ia:{id_conv}", 43200, "1")
        if db_pool:
            await db_pool.execute("""
                UPDATE followups SET status = 'cancelado'
                WHERE conversa_id = (SELECT id FROM conversas WHERE conversation_id = $1)
                  AND status = 'pendente'
            """, id_conv)
        return {"status": "ia_pausada"}

    if message_type != "incoming":
        return {"status": "ignorado_nao_incoming"}

    contato = payload.get("sender", {})
    await bd_iniciar_conversa(
        id_conv, slug, account_id, 
        contato.get("id"), limpar_nome(contato.get("name")), 
        EMPRESA_ID_PADRAO
    )
    await bd_atualizar_msg_cliente(id_conv)

    if await redis_client.exists(f"pause_ia:{id_conv}"):
        return {"status": "ignorado_ia_pausada"}

    anexos = payload.get("attachments") or payload.get("message", {}).get("attachments", [])
    arquivos_encontrados = []
    for a in anexos:
        file_type = str(a.get("file_type", "")).lower()
        tipo = "image" if file_type.startswith("image") or "image" in file_type else "audio" if file_type.startswith("audio") or "audio" in file_type else "documento"
        arquivos_encontrados.append({"url": a.get("data_url"), "type": tipo})

    chave_buffet = f"buffet:{id_conv}"
    await redis_client.rpush(chave_buffet, json.dumps({"text": conteudo_texto, "files": arquivos_encontrados}))
    await redis_client.expire(chave_buffet, 60)

    lock_val = str(uuid.uuid4())
    if await redis_client.set(f"lock:{id_conv}", lock_val, nx=True, ex=180):
        background_tasks.add_task(
            processar_ia_e_responder, 
            account_id, 
            id_conv, 
            contato.get("id"), 
            slug, 
            limpar_nome(contato.get("name")), 
            lock_val,
            EMPRESA_ID_PADRAO
        )
        return {"status": "processando"}
    
    return {"status": "acumulando_no_buffet"}

@app.get("/desbloquear/{conversation_id}")
async def desbloquear_ia(conversation_id: int):
    if await redis_client.delete(f"pause_ia:{conversation_id}"):
        return {"status": "sucesso", "mensagem": f"✅ IA reativada para a conversa {conversation_id}!"}
    return {"status": "aviso", "mensagem": f"A conversa {conversation_id} não estava pausada."}

@app.get("/")
async def health(): 
    return {"status": "🤖 Motor SaaS Full Stack com Cache Semântico e Métricas Diárias! 🚀"}
