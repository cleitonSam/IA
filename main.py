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
from fastapi import FastAPI, Request, BackgroundTasks, Header, HTTPException, Response
from dotenv import load_dotenv
from openai import AsyncOpenAI
import redis.asyncio as redis
import asyncpg
from tenacity import retry, wait_exponential, stop_after_attempt
from rapidfuzz import fuzz

# --- CONFIGURAÇÃO DE LOG (loguru se disponível, senão logging padrão) ---
try:
    from loguru import logger as _loguru_logger
    import sys as _sys
    _loguru_logger.remove()
    _loguru_logger.add(
        _sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
        level="INFO",
        colorize=True
    )
    logger = _loguru_logger
    # Suprime logs de bibliotecas externas via logging padrão
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
except ImportError:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    logger = logging.getLogger("motor-saas-ia")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

# --- PROMETHEUS METRICS (opcional — instale prometheus-client para ativar) ---
try:
    from prometheus_client import (
        Counter, Histogram, Gauge,
        generate_latest, CONTENT_TYPE_LATEST
    )
    _PROMETHEUS_OK = True

    METRIC_WEBHOOKS_TOTAL  = Counter("saas_webhooks_total",  "Total de webhooks recebidos", ["event"])
    METRIC_IA_LATENCY      = Histogram("saas_ia_latency_seconds", "Latência do LLM em segundos",
                                        buckets=[0.5, 1, 2, 5, 10, 30])
    METRIC_FAST_PATH_TOTAL = Counter("saas_fast_path_total", "Respostas via fast-path", ["tipo"])
    METRIC_ERROS_TOTAL     = Counter("saas_erros_total",     "Erros críticos por tipo", ["tipo"])
    METRIC_CONVERSAS_ATIVAS = Gauge("saas_conversas_ativas", "Conversas ativas no Redis")
    METRIC_PLANOS_ENVIADOS  = Counter("saas_planos_enviados_total", "Planos enviados ao cliente")
    METRIC_ALUNO_DETECTADO  = Counter("saas_tipo_cliente_total", "Tipo de cliente detectado", ["tipo"])
except ImportError:
    _PROMETHEUS_OK = False

load_dotenv()

CHATWOOT_URL = os.getenv("CHATWOOT_URL")
CHATWOOT_TOKEN = os.getenv("CHATWOOT_TOKEN")

app = FastAPI()

# ── Middleware de Rate Limit Global ──────────────────────────────────────────
# Bloqueia IPs e empresas que abusem do endpoint /webhook
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """
    Rate limiting em duas camadas:
      1. Por IP  — máx 60 req/minuto   (anti-spam / DDoS básico)
      2. Por empresa — máx 300 req/minuto (anti-loop de webhook)
    Apenas para o endpoint /webhook. Outros endpoints passam livre.
    """
    if request.url.path != "/webhook" or redis_client is None:
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"

    # 1. Rate limit por IP
    ip_key     = f"rl:ip:{client_ip}"
    ip_count   = await redis_client.incr(ip_key)
    if ip_count == 1:
        await redis_client.expire(ip_key, 60)
    if ip_count > 60:
        logger.warning(f"🚫 Rate limit por IP: {client_ip} ({ip_count} req/min)")
        if _PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="rate_limit_ip").inc()
        from fastapi.responses import JSONResponse
        return JSONResponse({"status": "rate_limit_ip"}, status_code=429)

    # 2. Rate limit por empresa (lido do payload — extrai account_id sem ler 2x o body)
    try:
        body = await request.body()
        _payload = json.loads(body)
        _account_id = _payload.get("account", {}).get("id")
        if _account_id:
            emp_key   = f"rl:account:{_account_id}"
            emp_count = await redis_client.incr(emp_key)
            if emp_count == 1:
                await redis_client.expire(emp_key, 60)
            if emp_count > 300:
                logger.warning(f"🚫 Rate limit por conta: account_id={_account_id} ({emp_count} req/min)")
                if _PROMETHEUS_OK:
                    METRIC_ERROS_TOTAL.labels(tipo="rate_limit_account").inc()
                from fastapi.responses import JSONResponse
                return JSONResponse({"status": "rate_limit_account"}, status_code=429)
        # Recria o request com o body já lido (FastAPI consome o stream uma vez)
        from starlette.datastructures import Headers
        from starlette.requests import Request as StarletteRequest
        scope = request.scope
        scope["_body"] = body
    except Exception:
        pass

    return await call_next(request)

# ============================================================
# ⚡ CIRCUIT BREAKER — protege contra queda do OpenRouter/LLM
# Estado salvo no Redis: CLOSED (normal) | OPEN (bloqueado) | HALF_OPEN (testando)
# ============================================================
class CircuitBreaker:
    """
    Circuit Breaker para chamadas ao LLM.
    - CLOSED: operação normal
    - OPEN: muitas falhas → bloqueia por `recovery_timeout` segundos
    - HALF_OPEN: após recovery, testa 1 chamada para ver se voltou

    Todos os estados persistem no Redis — funciona com múltiplos workers.
    """
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 2,
    ):
        self.name             = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout  = recovery_timeout
        self.success_threshold = success_threshold

    def _keys(self):
        return (
            f"cb:{self.name}:state",
            f"cb:{self.name}:failures",
            f"cb:{self.name}:successes",
            f"cb:{self.name}:opened_at",
        )

    async def get_state(self) -> str:
        k_state, _, _, k_opened = self._keys()
        state = await redis_client.get(k_state) or "CLOSED"
        if state == "OPEN":
            opened_at = await redis_client.get(k_opened)
            if opened_at and (time.time() - float(opened_at)) > self.recovery_timeout:
                await redis_client.set(k_state, "HALF_OPEN")
                return "HALF_OPEN"
        return state

    async def record_success(self):
        k_state, k_fail, k_succ, _ = self._keys()
        state = await self.get_state()
        if state == "HALF_OPEN":
            succs = await redis_client.incr(k_succ)
            if succs >= self.success_threshold:
                await redis_client.mset({k_state: "CLOSED", k_fail: 0, k_succ: 0})
                logger.info(f"✅ CircuitBreaker [{self.name}] → CLOSED (recuperado)")
        else:
            await redis_client.set(k_fail, 0)

    async def record_failure(self):
        k_state, k_fail, k_succ, k_opened = self._keys()
        state = await self.get_state()
        if state == "HALF_OPEN":
            # Voltou a falhar em teste — reabre
            await redis_client.mset({
                k_state: "OPEN",
                k_succ:  0,
                k_opened: str(time.time()),
            })
            logger.warning(f"⚡ CircuitBreaker [{self.name}] → OPEN novamente (falha em HALF_OPEN)")
        else:
            fails = await redis_client.incr(k_fail)
            if not await redis_client.ttl(k_fail):
                await redis_client.expire(k_fail, 120)
            if fails >= self.failure_threshold:
                await redis_client.mset({
                    k_state:  "OPEN",
                    k_opened: str(time.time()),
                    k_succ:   0,
                })
                logger.error(
                    f"🔴 CircuitBreaker [{self.name}] → OPEN "
                    f"({fails} falhas em 120s)"
                )
                if _PROMETHEUS_OK:
                    METRIC_ERROS_TOTAL.labels(tipo="circuit_breaker_open").inc()

    async def is_allowed(self) -> bool:
        state = await self.get_state()
        if state == "CLOSED":
            return True
        if state == "HALF_OPEN":
            return True   # permite 1 chamada de teste
        # OPEN — verifica se recovery_timeout já passou
        return False

# Instância global
cb_llm = CircuitBreaker(name="openrouter", failure_threshold=5, recovery_timeout=60)

# --- CONFIGURAÇÕES E VARIÁVEIS DE AMBIENTE ---
CHATWOOT_WEBHOOK_SECRET = os.getenv("CHATWOOT_WEBHOOK_SECRET")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REDIS_URL = os.getenv("REDIS_URL")
DATABASE_URL = os.getenv("DATABASE_URL")

EMPRESA_ID_PADRAO = 1

# 👋 SAUDAÇÕES — usadas para detectar mensagens de abertura OU small talk sem intenção real
# Inclui respostas de follow-up ("tudo sim", "por aí?") para não disparar vendas acidentalmente
SAUDACOES = {
    # Abertura
    "oi", "ola", "olá", "hey", "boa", "salve", "eai", "e ai",
    "bom dia", "boa tarde", "boa noite", "tudo bem", "tudo bom",
    "como vai", "oi tudo", "ola tudo", "oii", "oiii", "opa",
    # Follow-up de small talk (resposta à saudação da IA)
    "tudo sim", "tudo certo", "tudo otimo", "tudo ótimo", "tudo ok",
    "por ai", "por aí", "e por ai", "e por aí", "e voce", "e você", "e vc",
    "bem obrigado", "bem sim", "tudo tranquilo", "tranquilo", "aqui tudo",
    "muito bem", "que bom", "que otimo", "que ótimo", "que bom mesmo",
    "obrigado", "obg", "valeu", "brigado", "grato",
    "otimo", "ótimo", "perfeito", "maravilha", "show",
    "ok ok", "beleza", "blz", "sim sim", "claro", "certo",
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


def saudacao_por_horario() -> str:
    """
    Retorna 'Bom dia', 'Boa tarde' ou 'Boa noite' baseado no horário de São Paulo.
    Faixas:  6h–11h59 → Bom dia | 12h–17h59 → Boa tarde | 18h–5h59 → Boa noite
    Madrugada (0h–5h) também recebe 'Boa noite'.
    """
    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    hora = agora.hour
    if 6 <= hora < 12:
        return "Bom dia"
    elif 12 <= hora < 18:
        return "Boa tarde"
    else:  # 18h–23h e 0h–5h (madrugada)
        return "Boa noite"


def horario_hoje_formatado(horarios: Any) -> Optional[str]:
    """
    Retorna o horário de funcionamento de HOJE (baseado no dia da semana em SP).
    Suporta dict com chaves como "segunda", "seg", "segunda-feira", etc.
    Retorna None se não encontrar.
    """
    if not horarios:
        return None

    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    dia_semana_idx = agora.weekday()  # 0=segunda, 6=domingo

    # Mapeamento de dia da semana para possíveis chaves no dict de horários
    DIAS_MAP = {
        0: ["segunda", "seg", "segunda-feira", "mon", "segunda feira"],
        1: ["terca", "ter", "terça", "terca-feira", "terça-feira", "tue", "terca feira"],
        2: ["quarta", "qua", "quarta-feira", "wed", "quarta feira"],
        3: ["quinta", "qui", "quinta-feira", "thu", "quinta feira"],
        4: ["sexta", "sex", "sexta-feira", "fri", "sexta feira"],
        5: ["sabado", "sab", "sábado", "sat"],
        6: ["domingo", "dom", "sun"],
    }

    # Também tenta "seg a sex" / "segunda a sexta" / "dias uteis" para dias 0-4
    AGRUPADOS = {
        "seg a sex": range(0, 5),
        "segunda a sexta": range(0, 5),
        "dias uteis": range(0, 5),
        "dias úteis": range(0, 5),
        "sab e dom": range(5, 7),
        "sabado e domingo": range(5, 7),
        "sábado e domingo": range(5, 7),
        "fim de semana": range(5, 7),
        "feriados": [],  # tratado separadamente
    }

    # Se vier como string JSON (ex: asyncpg retorna JSONB como texto), converte para dict
    if isinstance(horarios, str):
        try:
            horarios = json.loads(horarios)
        except (json.JSONDecodeError, ValueError):
            # String simples (ex: "06:00-23:00") — retorna diretamente
            return horarios if len(horarios) < 50 else None

    if isinstance(horarios, dict):
        # 1. Tenta chave específica do dia
        possiveis = DIAS_MAP.get(dia_semana_idx, [])
        for chave in possiveis:
            for key_orig, valor in horarios.items():
                if normalizar(key_orig).strip() == normalizar(chave).strip():
                    return str(valor)

        # 2. Tenta chaves agrupadas ("seg a sex", "dias uteis", etc.)
        for chave_agrupada, dias_range in AGRUPADOS.items():
            if dia_semana_idx in dias_range:
                for key_orig, valor in horarios.items():
                    if normalizar(chave_agrupada) in normalizar(key_orig):
                        return str(valor)

    return None


def montar_saudacao_humanizada(
    nome_cliente: str,
    nome_ia: str,
    pers: dict,
    unidade: dict,
    hor_banco: Any,
) -> str:
    """
    Monta uma saudação super humanizada:
    - Usa o nome do cliente se disponível
    - Deseja bom dia/boa tarde/boa noite pelo horário de SP
    - Menciona horário de HOJE se disponível no banco
    - Tom quente e acolhedor
    """
    cumprimento = saudacao_por_horario()
    nome_limpo = limpar_nome(nome_cliente) if nome_cliente else ""

    # Monta a primeira linha: cumprimento + nome
    if nome_limpo and nome_limpo.lower() not in ("cliente", "contato", "visitante", ""):
        primeiro_nome = nome_limpo.split()[0].capitalize()
        linha1 = f"{cumprimento}, {primeiro_nome}! 😊"
    else:
        linha1 = f"{cumprimento}! 😊"

    # Apresentação do assistente
    linha2 = f"Eu sou {'a' if nome_ia and nome_ia[-1].lower() == 'a' else 'o'} {nome_ia}, tudo bem?"

    # Horário de hoje (se disponível no banco)
    horario_hoje = horario_hoje_formatado(hor_banco)
    if horario_hoje:
        agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
        NOMES_DIA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
        nome_dia = NOMES_DIA[agora.weekday()]
        linha3 = f"Hoje ({nome_dia}) estamos funcionando das {horario_hoje} 💪"
    else:
        linha3 = ""

    # Pergunta final
    linha4 = "Como posso te ajudar?"

    # Monta mensagem
    partes = [linha1, linha2]
    if linha3:
        partes.append(linha3)
    partes.append(linha4)

    return "\n\n".join(partes)


# 🏋️ PALAVRAS-CHAVE DE TIPO DE CLIENTE — detecta aluno atual ou usuário de convênio
ALUNO_KEYWORDS = [
    "sou aluno", "ja sou aluno", "já sou aluno", "sou cliente", "sou membro",
    "meu contrato", "minha matricula", "minha matrícula", "meu plano atual",
    "cancelar meu", "congelar minha", "pausar minha", "segunda via",
    "boleto atrasado", "fatura", "renovar meu", "transferir minha",
    "mudei de unidade", "troca de unidade", "problema com",
    "atendimento ao cliente", "suporte", "reclamacao", "reclamação",
]

GYMPASS_KEYWORDS = [
    "gympass", "totalpass", "wellhub", "sesi", "sesc",
    "convenio", "convênio", "beneficio corporativo", "benefício corporativo",
    "pelo app", "pelo aplicativo", "app parceiro", "parceria empresa",
    "plano empresarial", "beneficio da empresa", "benefício da empresa",
]


def detectar_tipo_cliente(texto: str) -> Optional[str]:
    """
    Detecta se o cliente já é aluno (suporte/cancelamento/dúvidas)
    ou usa convênio/gympass (roteamento diferente).
    Retorna: 'aluno' | 'gympass' | None
    """
    if not texto:
        return None
    norm = normalizar(texto)
    if any(k in norm for k in [normalizar(k) for k in GYMPASS_KEYWORDS]):
        return "gympass"
    if any(k in norm for k in [normalizar(k) for k in ALUNO_KEYWORDS]):
        return "aluno"
    return None

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
    "🏢 Temos {total} unidades:\n\n{lista_str}\n\nQual delas fica mais perto de você?",
    "Claro! Nossas unidades são:\n\n{lista_str}\n\nQual é a mais conveniente pra você?",
    "Aqui estão nossas {total} unidades:\n\n{lista_str}\n\nEm qual posso te ajudar?",
    "Temos {total} unidades disponíveis:\n\n{lista_str}\n\nQual prefere?",
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
    except redis.RedisError as e:
        logger.error(f"❌ Erro ao conectar no Redis: {e}")
        raise e
    except Exception as e:
        logger.error(f"❌ Erro inesperado ao conectar no Redis: {e}")
        raise e

    if DATABASE_URL:
        try:
            db_pool = await asyncpg.create_pool(DATABASE_URL)
            logger.info("🐘 Conexão com PostgreSQL estabelecida com sucesso!")
        except asyncpg.PostgresConnectionStatusError as e:
            logger.error(f"❌ Falha de autenticação no PostgreSQL: {e}")
        except asyncpg.CannotConnectNowError as e:
            logger.error(f"❌ PostgreSQL não está aceitando conexões: {e}")
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


def formatar_planos_bonito(planos: List[Dict]) -> List[str]:
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

    for idx, p in enumerate(planos):
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
        pitch = (
            p.get('descricao') or
            p.get('pitch') or
            p.get('slogan') or
            "Treine com estrutura completa e total liberdade."
        )
        pitch = str(pitch).strip()

        # ── Emoji do plano ───────────────────────────────────────────
        emoji = _EMOJIS_PLANO[idx % len(_EMOJIS_PLANO)]

        # ── Montagem do bloco ────────────────────────────────────────
        linhas: List[str] = []

        # Cabeçalho
        linhas.append(f"{emoji} *{nome}*")
        linhas.append("")

        # Pitch
        linhas.append(pitch)
        linhas.append("")

        # Diferenciais
        if diferenciais:
            linhas.append("Você terá acesso a:")
            linhas.append("")
            for dif in diferenciais:
                linhas.append(f"• {str(dif).strip()}")
            linhas.append("")
            linhas.append("Tudo isso por apenas:")
            linhas.append("")
        else:
            linhas.append("Valor:")
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
        linhas.append("")

        # Pergunta de fechamento
        linhas.append("Quer saber como funciona ou tirar alguma dúvida?")

        blocos.append("\n".join(linhas))

    if not blocos:
        return ["Não temos planos disponíveis no momento. 😕"]

    # Cada bloco = mensagem separada (sem divisor entre eles)
    return blocos


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
# ── Cache Semântico por Embedding (RAG Lite) ─────────────────────────────────
# Permite cachear respostas baseadas em similaridade semântica, não só hash exato.
# Requer: pip install sentence-transformers  (opcional — fallback para hash md5)
try:
    from sentence_transformers import SentenceTransformer as _ST
    import numpy as _np
    _embed_model = _ST("all-MiniLM-L6-v2")  # modelo leve ~22MB
    _EMBED_OK = True
    logger.info("✅ Sentence Transformers carregado — cache semântico ativo")
except ImportError:
    _EMBED_OK = False


def _cosine_sim(a: list, b: list) -> float:
    """Similaridade de cosseno entre dois vetores."""
    if not _EMBED_OK:
        return 0.0
    va = _np.array(a, dtype="float32")
    vb = _np.array(b, dtype="float32")
    norm = (_np.linalg.norm(va) * _np.linalg.norm(vb))
    return float(_np.dot(va, vb) / norm) if norm > 0 else 0.0


async def buscar_cache_semantico(
    texto: str,
    slug: str,
    threshold: float = 0.88
) -> Optional[Dict]:
    """
    Busca no Redis por uma resposta cacheada semanticamente similar à pergunta.
    Funciona em 2 modos:
      - Com sentence-transformers: usa embedding + cosine similarity (preciso)
      - Sem: fallback para cache por hash md5 (exato)
    Retorna dict {"resposta": ..., "estado": ...} ou None.
    """
    if not _EMBED_OK:
        return None  # sem embeddings, usa hash normal

    try:
        emb_query = _embed_model.encode(texto).tolist()
        # Busca todas as chaves de embedding para este slug (até 200)
        pattern = f"semcache:{slug}:*"
        keys = await redis_client.keys(pattern)
        if not keys:
            return None

        melhor_score = 0.0
        melhor_key   = None
        for k in keys[:200]:  # limita busca
            emb_str = await redis_client.hget(k, "embedding")
            if not emb_str:
                continue
            emb_cached = json.loads(emb_str)
            score = _cosine_sim(emb_query, emb_cached)
            if score > melhor_score:
                melhor_score = score
                melhor_key   = k

        if melhor_score >= threshold and melhor_key:
            resposta_str = await redis_client.hget(melhor_key, "resposta")
            if resposta_str:
                logger.info(f"🧠 Cache semântico HIT (sim={melhor_score:.3f}) para '{texto[:40]}'")
                return json.loads(resposta_str)
    except Exception as e:
        logger.warning(f"Cache semântico erro: {e}")
    return None


async def salvar_cache_semantico(
    texto: str,
    slug: str,
    dados: Dict,
    ttl: int = 3600
):
    """
    Salva embedding + resposta no Redis para uso futuro no cache semântico.
    Chave: semcache:{slug}:{md5(texto)}
    """
    if not _EMBED_OK:
        return
    try:
        emb = _embed_model.encode(texto).tolist()
        chave = f"semcache:{slug}:{hashlib.md5(texto.encode()).hexdigest()}"
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
    except asyncpg.PostgresError as e:
        logger.error(f"Erro PostgreSQL ao buscar empresa por account_id {account_id}: {e}")
        if _PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="db_empresa_lookup").inc()
        return None
    except Exception as e:
        logger.error(f"Erro inesperado ao buscar empresa por account_id {account_id}: {e}")
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
    except asyncpg.PostgresError as e:
        logger.error(f"Erro PostgreSQL ao carregar integração {tipo} da empresa {empresa_id}: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"JSON inválido na integração {tipo} da empresa {empresa_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Erro inesperado ao carregar integração {tipo} da empresa {empresa_id}: {e}")
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

async def simular_digitacao(account_id: int, conversation_id: int, integracao: dict, segundos: float = 2.0):
    """
    Simula tempo de digitação humana com um simples sleep.
    O endpoint REST de typing status do Chatwoot requer WebSocket (ActionCable),
    não funciona via API token — usamos apenas o delay para naturalidade.
    """
    await asyncio.sleep(max(0.5, min(segundos, 6.0)))


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
    except httpx.TimeoutException as e:
        logger.error(f"⏱️ Timeout ao enviar mensagem para conversa {conversation_id}: {e}")
        if _PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="chatwoot_timeout").inc()
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ HTTP {e.response.status_code} ao enviar para conversa {conversation_id}: {e}")
        if _PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="chatwoot_http_error").inc()
        return None
    except httpx.ConnectError as e:
        logger.error(f"🔌 Conexão falhou ao enviar para conversa {conversation_id}: {e}")
        if _PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="chatwoot_connect_error").inc()
        return None
    except Exception as e:
        logger.error(f"Erro inesperado ao enviar mensagem para Chatwoot: {e}")
        if _PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="chatwoot_unknown").inc()
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

    # Lembrete amigável — pergunta de novo sem listar todas as unidades
    await enviar_mensagem_chatwoot(
        account_id, conversation_id,
        "Só pra eu não te perder de vista 😊\n\nQual cidade ou bairro você prefere para treinar?",
        "Assistente Virtual", integracao
    )

    await asyncio.sleep(480)
    if not await redis_client.exists(f"esperando_unidade:{conversation_id}"):
        return
    if await redis_client.exists(f"unidade_escolhida:{conversation_id}"):
        return

    # Sem resposta após 8 min — encerra conversa
    await redis_client.delete(f"esperando_unidade:{conversation_id}")
    url_c = f"{integracao['url']}/api/v1/accounts/{account_id}/conversations/{conversation_id}"
    try:
        await http_client.put(
            url_c, json={"status": "resolved"},
            headers={"api_access_token": integracao['token']}
        )
    except Exception as e:
        logger.warning(f"Erro ao encerrar conversa {conversation_id}: {e}")


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
    except asyncpg.PostgresError as e:
        logger.error(f"Erro PostgreSQL ao listar unidades para empresa {empresa_id}: {e}")
        if _PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="db_unidades_lista").inc()
        return []
    except Exception as e:
        logger.error(f"Erro inesperado ao listar unidades: {e}")
        return []


async def buscar_unidade_na_pergunta(texto: str, empresa_id: int) -> Optional[str]:
    """
    Tenta identificar uma unidade mencionada na pergunta do cliente.
    Estratégia em 4 camadas:
      1. Função SQL customizada (se existir)
      2. Correspondência exata/parcial em nome, cidade, bairro e palavras-chave
      3. Correspondência por partes (tokens) — suporta nomes compostos e abreviações
      4. Fuzzy matching conservador (threshold 90)
    """
    if not db_pool or not texto:
        return None

    # Ignora saudações genéricas mas NÃO ignora nomes de bairros de 1 palavra (Itaquera, Paulista...)
    if eh_saudacao(texto):
        return None

    # 1. Função SQL customizada (mais precisa, se disponível no banco)
    try:
        query = "SELECT unidade_slug FROM buscar_unidades_por_texto($1, $2) LIMIT 1"
        row = await db_pool.fetchrow(query, empresa_id, texto)
        if row:
            return row['unidade_slug']
    except asyncpg.UndefinedFunctionError:
        pass  # Função não existe no banco — usa fallback Python
    except asyncpg.PostgresError as e:
        logger.error(f"Erro SQL ao buscar unidade: {e}")

    # 2. Busca por palavras-chave, nome, cidade e bairro
    unidades = await listar_unidades_ativas(empresa_id)
    texto_norm = normalizar(texto)
    tokens_texto = set(texto_norm.split())  # tokens para matching por palavra

    for u in unidades:
        nome_norm   = normalizar(u.get('nome', ''))
        cidade_norm = normalizar(u.get('cidade', '') or '')
        bairro_norm = normalizar(u.get('bairro', '') or '')
        palavras_chave = [normalizar(p) for p in (u.get('palavras_chave') or []) if p]

        # Correspondência completa no texto
        if nome_norm and nome_norm in texto_norm:
            return u['slug']
        if cidade_norm and len(cidade_norm) > 3 and cidade_norm in texto_norm:
            return u['slug']
        if bairro_norm and len(bairro_norm) > 3 and bairro_norm in texto_norm:
            return u['slug']
        if any(p and len(p) > 3 and p in texto_norm for p in palavras_chave):
            return u['slug']

        # Matching por tokens — suporta "morumbi" encontrar "Smart Fit – Morumbi"
        # ou "sp" / "sao paulo" encontrar qualquer cidade de SP
        tokens_nome    = set(nome_norm.split())
        tokens_cidade  = set(cidade_norm.split()) if cidade_norm else set()
        tokens_bairro  = set(bairro_norm.split()) if bairro_norm else set()

        # Interseção de tokens significativos (ignora palavras curtas < 4 chars)
        _sig = lambda ts: {t for t in ts if len(t) >= 4}
        if _sig(tokens_texto) & _sig(tokens_cidade):
            return u['slug']
        if _sig(tokens_texto) & _sig(tokens_bairro):
            return u['slug']

        # Verifica se alguma palavra-chave é um token presente no texto
        for p in palavras_chave:
            tokens_pchave = set(p.split())
            if _sig(tokens_texto) & _sig(tokens_pchave):
                return u['slug']

    # 3. Fuzzy matching conservador — threshold 90 para evitar falsos positivos
    melhor_slug = None
    maior_score = 0
    for u in unidades:
        nome_norm   = normalizar(u.get('nome', ''))
        cidade_norm = normalizar(u.get('cidade', '') or '')
        bairro_norm = normalizar(u.get('bairro', '') or '')

        for campo in filter(None, [nome_norm, cidade_norm, bairro_norm]):
            score = fuzz.partial_ratio(campo, texto_norm)
            if score > maior_score:
                maior_score = score
                melhor_slug = u['slug']

    if maior_score >= 90:
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
    """
    Carrega as perguntas frequentes da unidade e retorna formatadas para o prompt da IA.
    Tenta duas queries: com prioridade+visualizacoes, e fallback sem visualizacoes
    (caso a coluna ainda não exista no banco).
    Loga aviso quando FAQ está vazio para facilitar diagnóstico.
    """
    if not db_pool:
        return ""

    cache_key = f"cfg:faq:{slug}:v3"
    cache = await redis_client.get(cache_key)
    if cache:
        return cache

    rows = []
    try:
        # Query principal — com prioridade e visualizacoes
        rows = await db_pool.fetch("""
            SELECT f.pergunta, f.resposta
            FROM faq f
            JOIN unidades u ON u.id = f.unidade_id
            WHERE u.slug = $1 AND u.empresa_id = $2 AND f.ativo = true
            ORDER BY f.prioridade DESC NULLS LAST, f.visualizacoes DESC NULLS LAST
            LIMIT 30
        """, slug, empresa_id)
    except asyncpg.UndefinedColumnError:
        # Fallback: sem a coluna visualizacoes
        try:
            rows = await db_pool.fetch("""
                SELECT f.pergunta, f.resposta
                FROM faq f
                JOIN unidades u ON u.id = f.unidade_id
                WHERE u.slug = $1 AND u.empresa_id = $2 AND f.ativo = true
                ORDER BY f.prioridade DESC NULLS LAST
                LIMIT 30
            """, slug, empresa_id)
        except asyncpg.UndefinedTableError:
            logger.warning(f"⚠️ Tabela 'faq' não existe no banco — FAQ desativado para {slug}")
            return ""
    except asyncpg.UndefinedTableError:
        logger.warning(f"⚠️ Tabela 'faq' não existe no banco — crie com CREATE TABLE faq (...)")
        return ""
    except asyncpg.PostgresError as e:
        logger.error(f"Erro PostgreSQL ao carregar FAQ de {slug}: {e}")
        return ""

    if not rows:
        logger.warning(f"⚠️ FAQ vazio para slug='{slug}' empresa_id={empresa_id} — verifique ativo=true e unidade_id")
        return ""

    faq_formatado = "\n\n".join([
        f"P: {r['pergunta']}\nR: {r['resposta']}"
        for r in rows
    ])
    await redis_client.setex(cache_key, 300, faq_formatado)
    logger.info(f"✅ FAQ carregado: {len(rows)} perguntas para {slug}")
    return faq_formatado


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

async def _coletar_metricas_unidade(empresa_id: int, unidade_id: int, hoje) -> Dict:
    """
    Coleta TODAS as métricas para uma unidade em determinada data.
    Retorna dict pronto para inserção em metricas_diarias.
    Cada query usa COALESCE para nunca retornar NULL.
    """
    # ── Conversas ──────────────────────────────────────────────────────
    total_conversas = await db_pool.fetchval("""
        SELECT COUNT(*) FROM conversas
        WHERE empresa_id = $1 AND unidade_id = $2
          AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0

    conversas_encerradas = await db_pool.fetchval("""
        SELECT COUNT(*) FROM conversas
        WHERE empresa_id = $1 AND unidade_id = $2
          AND status IN ('encerrada', 'resolved', 'closed')
          AND DATE(updated_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0

    conversas_sem_resposta = await db_pool.fetchval("""
        SELECT COUNT(*) FROM conversas
        WHERE empresa_id = $1 AND unidade_id = $2
          AND primeira_resposta_em IS NULL
          AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0

    novos_contatos = await db_pool.fetchval("""
        SELECT COUNT(DISTINCT telefone) FROM conversas
        WHERE empresa_id = $1 AND unidade_id = $2
          AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
          AND NOT EXISTS (
              SELECT 1 FROM conversas c2
              WHERE c2.empresa_id = $1
                AND c2.telefone = conversas.telefone
                AND c2.created_at < conversas.created_at
          )
    """, empresa_id, unidade_id, hoje) or 0

    # ── Mensagens ──────────────────────────────────────────────────────
    total_mensagens = await db_pool.fetchval("""
        SELECT COUNT(*) FROM mensagens m
        JOIN conversas c ON c.id = m.conversa_id
        WHERE c.empresa_id = $1 AND c.unidade_id = $2
          AND DATE(m.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
          AND m.role = 'user'
    """, empresa_id, unidade_id, hoje) or 0

    total_mensagens_ia = await db_pool.fetchval("""
        SELECT COUNT(*) FROM mensagens m
        JOIN conversas c ON c.id = m.conversa_id
        WHERE c.empresa_id = $1 AND c.unidade_id = $2
          AND DATE(m.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
          AND m.role = 'assistant'
    """, empresa_id, unidade_id, hoje) or 0

    # ── Leads & Conversão ──────────────────────────────────────────────
    leads_qualificados = await db_pool.fetchval("""
        SELECT COUNT(*) FROM conversas
        WHERE empresa_id = $1 AND unidade_id = $2
          AND lead_qualificado = true
          AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0

    # taxa_conversao = leads / total_conversas (0.0 se sem conversas)
    taxa_conversao = round(leads_qualificados / total_conversas, 4) if total_conversas > 0 else 0.0

    # ── Tempo de Resposta ──────────────────────────────────────────────
    tempo_medio_resposta = await db_pool.fetchval("""
        SELECT COALESCE(
            AVG(EXTRACT(EPOCH FROM (primeira_resposta_em - primeira_mensagem))),
            0
        )
        FROM conversas
        WHERE empresa_id = $1 AND unidade_id = $2
          AND primeira_resposta_em IS NOT NULL
          AND primeira_mensagem IS NOT NULL
          AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0.0

    # ── Eventos do Funil ───────────────────────────────────────────────
    total_solicitacoes_telefone = await db_pool.fetchval("""
        SELECT COUNT(*) FROM eventos_funil ef
        JOIN conversas c ON c.id = ef.conversa_id
        WHERE c.empresa_id = $1 AND c.unidade_id = $2
          AND ef.tipo_evento = 'solicitacao_telefone'
          AND DATE(ef.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0

    total_links_enviados = await db_pool.fetchval("""
        SELECT COUNT(*) FROM eventos_funil ef
        JOIN conversas c ON c.id = ef.conversa_id
        WHERE c.empresa_id = $1 AND c.unidade_id = $2
          AND ef.tipo_evento = 'link_matricula_enviado'
          AND DATE(ef.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0

    total_planos_enviados = await db_pool.fetchval("""
        SELECT COUNT(*) FROM eventos_funil ef
        JOIN conversas c ON c.id = ef.conversa_id
        WHERE c.empresa_id = $1 AND c.unidade_id = $2
          AND ef.tipo_evento = 'plano_exibido'
          AND DATE(ef.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0

    total_matriculas = await db_pool.fetchval("""
        SELECT COUNT(*) FROM eventos_funil ef
        JOIN conversas c ON c.id = ef.conversa_id
        WHERE c.empresa_id = $1 AND c.unidade_id = $2
          AND ef.tipo_evento IN ('matricula_realizada', 'checkout_concluido')
          AND DATE(ef.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0

    # ── Horário de Pico ────────────────────────────────────────────────
    # Hora com maior volume de mensagens recebidas
    pico_row = await db_pool.fetchrow("""
        SELECT EXTRACT(HOUR FROM m.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo')::int AS hora,
               COUNT(*) AS qtd
        FROM mensagens m
        JOIN conversas c ON c.id = m.conversa_id
        WHERE c.empresa_id = $1 AND c.unidade_id = $2
          AND m.role = 'user'
          AND DATE(m.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
        GROUP BY hora
        ORDER BY qtd DESC
        LIMIT 1
    """, empresa_id, unidade_id, hoje)
    pico_hora = int(pico_row['hora']) if pico_row else None

    # ── Satisfação Média ──────────────────────────────────────────────
    # Tenta buscar da tabela `avaliacoes` se existir; senão mantém NULL
    satisfacao_media = None
    try:
        satisfacao_media = await db_pool.fetchval("""
            SELECT COALESCE(AVG(nota), NULL)
            FROM avaliacoes av
            JOIN conversas c ON c.id = av.conversa_id
            WHERE c.empresa_id = $1 AND c.unidade_id = $2
              AND DATE(av.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
        """, empresa_id, unidade_id, hoje)
    except Exception:
        satisfacao_media = None  # tabela ainda não existe

    # ── Tokens / Custo IA ─────────────────────────────────────────────
    tokens_consumidos = None
    custo_estimado_usd = None
    try:
        row_tokens = await db_pool.fetchrow("""
            SELECT COALESCE(SUM(tokens_prompt + tokens_completion), 0) AS total_tokens,
                   COALESCE(SUM(custo_usd), 0.0) AS custo
            FROM uso_ia ui
            JOIN conversas c ON c.id = ui.conversa_id
            WHERE c.empresa_id = $1 AND c.unidade_id = $2
              AND DATE(ui.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
        """, empresa_id, unidade_id, hoje)
        if row_tokens:
            tokens_consumidos = int(row_tokens['total_tokens'])
            custo_estimado_usd = float(row_tokens['custo'])
    except Exception:
        pass  # tabela uso_ia pode não existir

    return {
        "total_conversas": total_conversas,
        "conversas_encerradas": conversas_encerradas,
        "conversas_sem_resposta": conversas_sem_resposta,
        "novos_contatos": novos_contatos,
        "total_mensagens": total_mensagens,
        "total_mensagens_ia": total_mensagens_ia,
        "leads_qualificados": leads_qualificados,
        "taxa_conversao": taxa_conversao,
        "tempo_medio_resposta": float(tempo_medio_resposta),
        "total_solicitacoes_telefone": total_solicitacoes_telefone,
        "total_links_enviados": total_links_enviados,
        "total_planos_enviados": total_planos_enviados,
        "total_matriculas": total_matriculas,
        "pico_hora": pico_hora,
        "satisfacao_media": satisfacao_media,
        "tokens_consumidos": tokens_consumidos,
        "custo_estimado_usd": custo_estimado_usd,
    }


async def worker_metricas_diarias():
    """
    Worker que roda a cada hora e persiste todas as métricas diárias.
    Usa ON CONFLICT para atualizar registros existentes (idempotente).
    Colunas opcionais (satisfacao_media, tokens, custo) são ignoradas com
    graceful fallback se a coluna ainda não existir no banco.
    """
    while True:
        await asyncio.sleep(3600)
        if not db_pool:
            continue
        try:
            hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
            empresas = await db_pool.fetch("SELECT id FROM empresas WHERE ativo = true")

            total_unidades = 0
            for emp in empresas:
                empresa_id = emp['id']
                unidades = await db_pool.fetch(
                    "SELECT id FROM unidades WHERE empresa_id = $1 AND ativo = true",
                    empresa_id
                )

                for unid in unidades:
                    unidade_id = unid['id']
                    total_unidades += 1

                    m = await _coletar_metricas_unidade(empresa_id, unidade_id, hoje)

                    # ── Upsert principal (colunas garantidas) ─────────────
                    await db_pool.execute("""
                        INSERT INTO metricas_diarias (
                            empresa_id, unidade_id, data,
                            total_conversas, conversas_encerradas, conversas_sem_resposta,
                            novos_contatos,
                            total_mensagens, total_mensagens_ia,
                            leads_qualificados, taxa_conversao,
                            tempo_medio_resposta,
                            total_solicitacoes_telefone, total_links_enviados,
                            total_planos_enviados, total_matriculas,
                            pico_hora,
                            satisfacao_media,
                            updated_at
                        )
                        VALUES (
                            $1, $2, $3,
                            $4, $5, $6,
                            $7,
                            $8, $9,
                            $10, $11,
                            $12,
                            $13, $14,
                            $15, $16,
                            $17,
                            $18,
                            NOW()
                        )
                        ON CONFLICT (empresa_id, unidade_id, data) DO UPDATE SET
                            total_conversas            = EXCLUDED.total_conversas,
                            conversas_encerradas       = EXCLUDED.conversas_encerradas,
                            conversas_sem_resposta     = EXCLUDED.conversas_sem_resposta,
                            novos_contatos             = EXCLUDED.novos_contatos,
                            total_mensagens            = EXCLUDED.total_mensagens,
                            total_mensagens_ia         = EXCLUDED.total_mensagens_ia,
                            leads_qualificados         = EXCLUDED.leads_qualificados,
                            taxa_conversao             = EXCLUDED.taxa_conversao,
                            tempo_medio_resposta       = EXCLUDED.tempo_medio_resposta,
                            total_solicitacoes_telefone = EXCLUDED.total_solicitacoes_telefone,
                            total_links_enviados       = EXCLUDED.total_links_enviados,
                            total_planos_enviados      = EXCLUDED.total_planos_enviados,
                            total_matriculas           = EXCLUDED.total_matriculas,
                            pico_hora                  = EXCLUDED.pico_hora,
                            satisfacao_media           = EXCLUDED.satisfacao_media,
                            updated_at                 = NOW()
                    """,
                        empresa_id, unidade_id, hoje,
                        m["total_conversas"], m["conversas_encerradas"], m["conversas_sem_resposta"],
                        m["novos_contatos"],
                        m["total_mensagens"], m["total_mensagens_ia"],
                        m["leads_qualificados"], m["taxa_conversao"],
                        m["tempo_medio_resposta"],
                        m["total_solicitacoes_telefone"], m["total_links_enviados"],
                        m["total_planos_enviados"], m["total_matriculas"],
                        m["pico_hora"],
                        m["satisfacao_media"],
                    )

                    # ── Colunas opcionais (tokens/custo) — graceful fallback ──
                    if m["tokens_consumidos"] is not None:
                        try:
                            await db_pool.execute("""
                                UPDATE metricas_diarias
                                SET tokens_consumidos  = $4,
                                    custo_estimado_usd = $5,
                                    updated_at         = NOW()
                                WHERE empresa_id = $1 AND unidade_id = $2 AND data = $3
                            """, empresa_id, unidade_id, hoje,
                                m["tokens_consumidos"], m["custo_estimado_usd"])
                        except Exception:
                            pass  # colunas ainda não existem no banco

            logger.info(f"✅ Métricas diárias atualizadas — {total_unidades} unidades / {hoje}")

        except asyncpg.PostgresError as e:
            logger.error(f"❌ Erro PostgreSQL no worker de métricas: {e}")
        except Exception as e:
            logger.error(f"❌ Erro inesperado no worker de métricas: {e}", exc_info=True)


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
        except httpx.TimeoutException as e:
            logger.error(f"⏱️ Timeout ao baixar áudio: {e}")
            if _PROMETHEUS_OK:
                METRIC_ERROS_TOTAL.labels(tipo="whisper_timeout").inc()
            return "[Erro ao baixar áudio: timeout]"
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ HTTP {e.response.status_code} ao baixar áudio: {e}")
            if _PROMETHEUS_OK:
                METRIC_ERROS_TOTAL.labels(tipo="whisper_http").inc()
            return "[Erro ao baixar áudio]"
        except Exception as e:
            logger.error(f"Erro Whisper: {e}")
            if _PROMETHEUS_OK:
                METRIC_ERROS_TOTAL.labels(tipo="whisper_unknown").inc()
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

        # Guard: se o cliente ainda não escolheu a unidade, não processa com IA
        # O webhook já enviou a pergunta "Em qual cidade/bairro você prefere treinar?"
        if await redis_client.exists(f"esperando_unidade:{conversation_id}"):
            logger.info(f"⏳ Conv {conversation_id} aguardando escolha de unidade — IA pausada")
            # Recoloca mensagens no buffet para serem processadas quando unidade for escolhida
            for m_json in mensagens_acumuladas:
                await redis_client.rpush(f"buffet:{conversation_id}", m_json)
            await redis_client.expire(f"buffet:{conversation_id}", 300)
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

        texto_norm_fast = normalizar(primeira_mensagem or "")
        fast_reply = None          # str  — mensagem única
        fast_reply_lista = None   # List[str] — múltiplas mensagens (ex: planos)

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
        # Texto combinado de TODAS as mensagens acumuladas para detectar intenção
        texto_combinado_norm = normalizar(" ".join(textos))

        if not imagens_urls:

            # Fast-path: detecta tipo de cliente (aluno/gympass) para roteamento correto
            # Roda em todas as mensagens acumuladas para maior cobertura
            _tipo_cliente = None
            for _t in textos:
                _tipo_cliente = detectar_tipo_cliente(_t)
                if _tipo_cliente:
                    break
            if not _tipo_cliente:
                _tipo_cliente = detectar_tipo_cliente(texto_combinado_norm)

            if _tipo_cliente == "gympass":
                if _PROMETHEUS_OK:
                    METRIC_ALUNO_DETECTADO.labels(tipo="gympass").inc()
                fast_reply = (
                    "💚 Que ótimo! Aceitamos *Gympass / TotalPass / Wellhub* e outros convênios.\n\n"
                    "Para garantir o melhor atendimento, me conta:\n\n"
                    "• Qual é o seu convênio?\n"
                    "• Em qual cidade ou bairro você prefere treinar?\n\n"
                    "Assim te direciono para a unidade certa 🏋️"
                )
                logger.info("⚡ Fast-path: cliente gympass/convênio detectado")
            elif _tipo_cliente == "aluno":
                if _PROMETHEUS_OK:
                    METRIC_ALUNO_DETECTADO.labels(tipo="aluno").inc()
                tel_suporte = (tel_banco or "nosso WhatsApp") if unidade else "nosso suporte"
                fast_reply = (
                    f"Olá! Vi que você já é aluno(a) 😊\n\n"
                    "Para questões relacionadas ao seu contrato, cancelamento, congelamento "
                    "ou financeiro, o melhor canal é falar diretamente com a nossa equipe:\n\n"
                    f"📞 {tel_suporte}\n\n"
                    "Posso ajudar com alguma outra dúvida? 💪"
                )
                logger.info("⚡ Fast-path: aluno detectado — redirecionado para suporte")

            # Fast-path: saudação humanizada
            # Ativa quando TODAS as mensagens acumuladas são saudações
            # Ex: "Boa noite" + "Tudo bem?" enviados em sequência rápida
            elif all(eh_saudacao(t) for t in textos) and textos:
                # Verifica se já houve troca de mensagens (histórico existente)
                _qtd_ia_anterior = 0
                try:
                    _qtd_ia_anterior = await db_pool.fetchval("""
                        SELECT COUNT(*) FROM mensagens m
                        JOIN conversas c ON c.id = m.conversa_id
                        WHERE c.conversation_id = $1 AND m.role = 'assistant'
                    """, conversation_id) or 0
                except Exception:
                    pass

                if _qtd_ia_anterior > 0:
                    # Conversa já existente — resposta curta, sem reapresentação
                    _cumprimento_breve = saudacao_por_horario()
                    fast_reply = f"{_cumprimento_breve}! 😊 Como posso ajudar?"
                    logger.info(f"⚡ Fast-path: saudação curta (histórico existente) para {nome_cliente}")
                else:
                    # Primeiro contato — saudação completa com nome, horário e horas abertas
                    fast_reply = montar_saudacao_humanizada(
                        nome_cliente=nome_cliente,
                        nome_ia=nome_ia,
                        pers=pers,
                        unidade=unidade,
                        hor_banco=hor_banco,
                    )
                    logger.info(f"⚡ Fast-path: saudação humanizada (primeiro contato) para {nome_cliente}")

            # Fast-path: listar unidades
            # Regex cobre singular E plural + com ou sem cidade na pergunta
            elif re.search(
                r"(quais.{0,15}unidades?"          # quais as unidades / quais unidade
                r"|quantas.{0,10}unidades?"        # quantas unidades
                r"|tem.{0,20}unidades?"            # tem unidade em SP / vcs tem unidades
                r"|unidades?.{0,10}tem"            # unidades que tem
                r"|mais.{0,10}unidades?"           # mais unidades
                r"|outras.{0,10}unidades?"         # outras unidades
                r"|lista.{0,10}unidades?"          # lista de unidades
                r"|onde.{0,10}academia"            # onde tem academia
                r"|academia.{0,15}(sp|sao paulo|rio|rj|mg|bh)"  # academia em SP / RJ
                r"|saber.{0,10}unidades?"          # queria saber as unidades
                r"|todas.{0,10}unidades?"          # todas as unidades
                r"|unidades?.{0,10}existem"        # quais unidades existem
                r"|unidades?.{0,10}disponiveis"    # unidades disponíveis
                r"|unidades?.{0,10}abertas"        # unidades abertas
                r"|unidades?.{0,15}(sp|sao paulo|rio|rj|mg|bh|campinas|curitiba|belo horizonte|brasilia))",
                texto_combinado_norm, re.IGNORECASE
            ):
                todas_ativas = await listar_unidades_ativas(empresa_id)
                if todas_ativas:
                    # Filtra por cidade se o cliente mencionou uma
                    _cidade_filtro = None
                    # 1. Verifica se alguma cidade do banco está na pergunta
                    for _u in todas_ativas:
                        _cid = normalizar(_u.get('cidade', '') or '')
                        if _cid and len(_cid) > 3 and _cid in texto_combinado_norm:
                            _cidade_filtro = _u.get('cidade')
                            break
                    # 2. Verifica abreviações de estado
                    _ESTADO_MAP = {
                        "sp": "São Paulo", "sao paulo": "São Paulo",
                        "rj": "Rio de Janeiro", "rio": "Rio de Janeiro",
                        "mg": "Minas Gerais", "bh": "Belo Horizonte",
                        "brasilia": "Brasília", "campinas": "Campinas",
                        "curitiba": "Curitiba",
                    }
                    if not _cidade_filtro:
                        for _abbr, _cidade_nome in _ESTADO_MAP.items():
                            if _abbr in texto_combinado_norm.split() or _abbr in texto_combinado_norm:
                                _cid_norm = normalizar(_cidade_nome)
                                _match = [u for u in todas_ativas if normalizar(u.get('cidade', '') or '').startswith(_cid_norm[:5])]
                                if _match:
                                    _cidade_filtro = _match[0].get('cidade')
                                    break

                    if _cidade_filtro:
                        _cid_norm = normalizar(_cidade_filtro)
                        unidades_lista = [u for u in todas_ativas if normalizar(u.get('cidade', '') or '') == _cid_norm]
                        if not unidades_lista:
                            unidades_lista = todas_ativas
                    else:
                        unidades_lista = todas_ativas

                    total = len(unidades_lista)
                    # Só o nome — cidade não é exibida (evita repetição e poluição)
                    lista_str = "\n".join([f"• {u['nome']}" for u in unidades_lista])

                    if _cidade_filtro and total > 0:
                        fast_reply = (
                            f"📍 Temos *{total} {'unidade' if total == 1 else 'unidades'}* em {_cidade_filtro}:\n\n"
                            f"{lista_str}\n\n"
                            "Qual delas fica mais perto de você? 😊"
                        )
                    else:
                        fast_reply = random.choice(RESPOSTAS_UNIDADES).format(
                            total=total, lista_str=lista_str
                        )
                    await bd_registrar_evento_funil(
                        conversation_id, "consulta_unidades",
                        f"Cliente solicitou unidades{' em ' + _cidade_filtro if _cidade_filtro else ''}",
                        score_incremento=1
                    )
                else:
                    fast_reply = "No momento não há unidades cadastradas. 😕"

            # Fast-path: planos — detecta intenção em QUALQUER das mensagens acumuladas
            # Regex amplo para cobrir: "quais são os planos", "me fala o valor", "tem promoção",
            # "quero me matricular", "como faço para assinar", etc.
            elif re.search(
                r"(preco|valor(es)?|quanto (custa|cobra|fica)"
                r"|mensalidade|planos?|promocao|promoç"
                r"|beneficio|benefícios|benefíci"
                r"|quais.{0,10}planos|me (fala|mostra|manda).{0,15}planos?"
                r"|tem planos?|ver planos?|quero (assinar|contratar|me matricular)"
                r"|como (faço|faz|funciona).{0,10}(matric|assinar|contratar)"
                r"|quanto (é|e|custa|vale) o plano"
                r"|opcoes.{0,10}planos?|opções.{0,10}planos?)",
                texto_combinado_norm
            ):
                if planos_ativos:
                    fast_reply_lista = formatar_planos_bonito(planos_ativos)
                    if _PROMETHEUS_OK:
                        METRIC_PLANOS_ENVIADOS.inc()
                        METRIC_FAST_PATH_TOTAL.labels(tipo="planos").inc()
                    await bd_registrar_evento_funil(
                        conversation_id, "link_matricula_enviado",
                        "Link enviado via fast-path", score_incremento=2
                    )
                    logger.info(f"⚡ Fast-path: {len(fast_reply_lista)} plano(s) — enviando como mensagens separadas")

            # Fast-path: endereço (texto combinado)
            elif unidade and re.search(
                r"(endereco|enderco|localizacao|fica onde|onde fica|como chego|qual o local|onde voces ficam)",
                texto_combinado_norm
            ):
                if end_banco and str(end_banco).strip().lower() not in ['não informado', 'none', '']:
                    fast_reply = random.choice(RESPOSTAS_ENDERECO).format(endereco=end_banco)

            # Fast-path: horários (texto combinado)
            elif unidade and re.search(
                r"(horario|funcionamento|abre|fecha|que horas|ta aberto|esta aberto)",
                texto_combinado_norm
            ):
                if hor_banco:
                    if isinstance(hor_banco, dict):
                        horario_str = "\n".join([f"• {dia}: {h}" for dia, h in hor_banco.items()])
                    else:
                        horario_str = str(hor_banco)
                    fast_reply = random.choice(RESPOSTAS_HORARIO).format(horario_str=horario_str)

            # Fast-path: contato (texto combinado)
            elif unidade and re.search(
                r"(telefone|contato|whatsapp|numero|ligar|falar com alguem)",
                texto_combinado_norm
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

        # Cache semântico (embedding) — consultado apenas se não houver cache exato
        _cache_sem = None
        if not resposta_cacheada and not fast_reply and not imagens_urls and not mudou_unidade and primeira_mensagem:
            _cache_sem = await buscar_cache_semantico(primeira_mensagem, slug)

        if fast_reply:
            logger.info("⚡ Fast-Path Ativado! Respondendo sem IA.")
            resposta_texto = fast_reply
            novo_estado = estado_atual

        elif resposta_cacheada and not imagens_urls and not mudou_unidade:
            logger.info("🧠 Cache Hash HIT! Respondendo direto do Redis.")
            dados_cache = json.loads(resposta_cacheada)
            resposta_texto = dados_cache["resposta"]
            novo_estado = dados_cache["estado"]

        elif _cache_sem and not imagens_urls and not mudou_unidade:
            logger.info("🧬 Cache Semântico HIT! Respondendo por similaridade.")
            resposta_texto = _cache_sem["resposta"]
            novo_estado = _cache_sem.get("estado", estado_atual)

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
                'temperatura', 'created_at', 'updated_at',
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

            prompt_sistema = f"""
Seu nome é {nome_ia}. Você é atendente da academia {nome_empresa}, unidade {nome_unidade}.

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

FAQ — RESPOSTAS PRONTAS (USE SEMPRE QUE A PERGUNTA DO CLIENTE SE ENCAIXAR):
{faq}

HISTÓRICO DA CONVERSA
{historico}

REGRAS CRÍTICAS — ANTI-ALUCINAÇÃO E CONDUÇÃO DE CONVERSA (OBRIGATÓRIO):
- Use EXCLUSIVAMENTE as informações presentes em "INFORMAÇÕES DA UNIDADE" acima.
- Se um campo estiver como "não informado", diga que não tem essa informação agora.
- NUNCA invente endereços, telefones, horários ou qualquer dado não informado.
- NUNCA diga que a empresa tem "apenas uma unidade" — você não tem essa informação completa.
- Em conversa casual (saudação, "tudo bem?", "por aí?"), responda de forma natural e acolhedora. NÃO empurre planos ou produtos sem que o cliente pergunte.
- CONDUZA a conversa naturalmente em direção à venda: pergunte sobre objetivos, ajude o cliente a perceber o valor. Não seja agressivo.
- Quando o cliente PERGUNTAR sobre planos/preços, aí sim apresente as opções.
- Em saudações, NÃO mencione o nome da unidade — apenas se apresente.
- Quando perguntarem seu nome, responda APENAS seu nome. Nada de "aqui na [unidade]".
- Se a pergunta do cliente bater com algum item do FAQ acima, USE exatamente aquela resposta.

FORMATAÇÃO DA RESPOSTA (OBRIGATÓRIO):
- Fale como uma pessoa real — NUNCA mencione ser IA, robô ou assistente virtual
- Use emojis com moderação (😊 💪 ✅)
- Separe parágrafos com linha em branco
- Para listas use • no início de cada item
- NÃO use markdown: sem **, sem ##, sem [texto](url)
- Links: sempre URL plana (ex: https://exemplo.com)
- Respostas curtas e diretas, sem enrolação
- Não se apresente novamente se já houver histórico
- NUNCA repita o nome do cliente dentro da mesma resposta — use no máximo uma vez, só na saudação inicial
- NUNCA comece respostas de acompanhamento com "Olá, [nome]!" — já cumprimentou antes
{aviso_mudanca}

DADOS DO ATENDIMENTO:
Cliente: {nome_cliente}
Estado emocional anterior: {estado_atual}

MENSAGENS DO CLIENTE (responda a TODAS):
{mensagens_formatadas}

Responda APENAS em JSON válido:
{{"resposta": "<mensagem ao cliente>", "estado": "<neutro|interessado|animado|hesitante|frustrado|conversao>"}}
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

            # ── Circuit Breaker check ─────────────────────────────────────────
            _cb_allowed = await cb_llm.is_allowed()
            if not _cb_allowed:
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
            else:
                goto_send = False

            if not goto_send:
                # ── Chamada ao LLM com timeout global + circuit breaker ───────────
                start_time = time.time()

                async def _chamar_llm(model_id: str, extra_timeout: int = 25):
                    return await asyncio.wait_for(
                        cliente_ia.chat.completions.create(
                            model=model_id,
                            messages=[
                                {"role": "system", "content": prompt_sistema},
                                {"role": "user", "content": conteudo_usuario if conteudo_usuario else " "}
                            ],
                            temperature=temperature,
                        ),
                        timeout=extra_timeout
                    )

                async with llm_semaphore:
                    try:
                        response = await _chamar_llm(modelo_escolhido, extra_timeout=25)
                        resposta_bruta = response.choices[0].message.content
                        await cb_llm.record_success()

                    except asyncio.TimeoutError:
                        logger.warning(f"⏱️ Timeout LLM (25s) — tentando fallback. Conv {conversation_id}")
                        await cb_llm.record_failure()
                        if _PROMETHEUS_OK:
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
                            logger.error(f"❌ Erro no fallback: {e2}")
                            await cb_llm.record_failure()
                            resposta_bruta = json.dumps({
                                "resposta": "Tive um problema técnico. Pode repetir em instantes? 😊",
                                "estado": estado_atual
                            })

                    except Exception as e:
                        logger.warning(f"⚠️ Erro LLM primário ({e}) — tentando fallback")
                        await cb_llm.record_failure()
                        if _PROMETHEUS_OK:
                            METRIC_ERROS_TOTAL.labels(tipo="llm_fallback").inc()
                        try:
                            modelo_fallback = "google/gemini-2.5-flash" if imagens_urls else "google/gemini-2.5-flash-lite"
                            response = await _chamar_llm(modelo_fallback, extra_timeout=20)
                            resposta_bruta = response.choices[0].message.content
                            await cb_llm.record_success()
                        except Exception as e2:
                            logger.error(f"❌ Fallback também falhou: {e2}")
                            await cb_llm.record_failure()
                            resposta_bruta = json.dumps({
                                "resposta": "Tive um problema técnico. Pode repetir em instantes? 😊",
                                "estado": estado_atual
                            })

                _latencia = time.time() - start_time
                logger.info(f"⏱️ LLM Latency: {_latencia:.2f}s")
                if _PROMETHEUS_OK:
                    METRIC_IA_LATENCY.observe(_latencia)

            if not goto_send:
                resposta_bruta = corrigir_json(resposta_bruta)
                try:
                    dados_ia = json.loads(resposta_bruta)
                    resposta_texto = dados_ia.get("resposta", "Desculpe, não consegui processar.")
                    novo_estado = dados_ia.get("estado", estado_atual).strip().lower()

                    # Garante que não há markdown na resposta da IA
                    resposta_texto = limpar_markdown(resposta_texto)

                    # 🔧 Pós-processamento: se a IA gerou uma resposta com múltiplos planos
                    # substitui pela versão bem formatada (evita fragmentação em msgs separadas)
                    _qtd_precos = resposta_texto.count("R$")
                    _qtd_links  = resposta_texto.count("http")
                    if planos_ativos and (_qtd_precos >= 2 or _qtd_links >= 2):
                        logger.info("🔧 Pós-processamento: resposta da IA contém planos — reformatando em msgs separadas")
                        fast_reply_lista = formatar_planos_bonito(planos_ativos)
                        resposta_texto = ""   # descarta resposta original da IA
                        if _PROMETHEUS_OK:
                            METRIC_PLANOS_ENVIADOS.inc()

                    if not imagens_urls:
                        _cache_payload = json.dumps({"resposta": resposta_texto, "estado": novo_estado})
                        await redis_client.setex(chave_cache_ia, 600, _cache_payload)
                        # Salva também no cache semântico (embedding) para futuras queries similares
                        if primeira_mensagem:
                            await salvar_cache_semantico(
                                primeira_mensagem, slug,
                                {"resposta": resposta_texto, "estado": novo_estado},
                                ttl=3600
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

        elif fast_reply_lista:
            # ── Planos: cada item da lista = 1 mensagem separada ──────────────
            for i, bloco_plano in enumerate(fast_reply_lista):
                if await redis_client.exists(f"pause_ia:{conversation_id}"):
                    break
                if not bloco_plano.strip():
                    continue
                typing_time = min(len(bloco_plano) * 0.012, 3.0) + random.uniform(0.2, 0.6)
                await simular_digitacao(account_id, conversation_id, integracao_chatwoot, typing_time)
                await enviar_mensagem_chatwoot(
                    account_id, conversation_id, bloco_plano.strip(), nome_ia, integracao_chatwoot
                )
                await bd_atualizar_msg_ia(conversation_id)
                if i == 0:
                    await bd_registrar_primeira_resposta(conversation_id)

        elif fast_reply:
            # ── Fast-path: envia UMA mensagem (saudação, endereço, horário, etc.) ──
            if not resposta_texto:
                resposta_texto = fast_reply if isinstance(fast_reply, str) else ""
            typing_time = min(len(resposta_texto) * 0.015, 3.5) + random.uniform(0.3, 0.8)
            await simular_digitacao(account_id, conversation_id, integracao_chatwoot, typing_time)
            await enviar_mensagem_chatwoot(
                account_id, conversation_id, resposta_texto, nome_ia, integracao_chatwoot
            )
            await bd_atualizar_msg_ia(conversation_id)
            await bd_registrar_primeira_resposta(conversation_id)

        else:
            # ── Resposta da IA: divide por parágrafo duplo para simular digitação ──
            if not resposta_texto or not resposta_texto.strip():
                pass  # nada para enviar
            else:
                paragrafos = [p.strip() for p in resposta_texto.split("\n\n") if p.strip()]
                if not paragrafos:
                    paragrafos = [resposta_texto.strip()]

                for i, paragrafo in enumerate(paragrafos):
                    if await redis_client.exists(f"pause_ia:{conversation_id}"):
                        break

                    typing_time = min(len(paragrafo) * 0.03, 5.0) + random.uniform(0.3, 1.0)
                    await simular_digitacao(account_id, conversation_id, integracao_chatwoot, typing_time)

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

    if _PROMETHEUS_OK:
        METRIC_WEBHOOKS_TOTAL.labels(event=event or "unknown").inc()

    # Rate limiting por conversa
    # Rate limit por conversa (anti-loop de webhook)
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

    if event == "conversation_created":
        # Nova conversa — garante que não há estado antigo no Redis (ex: conversas reutilizadas em testes)
        await redis_client.delete(
            f"pause_ia:{id_conv}", f"estado:{id_conv}",
            f"unidade_escolhida:{id_conv}", f"esperando_unidade:{id_conv}",
            f"atend_manual:{id_conv}", f"lock:{id_conv}", f"buffet:{id_conv}"
        )
        logger.info(f"🆕 Nova conversa {id_conv} — Redis limpo")
        return {"status": "conversa_criada"}

    if event == "conversation_updated":
        if conv_obj.get("status") == "resolved":
            await bd_finalizar_conversa(id_conv)
            await redis_client.delete(
                f"pause_ia:{id_conv}", f"estado:{id_conv}",
                f"unidade_escolhida:{id_conv}", f"esperando_unidade:{id_conv}",
                f"atend_manual:{id_conv}"
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
    esperando_unidade = await redis_client.get(f"esperando_unidade:{id_conv}")

    # Detecta unidade na mensagem APENAS em dois cenários:
    # 1) Já existe um slug definido (cliente quer trocar de unidade)
    # 2) Cliente está no fluxo de escolha de unidade (esperando_unidade=1)
    # NUNCA roda na primeira mensagem sem contexto — evita falsos positivos com 30 unidades
    if message_type == "incoming" and conteudo_texto and (slug or esperando_unidade):
        slug_detectado = await buscar_unidade_na_pergunta(conteudo_texto, empresa_id)
        if slug_detectado and slug_detectado != slug:
            logger.info(f"🔄 Webhook mudou contexto para {slug_detectado}")
            slug = slug_detectado
            await redis_client.setex(f"unidade_escolhida:{id_conv}", 86400, slug)
            if esperando_unidade:
                await redis_client.delete(f"esperando_unidade:{id_conv}")

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
            # Múltiplas unidades — fluxo inteligente de identificação
            texto_cliente = normalizar(conteudo_texto).strip()

            # Tenta por número digitado (ex: "1", "2")
            if not slug_detectado and texto_cliente.isdigit():
                idx = int(texto_cliente) - 1
                if 0 <= idx < len(unidades_ativas):
                    slug_detectado = unidades_ativas[idx]["slug"]

            if slug_detectado:
                # Unidade identificada — confirma com mensagem humanizada e prossegue
                slug = slug_detectado
                await redis_client.setex(f"unidade_escolhida:{id_conv}", 86400, slug)
                await redis_client.delete(f"esperando_unidade:{id_conv}")
                contato = payload.get("sender", {})
                _nome_contato = limpar_nome(contato.get("name"))
                await bd_iniciar_conversa(
                    id_conv, slug, account_id,
                    contato.get("id"), _nome_contato, empresa_id
                )
                await bd_registrar_evento_funil(
                    id_conv, "unidade_escolhida", f"Cliente escolheu {slug}", 3
                )

                # Envia confirmação humanizada com dados da unidade
                _unid_dados = await carregar_unidade(slug, empresa_id) or {}
                _nome_unid = _unid_dados.get('nome') or slug
                _end_unid = _unid_dados.get('endereco_completo') or _unid_dados.get('endereco') or ''
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
                    account_id, id_conv, _msg_confirmacao, _nome_ia_temp, integracao
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
                # Unidade não identificada — pergunta cidade/bairro de forma humanizada
                cfg = await carregar_configuracao_global(empresa_id)
                nome_empresa = cfg.get('nome_empresa') or 'nossa academia'
                _pers_bv = await carregar_personalidade(empresa_id) or {}
                _nome_ia_bv = _pers_bv.get('nome_ia') or 'Assistente Virtual'

                # Saudação personalizada com nome e horário
                _cumpr_bv = saudacao_por_horario()
                _contato_bv = payload.get("sender", {})
                _nome_bv = limpar_nome(_contato_bv.get("name"))
                _primeiro_bv = _nome_bv.split()[0].capitalize() if _nome_bv and _nome_bv.lower() not in ("cliente", "contato", "") else ""
                _saud_bv = f"{_cumpr_bv}, {_primeiro_bv}!" if _primeiro_bv else f"{_cumpr_bv}!"

                # Monta dica de cidades únicas (até 8 para não poluir)
                cidades_unicas = sorted(set(
                    u['cidade'] for u in unidades_ativas if u.get('cidade')
                ))
                if len(cidades_unicas) <= 8:
                    hint = "\n\n📍 Estamos em: " + " • ".join(cidades_unicas)
                elif len(cidades_unicas) <= 20:
                    hint = f"\n\n📍 Presentes em {len(cidades_unicas)} cidades"
                else:
                    hint = f"\n\n📍 {len(unidades_ativas)} unidades disponíveis"

                msg = (
                    f"{_saud_bv} Eu sou {'a' if _nome_ia_bv[-1:].lower() == 'a' else 'o'} {_nome_ia_bv} "
                    f"da {nome_empresa}, tudo bem? 😊\n\n"
                    "Para te direcionar ao melhor atendimento, me conta:\n\n"
                    "Em qual *cidade* ou *bairro* você prefere treinar? 🎯"
                    f"{hint}"
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


@app.get("/metrics")
async def metrics_endpoint():
    """
    Expõe métricas no formato Prometheus para scraping.
    Requer: pip install prometheus-client
    Integra com Grafana, Datadog, etc.
    """
    if not _PROMETHEUS_OK:
        return {
            "erro": "prometheus-client não instalado",
            "instrucao": "Execute: pip install prometheus-client"
        }
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


@app.get("/metricas/diagnostico")
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
    if not db_pool:
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
        colunas_banco = await db_pool.fetch("""
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

        registros = await db_pool.fetch(f"""
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
        ultima_atualizacao = await db_pool.fetchval("""
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


@app.get("/status")
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
        if db_pool:
            await db_pool.fetchval("SELECT 1")
            db_ok = True
    except Exception:
        pass
    return {
        "status": "online",
        "redis": "✅ conectado" if redis_ok else "❌ offline",
        "postgres": "✅ conectado" if db_ok else "❌ offline",
        "prometheus": "✅ ativo" if _PROMETHEUS_OK else "⚠️ não instalado",
        "versao": "2.5.0",
    }


@app.get("/")
async def health():
    return {
        "status": (
            "🤖 Motor SaaS IA v2.5 — Planos bonitos, aluno/gympass detectado, "
            "busca cidade/bairro aprimorada, métricas Prometheus, loguru!"
        )
    }
