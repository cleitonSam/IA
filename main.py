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

CHATWOOT_URL = os.getenv("CHATWOOT_URL")
CHATWOOT_TOKEN = os.getenv("CHATWOOT_TOKEN")

app = FastAPI()

# --- CONFIGURAÇÕES E VARIÁVEIS DE AMBIENTE ---
CHATWOOT_WEBHOOK_SECRET = os.getenv("CHATWOOT_WEBHOOK_SECRET")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REDIS_URL = os.getenv("REDIS_URL")
DATABASE_URL = os.getenv("DATABASE_URL")

EMPRESA_ID_PADRAO = 1

# 👋 SAUDAÇÕES — usadas para detectar mensagens de abertura sem intenção real
SAUDACOES = {
    "oi", "ola", "olá", "hey", "boa", "salve", "eai", "e ai",
    "bom dia", "boa tarde", "boa noite", "tudo bem", "tudo bom",
    "como vai", "oi tudo", "ola tudo", "oii", "oiii", "opa"
}

def eh_saudacao(texto: str) -> bool:
    """Retorna True se a mensagem for apenas uma saudação genérica (sem intenção real)."""
    if not texto:
        return False
    norm = normalizar(texto).strip()
    palavras = norm.split()
    # Mensagem curta (até 5 palavras) que começa ou contém saudação
    if len(palavras) <= 5:
        return any(s in norm for s in SAUDACOES)
    return False

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

# ==================== MENSAGENS PRÉ-FORMATADAS ====================
# Removido ** (markdown duplo) — WhatsApp usa *asterisco simples* para negrito

RESPOSTAS_UNIDADES = [
    "🏢 Temos {total} unidades disponíveis:\n\n{lista_str}\n\nQual delas você gostaria de conhecer melhor?",
    "Claro! Nossas {total} unidades são:\n\n{lista_str}\n\nMe diga qual é a mais conveniente para você!",
    "Aqui estão todas as nossas {total} unidades:\n\n{lista_str}\n\nEm qual delas podemos ajudar?",
    "Fico feliz em ajudar! Nossas academias ({total} no total) estão localizadas em:\n\n{lista_str}\n\nQual você prefere?"
]

RESPOSTAS_ENDERECO = [
    "📍 Ficamos aqui:\n{endereco}\n\nPosso te ajudar com mais alguma dúvida?",
    "Nosso endereço é:\n{endereco}\n\nPrecisando de mais informações, é só falar!",
    "Estamos localizados em:\n{endereco}\n\nSe quiser, também posso passar os horários de funcionamento."
]

RESPOSTAS_HORARIO = [
    "🕒 Nosso horário de funcionamento é:\n\n{horario_str}\n\nSe quiser, posso te ajudar com planos e valores também!",
    "Funcionamos nos seguintes horários:\n\n{horario_str}\n\nAlguma dúvida sobre os horários?",
    "Horário de atendimento:\n\n{horario_str}\n\nEstamos prontos para te receber! 💪"
]

RESPOSTAS_CONTATO = [
    "📞 Nosso número de contato é:\n{tel_banco}\n\nPosso ajudar com mais algo?",
    "Pode entrar em contato conosco pelo telefone:\n{tel_banco}\n\nEstamos à disposição!",
    "Nosso WhatsApp é:\n{tel_banco}\n\nFique à vontade para chamar! 😊"
]
# ===================================================================


@app.on_event("startup")
async def startup_event():
    global http_client, redis_client, db_pool
    http_client = httpx.AsyncClient(
        timeout=30.0,
        limits=httpx.Limits(max_keepalive_connections=20, max_connections=50)
    )

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
    asyncio.create_task(worker_metricas_diarias())
    asyncio.create_task(worker_sync_planos())


@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()
    await redis_client.aclose()
    if db_pool:
        await db_pool.close()
    logger.info("🛑 Servidor desligado.")


# --- UTILITÁRIOS ---

def normalizar(texto: str) -> str:
    """Remove acentos e converte para minúsculas"""
    if not texto:
        return ""
    return unicodedata.normalize("NFD", str(texto).lower()).encode("ascii", "ignore").decode("utf-8")


def comprimir_texto(texto: str) -> str:
    if not texto:
        return ""
    dados = zlib.compress(texto.encode('utf-8'))
    return base64.b64encode(dados).decode('utf-8')


def descomprimir_texto(texto_comprimido: str) -> str:
    if not texto_comprimido:
        return ""
    try:
        dados = base64.b64decode(texto_comprimido)
        return zlib.decompress(dados).decode('utf-8')
    except Exception:
        return texto_comprimido


def limpar_nome(nome):
    if not nome:
        return "Cliente"
    return re.sub(r"[^a-zA-ZÀ-ÿ\s]", "", str(nome)).strip()


def limpar_markdown(texto: str) -> str:
    """
    Converte markdown para formato compatível com WhatsApp/Chatwoot:
    - [texto](url)  →  url
    - **texto**     →  *texto*  (WhatsApp usa asterisco simples para negrito)
    - __texto__     →  _texto_
    - Remove ### headers
    """
    if not texto:
        return texto

    # [texto](url) → url  (evita colchetes e parênteses feios)
    texto = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\2', texto)

    # **texto** → *texto*
    texto = re.sub(r'\*\*(.+?)\*\*', r'*\1*', texto)

    # __texto__ → _texto_
    texto = re.sub(r'__(.+?)__', r'_\1_', texto)

    # ### Título → Título (remove headers markdown)
    texto = re.sub(r'^#{1,6}\s+', '', texto, flags=re.MULTILINE)

    return texto


def formatar_planos_bonito(planos: List[Dict]) -> str:
    """
    Formata os planos de forma bonita para envio ao cliente via WhatsApp/Chatwoot.
    Retorna UMA string única (sem \n\n entre planos) para ser enviada como uma só mensagem.
    """
    if not planos:
        return "Não temos planos disponíveis no momento. 😕"

    SEPARADOR = "\n─────────────────\n"
    blocos = []

    for p in planos:
        nome = p.get('nome', 'Plano')
        link = p.get('link_venda', '')

        if not link or link.strip() == '':
            continue

        try:
            valor_float = float(p['valor']) if p.get('valor') is not None else None
        except (TypeError, ValueError):
            valor_float = None

        try:
            promo_float = float(p['valor_promocional']) if p.get('valor_promocional') is not None else None
        except (TypeError, ValueError):
            promo_float = None

        meses_promo = p.get('meses_promocionais')
        diferenciais = p.get('diferenciais') or []

        linhas = [f"🏅 *{nome}*"]

        if valor_float and valor_float > 0:
            linhas.append(f"💰 R$ {valor_float:.2f}/mês")

        if promo_float and meses_promo and promo_float > 0:
            linhas.append(f"⚡ Promoção: {meses_promo}x R$ {promo_float:.2f}")

        if diferenciais:
            if isinstance(diferenciais, list):
                # Quebra diferenciais longos em linhas de até 3 itens
                chunks = [diferenciais[i:i+3] for i in range(0, len(diferenciais), 3)]
                for chunk in chunks:
                    linhas.append(f"✨ {' · '.join(chunk)}")
            else:
                linhas.append(f"✨ {diferenciais}")

        linhas.append(f"🔗 {link}")
        blocos.append("\n".join(linhas))

    if not blocos:
        return "Não temos planos disponíveis no momento. 😕"

    cabecalho = "💪 *Nossos Planos*"
    rodape = "\nQuer saber mais sobre algum plano? É só perguntar! 😊"
    return cabecalho + "\n" + SEPARADOR.join(blocos) + rodape


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


# --- FUNÇÕES DE INTEGRAÇÃO (BUSCA POR EMPRESA) ---

async def buscar_empresa_por_account_id(account_id: int) -> Optional[int]:
    """
    Retorna o ID da empresa associada ao account_id do Chatwoot.
    """
    if not db_pool:
        return None

    cache_key = f"map:account:{account_id}"
    cached = await redis_client.get(cache_key)
    if cached:
        return int(cached)

    try:
        query = """
            SELECT empresa_id FROM integracoes
            WHERE tipo = 'chatwoot'
              AND ativo = true
              AND config->>'account_id' = $1::text
            LIMIT 1
        """
        row = await db_pool.fetchrow(query, str(account_id))
        if row:
            empresa_id = row['empresa_id']
            await redis_client.setex(cache_key, 3600, str(empresa_id))
            return empresa_id
        return None
    except Exception as e:
        logger.error(f"Erro ao buscar empresa por account_id {account_id}: {e}")
        return None


async def carregar_integracao(empresa_id: int, tipo: str = 'chatwoot') -> Optional[Dict[str, Any]]:
    """
    Carrega a configuração de integração ativa de uma empresa.
    """
    if not db_pool:
        return None

    cache_key = f"cfg:integracao:{empresa_id}:{tipo}"
    cache = await redis_client.get(cache_key)
    if cache:
        return json.loads(cache)

    try:
        query = """
            SELECT config
            FROM integracoes
            WHERE empresa_id = $1 AND tipo = $2 AND ativo = true
            LIMIT 1
        """
        row = await db_pool.fetchrow(query, empresa_id, tipo)
        if row:
            config = row['config']
            if isinstance(config, str):
                config = json.loads(config)
            await redis_client.setex(cache_key, 300, json.dumps(config))
            return config
        return None
    except Exception as e:
        logger.error(f"Erro ao carregar integração {tipo} da empresa {empresa_id}: {e}")
        return None


# --- FUNÇÕES PARA INTEGRAÇÃO EVO ---

async def buscar_planos_evo_da_api(empresa_id: int) -> Optional[List[Dict]]:
    """
    Busca os planos (memberships) da academia via API Evo diretamente.
    """
    if not db_pool:
        return None

    integracao = await carregar_integracao(empresa_id, 'evo')
    if not integracao:
        logger.info(f"ℹ️ Empresa {empresa_id} não tem integração Evo ativa")
        return None

    dns = integracao.get('dns')
    secret_key = integracao.get('secret_key')
    if not dns or not secret_key:
        logger.error(f"Integração Evo da empresa {empresa_id} incompleta: DNS ou Secret Key ausentes")
        return None

    api_base = integracao.get('api_url', 'https://evo-integracao-api.w12app.com.br/api/v2')
    url = (
        f"{api_base}/membership?take=100&skip=0&active=true"
        "&showAccessBranches=false&showOnlineSalesObservation=false"
        "&showActivitiesGroups=false&externalSaleAvailable=false"
    )

    auth = base64.b64encode(f"{dns}:{secret_key}".encode()).decode()
    headers = {'Authorization': f'Basic {auth}', 'accept': 'application/json'}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()

        items = None
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            possible_keys = ['data', 'items', 'results', 'memberships', 'planos', 'lista', 'list']
            for key in possible_keys:
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    break
            if items is None:
                logger.error(f"Resposta da API Evo sem lista reconhecida. Chaves: {list(data.keys())}")
                return None
        else:
            logger.error(f"Formato inesperado da API Evo: {type(data)}")
            return None

        planos = []
        for item in items:
            if not isinstance(item, dict):
                continue
            diferenciais = item.get('differentials', [])
            if isinstance(diferenciais, list):
                diffs = [d.get('title') for d in diferenciais if isinstance(d, dict) and d.get('title')]
            else:
                diffs = []

            plano = {
                'id': item.get('idMembership'),
                'nome': item.get('displayName') or item.get('nameMembership', 'Plano'),
                'valor': item.get('value'),
                'valor_promocional': item.get('valuePromotionalPeriod'),
                'meses_promocionais': item.get('monthsPromotionalPeriod'),
                'descricao': item.get('description'),
                'diferenciais': diffs,
                'link_venda': item.get('urlSale'),
            }
            planos.append(plano)

        return planos

    except Exception as e:
        logger.error(f"Erro ao buscar planos Evo da API para empresa {empresa_id}: {e}")
        return None


async def sincronizar_planos_evo(empresa_id: int) -> int:
    """
    Busca planos da API Evo e insere/atualiza na tabela planos.
    """
    if not db_pool:
        return 0

    planos_api = await buscar_planos_evo_da_api(empresa_id)
    if not planos_api:
        return 0

    count = 0
    for p in planos_api:
        if not p.get('link_venda'):
            continue

        existing = await db_pool.fetchval(
            "SELECT id FROM planos WHERE empresa_id = $1 AND id_externo = $2",
            empresa_id, p['id']
        )
        if existing:
            await db_pool.execute("""
                UPDATE planos SET
                    nome = $1, valor = $2, valor_promocional = $3, meses_promocionais = $4,
                    descricao = $5, diferenciais = $6, link_venda = $7, updated_at = NOW()
                WHERE id = $8
            """, p['nome'], p['valor'], p['valor_promocional'], p['meses_promocionais'],
               p['descricao'], p['diferenciais'], p['link_venda'], existing)
        else:
            await db_pool.execute("""
                INSERT INTO planos
                    (empresa_id, id_externo, nome, valor, valor_promocional, meses_promocionais,
                     descricao, diferenciais, link_venda, ativo, ordem)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, true, 0)
            """, empresa_id, p['id'], p['nome'], p['valor'], p['valor_promocional'],
               p['meses_promocionais'], p['descricao'], p['diferenciais'], p['link_venda'])
            count += 1

    await redis_client.delete(f"planos:ativos:{empresa_id}:todos")
    logger.info(f"✅ Sincronizados {count} novos planos para empresa {empresa_id}")
    return count


async def buscar_planos_ativos(empresa_id: int, unidade_id: int = None, force_sync: bool = False) -> List[Dict]:
    """
    Retorna planos ativos da empresa, ordenados por ordem e nome.
    """
    if not db_pool:
        return []

    cache_key = f"planos:ativos:{empresa_id}:{unidade_id or 'todos'}"
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    query = """
        SELECT * FROM planos
        WHERE empresa_id = $1 AND ativo = true
          AND link_venda IS NOT NULL AND link_venda != ''
    """
    params = [empresa_id]
    if unidade_id:
        query += " AND (unidade_id = $2 OR unidade_id IS NULL)"
        params.append(unidade_id)
    query += " ORDER BY ordem, nome"

    rows = await db_pool.fetch(query, *params)
    planos = [dict(r) for r in rows]

    if not planos and force_sync:
        logger.info(f"🔄 Nenhum plano ativo no banco para empresa {empresa_id}. Tentando sincronizar da API...")
        await sincronizar_planos_evo(empresa_id)
        rows = await db_pool.fetch(query, *params)
        planos = [dict(r) for r in rows]

    await redis_client.setex(cache_key, 300, json.dumps(planos, default=str))
    return planos


def formatar_planos_para_prompt(planos: List[Dict]) -> str:
    """
    Formata planos para inserção no prompt da IA (texto técnico, sem markdown decorativo).
    """
    if not planos:
        return "Nenhum plano disponível no momento."

    linhas = []
    for p in planos:
        nome = p.get('nome', 'Plano')
        link = p.get('link_venda', '')
        if not link or link.strip() == '':
            continue

        try:
            valor_float = float(p['valor']) if p.get('valor') is not None else None
        except (TypeError, ValueError):
            valor_float = None

        try:
            promocao_float = float(p['valor_promocional']) if p.get('valor_promocional') is not None else None
        except (TypeError, ValueError):
            promocao_float = None

        meses_promo = p.get('meses_promocionais')
        diferenciais = p.get('diferenciais', [])

        linha = f"- {nome}"
        if valor_float and valor_float > 0:
            linha += f": R$ {valor_float:.2f}/mes"
        if promocao_float and meses_promo and promocao_float > 0:
            linha += f" (promocao {meses_promo} mes(es) por R$ {promocao_float:.2f})"
        if diferenciais:
            diffs_str = ", ".join(diferenciais) if isinstance(diferenciais, list) else str(diferenciais)
            linha += f" | Diferenciais: {diffs_str}"
        linha += f" | Link: {link}"
        linhas.append(linha)

    return "\n".join(linhas) if linhas else "Nenhum plano disponível no momento."


async def worker_sync_planos():
    while True:
        await asyncio.sleep(21600)  # 6 horas
        if not db_pool:
            continue
        try:
            empresas = await db_pool.fetch("SELECT id FROM empresas")
            for emp in empresas:
                await sincronizar_planos_evo(emp['id'])
        except Exception as e:
            logger.error(f"Erro no worker de sincronização de planos: {e}")


@app.get("/sync-planos/{empresa_id}")
async def sync_planos_manual(empresa_id: int):
    count = await sincronizar_planos_evo(empresa_id)
    await redis_client.delete(f"planos:ativos:{empresa_id}:todos")
    return {"status": "ok", "sincronizados": count}


# --- FUNÇÃO CENTRALIZADA DE ENVIO PARA O CHATWOOT ---

async def enviar_mensagem_chatwoot(
    account_id: int,
    conversation_id: int,
    content: str,
    nome_ia: str,
    integracao: dict
):
    url_base = integracao.get('url')
    token = integracao.get('token')
    if not url_base or not token:
        logger.error("Integração Chatwoot incompleta: url ou token ausentes")
        return None

    # Limpa markdown incompatível antes de enviar
    content = limpar_markdown(content)

    url_m = f"{url_base}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    payload = {
        "content": content,
        "message_type": "outgoing",
        "content_attributes": {
            "origin": "ai",
            "ai_agent": nome_ia,
            "ignore_webhook": True
        }
    }
    headers = {"api_access_token": token}

    try:
        resp = await http_client.post(url_m, json=payload, headers=headers)
        resp.raise_for_status()
        logger.info(f"📤 Mensagem enviada para conversa {conversation_id}")
        return resp
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem para Chatwoot: {e}")
        return None


# --- BACKGROUND JOBS & FOLLOW-UP ---

async def agendar_followups(conversation_id: int, account_id: int, slug: str, empresa_id: int):
    if not db_pool:
        return
    try:
        await db_pool.execute("""
            UPDATE followups SET status = 'cancelado'
            WHERE conversa_id = (SELECT id FROM conversas WHERE conversation_id = $1)
              AND status = 'pendente'
        """, conversation_id)

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
    while True:
        await asyncio.sleep(30)
        if not db_pool:
            continue
        try:
            agora = datetime.now(ZoneInfo("America/Sao_Paulo")).replace(tzinfo=None)

            pendentes = await db_pool.fetch("""
                SELECT f.*, c.conversation_id, c.account_id, u.slug, c.empresa_id
                FROM followups f
                JOIN conversas c ON c.id = f.conversa_id
                JOIN unidades u ON u.id = f.unidade_id
                WHERE f.status = 'pendente' AND f.agendado_para <= $1
                ORDER BY f.agendado_para
                LIMIT 20
                FOR UPDATE SKIP LOCKED
            """, agora)

            for f in pendentes:
                if (
                    await redis_client.get(f"atend_manual:{f['conversation_id']}") == "1"
                    or await redis_client.get(f"pause_ia:{f['conversation_id']}") == "1"
                ):
                    await db_pool.execute("UPDATE followups SET status = 'cancelado' WHERE id = $1", f['id'])
                    continue

                respondeu = await db_pool.fetchval("""
                    SELECT 1 FROM mensagens
                    WHERE conversa_id = $1 AND role = 'user' AND created_at > NOW() - interval '5 minutes'
                """, f['conversa_id'])
                if respondeu:
                    await db_pool.execute("UPDATE followups SET status = 'cancelado' WHERE id = $1", f['id'])
                    continue

                integracao = await carregar_integracao(f['empresa_id'], 'chatwoot')
                if not integracao:
                    await db_pool.execute(
                        "UPDATE followups SET status = 'erro', erro_log = 'Sem integração' WHERE id = $1", f['id']
                    )
                    continue

                await enviar_mensagem_chatwoot(
                    f['account_id'], f['conversation_id'], f['mensagem'], "Assistente Virtual", integracao
                )
                await db_pool.execute(
                    "UPDATE followups SET status = 'enviado', enviado_em = NOW() WHERE id = $1", f['id']
                )

        except Exception as e:
            logger.error(f"Erro no worker de follow-up: {e}")


async def monitorar_escolha_unidade(account_id: int, conversation_id: int, empresa_id: int):
    await asyncio.sleep(120)
    if not await redis_client.exists(f"esperando_unidade:{conversation_id}"):
        return
    if await redis_client.exists(f"unidade_escolhida:{conversation_id}"):
        return

    integracao = await carregar_integracao(empresa_id, 'chatwoot')
    if not integracao:
        return

    await enviar_mensagem_chatwoot(
        account_id, conversation_id,
        "Só pra eu não perder seu contato, qual unidade fica melhor para você? 🙂",
        "Assistente Virtual", integracao
    )

    await asyncio.sleep(480)
    if not await redis_client.exists(f"esperando_unidade:{conversation_id}"):
        return
    if await redis_client.exists(f"unidade_escolhida:{conversation_id}"):
        return

    await redis_client.delete(f"esperando_unidade:{conversation_id}")
    url_c = f"{integracao['url']}/api/v1/accounts/{account_id}/conversations/{conversation_id}"
    await http_client.put(
        url_c, json={"status": "resolved"},
        headers={"api_access_token": integracao['token']}
    )


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
        return data
    except Exception as e:
        logger.error(f"Erro ao listar unidades: {e}")
        return []


async def buscar_unidade_na_pergunta(texto: str, empresa_id: int) -> Optional[str]:
    """
    Tenta identificar uma unidade mencionada na pergunta do cliente.

    IMPORTANTE: só retorna resultado se houver correspondência forte e clara.
    Threshold do fuzzy aumentado para 85 para evitar falsos positivos.
    """
    if not db_pool or not texto:
        return None

    # Textos muito curtos (saudações, etc.) não devem acionar detecção de unidade
    palavras = texto.strip().split()
    if len(palavras) < 2:
        return None

    # 1. Tenta função SQL customizada (mais precisa)
    try:
        query = "SELECT unidade_slug FROM buscar_unidades_por_texto($1, $2) LIMIT 1"
        row = await db_pool.fetchrow(query, empresa_id, texto)
        if row:
            return row['unidade_slug']
    except Exception as e:
        logger.error(f"Erro na busca SQL de unidade: {e}")

    # 2. Fallback: busca por palavras-chave e nome
    unidades = await listar_unidades_ativas(empresa_id)
    texto_norm = normalizar(texto)

    for u in unidades:
        nome_norm = normalizar(u.get('nome', ''))
        cidade_norm = normalizar(u.get('cidade', ''))
        bairro_norm = normalizar(u.get('bairro', ''))
        palavras_chave = [normalizar(p) for p in (u.get('palavras_chave') or [])]

        # Correspondência exata de nome ou cidade no texto
        if nome_norm and nome_norm in texto_norm:
            return u['slug']
        if cidade_norm and len(cidade_norm) > 3 and cidade_norm in texto_norm:
            return u['slug']
        if bairro_norm and len(bairro_norm) > 3 and bairro_norm in texto_norm:
            return u['slug']
        if any(p and len(p) > 3 and p in texto_norm for p in palavras_chave):
            return u['slug']

    # 3. Fuzzy matching conservador (threshold 85 para evitar matches aleatórios)
    melhor_slug = None
    maior_score = 0
    for u in unidades:
        nome_norm = normalizar(u.get('nome', ''))
        if not nome_norm:
            continue
        score = fuzz.partial_ratio(nome_norm, texto_norm)
        if score > maior_score:
            maior_score = score
            melhor_slug = u['slug']

    if maior_score >= 85:
        return melhor_slug

    return None


async def carregar_unidade(slug: str, empresa_id: int) -> Dict[str, Any]:
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


async def carregar_faq_unidade(slug: str, empresa_id: int) -> str:
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


async def carregar_personalidade(empresa_id: int) -> Dict[str, Any]:
    if not db_pool:
        return {}

    cache_key = f"cfg:pers:empresa:{empresa_id}"
    cache = await redis_client.get(cache_key)
    if cache:
        dados_cache = json.loads(cache)
        if dados_cache.get('ativo') is True:
            return dados_cache
        else:
            await redis_client.delete(cache_key)

    try:
        query = """
            SELECT p.*
            FROM personalidade_ia p
            WHERE p.empresa_id = $1 AND p.ativo = true
            LIMIT 1
        """
        row = await db_pool.fetchrow(query, empresa_id)
        if row:
            dados = dict(row)
            for key, value in dados.items():
                if isinstance(value, Decimal):
                    dados[key] = float(value)
            await redis_client.setex(cache_key, 300, json.dumps(dados, default=str))
            return dados
        else:
            await redis_client.setex(cache_key, 60, json.dumps({}))
            return {}
    except Exception as e:
        logger.error(f"Erro ao carregar personalidade da empresa {empresa_id}: {e}")
        return {}


async def carregar_configuracao_global(empresa_id: int) -> Dict[str, Any]:
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
            config_data = row['config']
            if config_data is None:
                config = {}
            elif isinstance(config_data, str):
                try:
                    config = json.loads(config_data)
                except json.JSONDecodeError:
                    config = {}
            else:
                config = config_data
            config['nome_empresa'] = row['nome']
            config['plano'] = row['plano']
            await redis_client.setex(cache_key, 3600, json.dumps(config, default=str))
            return config
        return {}
    except Exception as e:
        logger.error(f"Erro ao carregar config global: {e}")
        return {}


# --- AUXILIARES BANCO DE DADOS ---

def log_db_error(retry_state):
    logger.error(f"Erro BD após {retry_state.attempt_number} tentativas: {retry_state.outcome.exception()}")
    return None


@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_iniciar_conversa(
    conversation_id: int, slug: str, account_id: int,
    contato_id: int = None, contato_nome: str = None, empresa_id: int = None
):
    if not db_pool:
        return
    try:
        unidade = await db_pool.fetchrow(
            "SELECT id FROM unidades WHERE slug = $1 AND empresa_id = $2", slug, empresa_id
        )
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
    except Exception as e:
        logger.error(f"❌ Erro ao iniciar conversa {conversation_id}: {e}")


@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_salvar_mensagem_local(
    conversation_id: int, role: str, content: str,
    tipo: str = 'texto', url_midia: str = None
):
    if not db_pool:
        return
    try:
        conversa = await db_pool.fetchrow(
            "SELECT id FROM conversas WHERE conversation_id = $1", conversation_id
        )
        if not conversa:
            logger.error(f"Conversa {conversation_id} não encontrada para salvar mensagem.")
            return
        await db_pool.execute("""
            INSERT INTO mensagens (conversa_id, role, tipo, conteudo, url_midia, created_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
        """, conversa['id'], role, tipo, content, url_midia)
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
            SET total_mensagens_cliente = total_mensagens_cliente + 1,
                ultima_mensagem = NOW(), updated_at = NOW()
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
            SET total_mensagens_ia = total_mensagens_ia + 1,
                ultima_mensagem = NOW(), updated_at = NOW()
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
async def bd_registrar_evento_funil(
    conversation_id: int, tipo_evento: str,
    descricao: str, score_incremento: int = 5
):
    if not db_pool:
        return
    try:
        conversa = await db_pool.fetchrow(
            "SELECT id FROM conversas WHERE conversation_id = $1", conversation_id
        )
        if not conversa:
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
            await db_pool.execute(
                "UPDATE conversas SET lead_qualificado = TRUE WHERE id = $1", conversa_id
            )
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
    while True:
        await asyncio.sleep(3600)
        if not db_pool:
            continue
        try:
            hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
            empresas = await db_pool.fetch("SELECT id FROM empresas")

            for emp in empresas:
                empresa_id = emp['id']
                unidades = await db_pool.fetch("SELECT id FROM unidades WHERE empresa_id = $1", empresa_id)

                for unid in unidades:
                    unidade_id = unid['id']

                    total_conversas = await db_pool.fetchval("""
                        SELECT COUNT(*) FROM conversas
                        WHERE empresa_id = $1 AND unidade_id = $2
                          AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
                    """, empresa_id, unidade_id, hoje)

                    total_mensagens = await db_pool.fetchval("""
                        SELECT COUNT(*) FROM mensagens m
                        JOIN conversas c ON c.id = m.conversa_id
                        WHERE c.empresa_id = $1 AND c.unidade_id = $2
                          AND DATE(m.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
                          AND m.role = 'user'
                    """, empresa_id, unidade_id, hoje)

                    leads = await db_pool.fetchval("""
                        SELECT COUNT(*) FROM conversas
                        WHERE empresa_id = $1 AND unidade_id = $2
                          AND lead_qualificado = true
                          AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
                    """, empresa_id, unidade_id, hoje)

                    tempo_medio = await db_pool.fetchval("""
                        SELECT COALESCE(
                            AVG(EXTRACT(EPOCH FROM (primeira_resposta_em - primeira_mensagem))),
                            0
                        )
                        FROM conversas
                        WHERE empresa_id = $1 AND unidade_id = $2
                          AND primeira_resposta_em IS NOT NULL
                          AND primeira_mensagem IS NOT NULL
                          AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
                    """, empresa_id, unidade_id, hoje)

                    total_telefone = await db_pool.fetchval("""
                        SELECT COUNT(*) FROM eventos_funil ef
                        JOIN conversas c ON c.id = ef.conversa_id
                        WHERE c.empresa_id = $1 AND c.unidade_id = $2
                          AND ef.tipo_evento = 'solicitacao_telefone'
                          AND DATE(ef.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
                    """, empresa_id, unidade_id, hoje)

                    total_links = await db_pool.fetchval("""
                        SELECT COUNT(*) FROM eventos_funil ef
                        JOIN conversas c ON c.id = ef.conversa_id
                        WHERE c.empresa_id = $1 AND c.unidade_id = $2
                          AND ef.tipo_evento = 'link_matricula_enviado'
                          AND DATE(ef.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
                    """, empresa_id, unidade_id, hoje)

                    await db_pool.execute("""
                        INSERT INTO metricas_diarias (
                            empresa_id, unidade_id, data,
                            total_conversas, total_mensagens, leads_qualificados,
                            tempo_medio_resposta, total_solicitacoes_telefone,
                            total_links_enviados, satisfacao_media
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 0.0)
                        ON CONFLICT (empresa_id, unidade_id, data) DO UPDATE SET
                            total_conversas = EXCLUDED.total_conversas,
                            total_mensagens = EXCLUDED.total_mensagens,
                            leads_qualificados = EXCLUDED.leads_qualificados,
                            tempo_medio_resposta = EXCLUDED.tempo_medio_resposta,
                            total_solicitacoes_telefone = EXCLUDED.total_solicitacoes_telefone,
                            total_links_enviados = EXCLUDED.total_links_enviados,
                            updated_at = NOW()
                    """, empresa_id, unidade_id, hoje, total_conversas, total_mensagens,
                           leads, tempo_medio, total_telefone, total_links)

            logger.info("✅ Métricas diárias atualizadas")
        except Exception as e:
            logger.error(f"❌ Erro no worker de métricas diárias: {e}", exc_info=True)


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
            resp = await http_client.get(url, follow_redirects=True)
            audio_file = io.BytesIO(resp.content)
            audio_file.name = "audio.ogg"
            transcription = await cliente_whisper.audio.transcriptions.create(
                model="whisper-1", file=audio_file
            )
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
    empresa_id: int,
    integracao_chatwoot: dict
):
    chave_lock = f"lock:{conversation_id}"
    watchdog = asyncio.create_task(renovar_lock(chave_lock, lock_val))

    try:
        # ⏱️ Aguarda 6s para acumular mensagens enviadas em sequência rápida
        await asyncio.sleep(6)

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

        mensagens_lista = []
        for i, txt in enumerate(textos, 1):
            mensagens_lista.append(f"{i}. {txt}")
        for i, transc in enumerate(transcricoes, len(textos) + 1):
            mensagens_lista.append(f"{i}. [Áudio] {transc}")

        mensagens_formatadas = "\n".join(mensagens_lista) if mensagens_lista else ""

        # Detecta se cliente mencionou outra unidade
        primeira_mensagem = textos[0] if textos else ""
        slug_detectado = await buscar_unidade_na_pergunta(primeira_mensagem, empresa_id) if primeira_mensagem else None
        mudou_unidade = False

        if slug_detectado and slug_detectado != slug:
            logger.info(f"🔄 IA mudou contexto de {slug} para unidade: {slug_detectado}")
            slug = slug_detectado
            mudou_unidade = True
            await redis_client.setex(f"unidade_escolhida:{conversation_id}", 86400, slug)
            await bd_registrar_evento_funil(
                conversation_id, "mudanca_unidade", f"Contexto alterado para {slug}", score_incremento=1
            )

        # Salvar mensagens do usuário
        for txt in textos:
            await bd_salvar_mensagem_local(conversation_id, "user", txt)
        for transc in transcricoes:
            await bd_salvar_mensagem_local(conversation_id, "user", f"[Áudio] {transc}")

        unidade = await carregar_unidade(slug, empresa_id) or {}
        pers = await carregar_personalidade(empresa_id) or {}
        nome_ia = pers.get('nome_ia') or 'Assistente Virtual'

        estado_raw = await redis_client.get(f"estado:{conversation_id}")
        estado_atual = descomprimir_texto(estado_raw) or "neutro"

        texto_norm_fast = normalizar(primeira_mensagem)
        fast_reply = None

        # Campos da unidade
        end_banco = unidade.get('endereco_completo') or unidade.get('endereco')
        hor_banco = unidade.get('horarios')
        link_mat = unidade.get('link_matricula') or unidade.get('site') or 'nosso site oficial'
        tel_banco = unidade.get('telefone') or unidade.get('whatsapp')

        # Planos ativos
        planos_ativos = await buscar_planos_ativos(empresa_id, unidade.get('id'), force_sync=True)
        if planos_ativos:
            planos_str = formatar_planos_para_prompt(planos_ativos)
            links_dos_planos = "\n".join([
                f"- {p['nome']}: {p['link_venda']}"
                for p in planos_ativos if p.get('link_venda')
            ])
            link_plano = planos_ativos[0].get('link_venda') if planos_ativos else link_mat
        else:
            planos_str = "não informado"
            links_dos_planos = ""
            link_plano = link_mat

        # ==================== FAST-PATH ====================

        if not imagens_urls and len(textos) == 1:

            # Fast-path: saudação genérica — responde sem mencionar unidade específica
            if eh_saudacao(primeira_mensagem):
                _saudacao_base = pers.get('saudacao_personalizada') or f"Olá! Sou {nome_ia} 😊"
                # Remove menção ao nome da unidade da saudação personalizada
                _nome_unidade_atual = unidade.get('nome') or ''
                if _nome_unidade_atual and _nome_unidade_atual in _saudacao_base:
                    _saudacao_base = _saudacao_base.replace(_nome_unidade_atual, nome_ia)
                fast_reply = f"{_saudacao_base}\n\nComo posso te ajudar hoje? 😊"
                logger.info("⚡ Fast-path: saudação genérica (sem mencionar unidade)")

            # Fast-path: listar unidades
            if re.search(
                r"(quais (sao as )?unidades|quantas unidades|unidades (voc[êe]s )?tem|tem outras unidades"
                r"|lista de unidades|onde (voc[êe]s )?tem academia|queria saber as unidades"
                r"|gostaria de saber as unidades|me (diga|informe) as unidades|quais unidades existem)",
                texto_norm_fast, re.IGNORECASE
            ):
                todas_ativas = await listar_unidades_ativas(empresa_id)
                if todas_ativas:
                    total = len(todas_ativas)
                    lista_str = "\n".join([
                        f"• {u['nome']}" + (f" ({u['cidade']})" if u.get('cidade') else "")
                        for u in todas_ativas
                    ])
                    fast_reply = random.choice(RESPOSTAS_UNIDADES).format(
                        total=total, lista_str=lista_str
                    )
                    await bd_registrar_evento_funil(
                        conversation_id, "consulta_unidades",
                        "Cliente solicitou lista de unidades", score_incremento=1
                    )
                else:
                    fast_reply = "No momento não há unidades cadastradas. 😕"

            # Fast-path: endereço
            elif unidade and re.search(
                r"(endereco|enderco|local|localizacao|fica onde|onde fica|como chego|qual o local)",
                texto_norm_fast
            ):
                if end_banco and str(end_banco).strip().lower() not in ['não informado', 'none', '']:
                    fast_reply = random.choice(RESPOSTAS_ENDERECO).format(endereco=end_banco)

            # Fast-path: horários
            elif unidade and re.search(
                r"(horario|funcionamento|abre|fecha|que horas|ta aberto)", texto_norm_fast
            ):
                if hor_banco:
                    if isinstance(hor_banco, dict):
                        horario_str = "\n".join([f"• {dia}: {h}" for dia, h in hor_banco.items()])
                    else:
                        horario_str = str(hor_banco)
                    fast_reply = random.choice(RESPOSTAS_HORARIO).format(horario_str=horario_str)

            # Fast-path: planos — usa formatar_planos_bonito para visual bonito
            elif unidade and re.search(
                r"(preco|valor|quanto custa|mensalidade|planos|promocao)", texto_norm_fast
            ):
                if planos_ativos:
                    fast_reply = formatar_planos_bonito(planos_ativos)
                    fast_reply += "\n\nQuer saber mais sobre algum plano específico? 😊"
                    await bd_registrar_evento_funil(
                        conversation_id, "link_matricula_enviado",
                        "Link enviado via fast-path", score_incremento=2
                    )

            # Fast-path: contato
            elif unidade and re.search(
                r"(telefone|contato|whatsapp|numero|ligar)", texto_norm_fast
            ):
                if tel_banco and str(tel_banco).strip().lower() not in ['não informado', 'none', '']:
                    fast_reply = random.choice(RESPOSTAS_CONTATO).format(tel_banco=tel_banco)
                    await bd_registrar_evento_funil(
                        conversation_id, "solicitacao_telefone",
                        "Cliente solicitou telefone", score_incremento=3
                    )

        # ===================================================

        # Cache de intenção
        intencao = detectar_intencao(primeira_mensagem) if primeira_mensagem else None
        if intencao:
            chave_cache_ia = f"cache:intent:{slug}:{intencao}"
        else:
            hash_pergunta = hashlib.md5(texto_norm_fast.encode('utf-8')).hexdigest()
            chave_cache_ia = f"cache:ia:{slug}:{hash_pergunta}"

        resposta_cacheada = await redis_client.get(chave_cache_ia)

        if fast_reply:
            logger.info("⚡ Fast-Path Ativado! Respondendo sem IA.")
            resposta_texto = fast_reply
            novo_estado = estado_atual

        elif resposta_cacheada and not imagens_urls and not mudou_unidade:
            logger.info("🧠 Cache Hit! Respondendo direto do Redis.")
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

            if hor_banco:
                if isinstance(hor_banco, dict):
                    horarios_str = "\n".join([f"- {dia}: {h}" for dia, h in hor_banco.items()])
                else:
                    horarios_str = str(hor_banco)
            else:
                horarios_str = "não informado"

            # Detalhes de planos para o prompt (texto simples, sem markdown)
            planos_detalhados = formatar_planos_para_prompt(planos_ativos) if planos_ativos else "não informado"

            dados_unidade = f"""
DADOS COMPLETOS DA UNIDADE
Nome: {unidade.get('nome') or 'não informado'}
Empresa: {unidade.get('nome_empresa') or 'não informado'}
Endereço: {end_banco or 'não informado'}
Cidade/Estado: {unidade.get('cidade') or 'não informado'} / {unidade.get('estado') or 'não informado'}
Telefone: {tel_banco or 'não informado'}
Horários:
{horarios_str}
Planos (com links de matricula):
{planos_detalhados}
Site: {unidade.get('site') or 'não informado'}
Instagram: {unidade.get('instagram') or 'não informado'}
Modalidades: {', '.join(unidade.get('modalidades', [])) if unidade.get('modalidades') else 'não informado'}
Infraestrutura: {json.dumps(unidade.get('infraestrutura', {}), ensure_ascii=False) if unidade.get('infraestrutura') else 'não informado'}
Pagamentos: {', '.join(unidade.get('formas_pagamento', [])) if unidade.get('formas_pagamento') else 'não informado'}
Convênios: {', '.join(unidade.get('convenios', [])) if unidade.get('convenios') else 'não informado'}
"""

            tom_voz = pers.get('tom_voz') or 'Profissional, claro e prestativo'
            estilo = pers.get('estilo_comunicacao') or ''
            saudacao = pers.get('saudacao_personalizada') or f"Olá! Sou {nome_ia}, como posso ajudar?"
            instrucoes_base = pers.get('instrucoes_base') or "Atenda o cliente de forma educada."
            regras_atendimento = pers.get('regras_atendimento') or "Seja breve e objetivo."
            aviso_mudanca = (
                f"\n[AVISO]: O cliente perguntou sobre a unidade {nome_unidade}. "
                "Use os dados abaixo para responder."
            ) if mudou_unidade else ""

            prompt_sistema = f"""
Seu nome é {nome_ia}. Você é atendente da academia {nome_empresa}, unidade {nome_unidade}.

PERSONALIDADE
{pers.get('personalidade', '')}

ESTILO DE COMUNICAÇÃO
Tom de voz: {tom_voz}
Estilo: {estilo}

SAUDAÇÃO PADRÃO
{saudacao}

INSTRUÇÕES
{instrucoes_base}

REGRAS DE ATENDIMENTO
{regras_atendimento}

INFORMAÇÕES DA UNIDADE
{dados_unidade}

FAQ
{faq}

HISTÓRICO DA CONVERSA
{historico}

REGRA CRÍTICA — ANTI-ALUCINAÇÃO (OBRIGATÓRIO, NUNCA IGNORE):
- Use EXCLUSIVAMENTE as informações presentes em DADOS COMPLETOS DA UNIDADE acima.
- Se um campo estiver como "não informado" ou ausente, diga que não tem essa informação no momento.
- NUNCA invente, suponha ou complete endereços, telefones, horários ou qualquer dado.
- Se o cliente perguntar algo que não está nos dados, diga: "Não tenho essa informação agora, mas posso verificar para você!" ou similar.
- Em saudações (boa tarde, oi, etc.), NÃO mencione o nome da unidade — apenas se apresente e pergunte como pode ajudar.

FORMATAÇÃO DA RESPOSTA (OBRIGATÓRIO):
- Fale como uma pessoa real, nunca mencione ser IA ou assistente virtual
- Use emojis com moderação (😊 💪 ✅)
- Separe parágrafos com linha em branco
- Para listas use • no início de cada item
- NÃO use markdown: sem **, sem ##, sem [texto](url)
- Links devem aparecer como URL plana (ex: https://exemplo.com)
- Respostas curtas e diretas, sem enrolação
- Não se apresente novamente se já houver histórico
{aviso_mudanca}

DADOS DO ATENDIMENTO:
Cliente: {nome_cliente}
Estado anterior: {estado_atual}

MENSAGENS DO CLIENTE:
{mensagens_formatadas}

Responda APENAS em JSON válido com os campos:
- "resposta": sua mensagem ao cliente (texto formatado conforme regras acima)
- "estado": estado emocional atual do cliente (neutro, interessado, animado, hesitante, frustrado, conversao)
"""

            conteudo_usuario = []
            for img_url in imagens_urls:
                try:
                    resp = await http_client.get(
                        img_url,
                        headers={"api_access_token": integracao_chatwoot['token']},
                        follow_redirects=True
                    )
                    if resp.status_code == 200:
                        img_b64 = base64.b64encode(resp.content).decode("utf-8")
                        conteudo_usuario.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                        })
                except Exception as e:
                    logger.error(f"Erro ao baixar imagem: {e}")

            modelo_escolhido = pers.get("modelo_preferido") or (
                "google/gemini-2.5-flash" if imagens_urls else "google/gemini-2.5-flash-lite"
            )
            temperature = float(pers.get("temperatura") or 0.7)

            start_time = time.time()
            async with llm_semaphore:
                try:
                    response = await cliente_ia.chat.completions.create(
                        model=modelo_escolhido,
                        messages=[
                            {"role": "system", "content": prompt_sistema},
                            {"role": "user", "content": conteudo_usuario if conteudo_usuario else " "}
                        ],
                        temperature=temperature,
                        timeout=30
                    )
                    resposta_bruta = response.choices[0].message.content
                except Exception as e:
                    logger.warning(f"Fallback para Gemini Flash devido a erro: {e}")
                    modelo_fallback = "google/gemini-2.5-flash" if imagens_urls else "google/gemini-2.5-flash-lite"
                    response = await cliente_ia.chat.completions.create(
                        model=modelo_fallback,
                        messages=[
                            {"role": "system", "content": prompt_sistema},
                            {"role": "user", "content": conteudo_usuario if conteudo_usuario else " "}
                        ],
                        temperature=temperature
                    )
                    resposta_bruta = response.choices[0].message.content

            logger.info(f"⏱️ LLM Latency: {time.time() - start_time:.2f}s")

            resposta_bruta = corrigir_json(resposta_bruta)

            try:
                dados_ia = json.loads(resposta_bruta)
                resposta_texto = dados_ia.get("resposta", "Desculpe, não consegui processar.")
                novo_estado = dados_ia.get("estado", estado_atual).strip().lower()

                # Garante que não há markdown na resposta da IA
                resposta_texto = limpar_markdown(resposta_texto)

                if not imagens_urls:
                    await redis_client.setex(
                        chave_cache_ia, 600,
                        json.dumps({"resposta": resposta_texto, "estado": novo_estado})
                    )

                if link_plano in resposta_texto or "matricular" in resposta_texto.lower():
                    await bd_registrar_evento_funil(
                        conversation_id, "link_matricula_enviado", "Link enviado via IA", score_incremento=2
                    )
                if tel_banco and tel_banco in resposta_texto:
                    await bd_registrar_evento_funil(
                        conversation_id, "solicitacao_telefone", "IA forneceu telefone", score_incremento=3
                    )

            except json.JSONDecodeError:
                logger.error(f"❌ JSON inválido da IA. Bruto: {resposta_bruta[:200]}...")
                resposta_texto = "Desculpe, tive um problema ao processar sua solicitação. Pode reformular?"
                novo_estado = estado_atual

        # --- Salvar estado ---
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.setex(f"estado:{conversation_id}", 86400, comprimir_texto(novo_estado))
            pipe.lpush(
                f"hist_estado:{conversation_id}",
                f"{datetime.now(ZoneInfo('America/Sao_Paulo')).isoformat()}|{novo_estado}"
            )
            pipe.ltrim(f"hist_estado:{conversation_id}", 0, 10)
            pipe.expire(f"hist_estado:{conversation_id}", 86400)
            await pipe.execute()

        if any(k in novo_estado for k in ("interessado", "conversao", "matricula", "animado")):
            await bd_registrar_evento_funil(
                conversation_id, "interesse_detectado", f"Estado: {novo_estado}"
            )

        await bd_salvar_mensagem_local(conversation_id, "assistant", resposta_texto)

        is_manual = (await redis_client.get(f"atend_manual:{conversation_id}")) == "1"

        if is_manual or await redis_client.exists(f"pause_ia:{conversation_id}"):
            pass  # IA pausada, não envia
        elif fast_reply:
            # Fast-path: envia a resposta INTEIRA como UMA mensagem (planos, endereço, etc.)
            delay = min(len(resposta_texto) * 0.02, 3) + random.uniform(0.3, 0.8)
            await asyncio.sleep(delay)
            await enviar_mensagem_chatwoot(
                account_id, conversation_id, resposta_texto, nome_ia, integracao_chatwoot
            )
            await bd_atualizar_msg_ia(conversation_id)
            await bd_registrar_primeira_resposta(conversation_id)
        else:
            # Resposta da IA: divide por parágrafo duplo para simular digitação humana
            paragrafos = [p.strip() for p in resposta_texto.split("\n\n") if p.strip()]
            if not paragrafos:
                paragrafos = [resposta_texto.strip()]

            for i, paragrafo in enumerate(paragrafos):
                if await redis_client.exists(f"pause_ia:{conversation_id}"):
                    break

                delay = min(len(paragrafo) * 0.035, 5) + random.uniform(0.3, 1.0)
                await asyncio.sleep(delay)

                await enviar_mensagem_chatwoot(
                    account_id, conversation_id, paragrafo, nome_ia, integracao_chatwoot
                )
                await bd_atualizar_msg_ia(conversation_id)

                if i == 0:
                    await bd_registrar_primeira_resposta(conversation_id)

        # 🔄 DRAIN LOOP — processa mensagens que chegaram DURANTE o processamento da IA
        # Isso resolve o problema de mensagens perdidas quando o cliente digita rápido
        _drain_tentativas = 0
        while _drain_tentativas < 2:
            await asyncio.sleep(2)
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
                await bd_salvar_mensagem_local(conversation_id, "user", txt)
            # Passa essas mensagens para outro ciclo de processamento reutilizando o mesmo lock
            for m_json in msgs_drain:
                await redis_client.rpush(f"buffet_drain:{conversation_id}", m_json)
            await redis_client.expire(f"buffet_drain:{conversation_id}", 120)
            # Coloca de volta no buffet para ser pego pelo próximo webhook (lock será liberado logo)
            for m_json in msgs_drain:
                await redis_client.rpush(chave_buffet, m_json)
            await redis_client.expire(chave_buffet, 60)
            _drain_tentativas += 1

    except Exception as e:
        logger.error(f"🔥 Erro Crítico: {e}", exc_info=True)
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
                        nome_cliente, novo_lock_val, empresa_id, integracao_chatwoot
                    ))
        except Exception as e_drain:
            logger.error(f"Erro no drain pós-processamento: {e_drain}")


# --- WEBHOOK ENDPOINT ---

async def validar_assinatura(request: Request, signature: str):
    if not CHATWOOT_WEBHOOK_SECRET:
        return
    body = await request.body()
    expected = hmac.new(CHATWOOT_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature or "", expected):
        raise HTTPException(status_code=401, detail="Assinatura inválida")


@app.post("/webhook")
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

    # Rate limiting por conversa
    rate_key = f"rate:{id_conv}"
    contador = await redis_client.incr(rate_key)
    if contador == 1:
        await redis_client.expire(rate_key, 10)
    if contador > 10:
        return {"status": "rate_limit"}

    # Busca empresa pelo account_id
    empresa_id = await buscar_empresa_por_account_id(account_id)
    if not empresa_id:
        logger.error(f"Account {account_id} sem empresa associada")
        return {"status": "erro_sem_empresa"}

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
        await redis_client.setex(f"atend_manual:{id_conv}", 86400, is_manual)

    if event == "conversation_updated":
        if conv_obj.get("status") == "resolved":
            await bd_finalizar_conversa(id_conv)
            await redis_client.delete(
                f"pause_ia:{id_conv}", f"estado:{id_conv}",
                f"unidade_escolhida:{id_conv}", f"esperando_unidade:{id_conv}"
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

    # Detecta mudança de contexto de unidade na mensagem
    if message_type == "incoming" and conteudo_texto:
        slug_detectado = await buscar_unidade_na_pergunta(conteudo_texto, empresa_id)
        if slug_detectado and slug_detectado != slug:
            logger.info(f"🔄 Webhook mudou contexto para {slug_detectado}")
            slug = slug_detectado
            await redis_client.setex(f"unidade_escolhida:{id_conv}", 86400, slug)

    # Sem unidade ainda — tenta definir
    if not slug and message_type == "incoming":
        unidades_ativas = await listar_unidades_ativas(empresa_id)
        if not unidades_ativas:
            return {"status": "sem_unidades_ativas"}

        elif len(unidades_ativas) == 1:
            # Empresa com apenas 1 unidade — seleciona automaticamente
            slug = unidades_ativas[0]["slug"]
            await redis_client.setex(f"unidade_escolhida:{id_conv}", 86400, slug)

        else:
            # Múltiplas unidades — tenta identificar pelo texto ou número digitado
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
                    contato.get("id"), limpar_nome(contato.get("name")), empresa_id
                )
                await bd_registrar_evento_funil(
                    id_conv, "unidade_escolhida", f"Cliente escolheu {slug}", 3
                )
                lock_key = f"agendar_lock:{id_conv}"
                if await redis_client.set(lock_key, "1", nx=True, ex=5):
                    try:
                        existe = await db_pool.fetchval(
                            "SELECT 1 FROM followups f JOIN conversas c ON c.id = f.conversa_id "
                            "WHERE c.conversation_id = $1 AND f.status = 'pendente' LIMIT 1", id_conv
                        )
                        if not existe:
                            await agendar_followups(id_conv, account_id, slug, empresa_id)
                    finally:
                        await redis_client.delete(lock_key)
            else:
                # Pede ao cliente que escolha a unidade
                cfg = await carregar_configuracao_global(empresa_id)
                boas_vindas = cfg.get("mensagem_boas_vindas") or "Olá! 😊 Seja bem-vindo."
                nomes = "\n".join([
                    f"• {u['nome']}" + (f" ({u['cidade']})" if u.get('cidade') else "")
                    for u in unidades_ativas
                ])
                msg = (
                    f"{boas_vindas}\n\n"
                    "Só pra eu te direcionar melhor 🙂\n"
                    "Qual unidade você quer falar?\n\n"
                    f"{nomes}\n\n"
                    "Se preferir, pode me dizer o nome ou a cidade também."
                )
                await enviar_mensagem_chatwoot(account_id, id_conv, msg, "Assistente Virtual", integracao)
                await redis_client.setex(f"esperando_unidade:{id_conv}", 86400, "1")
                background_tasks.add_task(monitorar_escolha_unidade, account_id, id_conv, empresa_id)
                return {"status": "aguardando_escolha_unidade"}

    if not slug:
        return {"status": "erro_sem_unidade"}

    # Pausa IA se for mensagem de atendente humano
    if message_type == "outgoing" and sender_type == "user":
        if is_ai_message:
            return {"status": "ignorado"}
        await redis_client.setex(f"pause_ia:{id_conv}", 43200, "1")
        if db_pool:
            await db_pool.execute(
                "UPDATE followups SET status = 'cancelado' "
                "WHERE conversa_id = (SELECT id FROM conversas WHERE conversation_id = $1) "
                "AND status = 'pendente'", id_conv
            )
        return {"status": "ia_pausada"}

    if message_type != "incoming":
        return {"status": "ignorado"}

    contato = payload.get("sender", {})
    await bd_iniciar_conversa(
        id_conv, slug, account_id,
        contato.get("id"), limpar_nome(contato.get("name")), empresa_id
    )

    lock_key = f"agendar_lock:{id_conv}"
    if await redis_client.set(lock_key, "1", nx=True, ex=5):
        try:
            existe = await db_pool.fetchval(
                "SELECT 1 FROM followups f JOIN conversas c ON c.id = f.conversa_id "
                "WHERE c.conversation_id = $1 AND f.status = 'pendente' LIMIT 1", id_conv
            )
            if not existe:
                await agendar_followups(id_conv, account_id, slug, empresa_id)
        finally:
            await redis_client.delete(lock_key)

    await bd_atualizar_msg_cliente(id_conv)

    if await redis_client.exists(f"pause_ia:{id_conv}"):
        return {"status": "ignorado"}

    anexos = payload.get("attachments") or payload.get("message", {}).get("attachments", [])
    arquivos = []
    for a in anexos:
        ft = str(a.get("file_type", "")).lower()
        tipo = "image" if ft.startswith("image") else "audio" if ft.startswith("audio") else "documento"
        arquivos.append({"url": a.get("data_url"), "type": tipo})

    await redis_client.rpush(
        f"buffet:{id_conv}",
        json.dumps({"text": conteudo_texto, "files": arquivos})
    )
    await redis_client.expire(f"buffet:{id_conv}", 60)

    lock_val = str(uuid.uuid4())
    if await redis_client.set(f"lock:{id_conv}", lock_val, nx=True, ex=180):
        background_tasks.add_task(
            processar_ia_e_responder,
            account_id, id_conv, contato.get("id"), slug,
            limpar_nome(contato.get("name")), lock_val, empresa_id, integracao
        )
        return {"status": "processando"}

    return {"status": "acumulando_no_buffet"}


@app.get("/desbloquear/{conversation_id}")
async def desbloquear_ia(conversation_id: int):
    if await redis_client.delete(f"pause_ia:{conversation_id}"):
        return {"status": "sucesso", "mensagem": f"✅ IA reativada para {conversation_id}!"}
    return {"status": "aviso", "mensagem": f"A conversa {conversation_id} não estava pausada."}


@app.get("/")
async def health():
    return {
        "status": "🤖 Motor SaaS IA — Planos bonitos, links planos, unidades corretas, formatação perfeita!"
    }
