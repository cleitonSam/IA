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
import os
import sys

# Garante que o diretório raiz esteja no sys.path para imports modularizados
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.append(_root)
from decimal import Decimal
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Request, BackgroundTasks, Header, HTTPException, Response
from dotenv import load_dotenv
from openai import AsyncOpenAI
import redis.asyncio as redis
import asyncpg
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from rapidfuzz import fuzz

# Imports para Fluxo Visual (Triagem)
from src.services.db_queries import carregar_fluxo_triagem, carregar_integracao
from src.services.flow_executor import executar_fluxo
from src.services.uaz_client import UazAPIClient
from src.utils.text_helpers import (
    nome_eh_valido as _nome_eh_valido_completo,
    primeiro_nome_cliente as _primeiro_nome_completo,
    extrair_nome_do_texto as _extrair_nome_completo,
    limpar_nome as _limpar_nome_th,
)

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

# --- PROMETHEUS METRICS ---
from src.core.config import (
    PROMETHEUS_OK as _PROMETHEUS_OK,
    METRIC_WEBHOOKS_TOTAL, METRIC_IA_LATENCY, METRIC_FAST_PATH_TOTAL,
    METRIC_ERROS_TOTAL, METRIC_CONVERSAS_ATIVAS, METRIC_PLANOS_ENVIADOS,
    METRIC_ALUNO_DETECTADO, generate_latest, CONTENT_TYPE_LATEST
)

load_dotenv()

CHATWOOT_URL = os.getenv("CHATWOOT_URL")
CHATWOOT_TOKEN = os.getenv("CHATWOOT_TOKEN")

app = FastAPI()

# ── CORS ─────────────────────────────────────────────────────────────────────
from fastapi.middleware.cors import CORSMiddleware
from src.core.config import FRONTEND_URL

_cors_origins = [
    FRONTEND_URL,
    "http://localhost:3000",
]
# Remove duplicatas e vazios
_cors_origins = list({o for o in _cors_origins if o})

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rotas de dashboard/auth da versão modular (sem quebrar o webhook legado)
from src.api.routers.auth import router as auth_router
from src.api.routers.dashboard import router as dashboard_router
from src.api.routers.management import router as management_router
from src.api.routers.uaz_webhook import router as uaz_webhook_router
from src.api.routers.ws import router as ws_router
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(management_router)
app.include_router(uaz_webhook_router)
app.include_router(ws_router)

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
        if _PROMETHEUS_OK:
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
                if _PROMETHEUS_OK:
                    METRIC_ERROS_TOTAL.labels(tipo="rate_limit_account").inc()
                from fastapi.responses import JSONResponse
                return JSONResponse({"status": "rate_limit_account"}, status_code=429)
        # Devolve o body ao request para que o endpoint possa lê-lo normalmente
        await _set_body(request, body)
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
                await redis_client.delete(f"cb:{self.name}:half_open_test")
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
            await redis_client.delete(f"cb:{self.name}:half_open_test")
            logger.warning(f"⚡ CircuitBreaker [{self.name}] → OPEN novamente (falha em HALF_OPEN)")
        else:
            fails = await redis_client.incr(k_fail)
            ttl = await redis_client.ttl(k_fail)
            if ttl in (-1, -2):
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
            test_key = f"cb:{self.name}:half_open_test"
            acquired = await redis_client.set(test_key, "1", nx=True, ex=30)
            return bool(acquired)
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


if not CHATWOOT_URL:
    logger.warning("CHATWOOT_URL não definido globalmente")
if not CHATWOOT_TOKEN:
    logger.warning("CHATWOOT_TOKEN não definido globalmente")
if not OPENROUTER_API_KEY:
    logger.warning("OPENROUTER_API_KEY não definido")
if not REDIS_URL:
    raise RuntimeError("REDIS_URL não definido")

EMPRESA_ID_PADRAO = 1
APP_VERSION = "2.5.0"

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
    # Mensagem curta (até 5 palavras) com match exato/início controlado
    if len(palavras) <= 5:
        return norm in SAUDACOES or any(norm.startswith(f"{s} ") for s in SAUDACOES)
    return False


def eh_confirmacao_curta(texto: str) -> bool:
    """Detecta confirmações curtas de continuidade (ex: 'quero sim', 'pode mandar')."""
    if not texto:
        return False
    t = normalizar(texto).strip()
    if len(t.split()) > 6:
        return False
    return bool(re.search(r"^(sim|quero sim|quero|pode|pode sim|pode mandar|manda|me passa|pode passar|ok|beleza|blz|claro)$", t))


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


def formatar_horarios_funcionamento(horarios: Any) -> str:
    """Converte horários da unidade em texto amigável para resposta direta ao cliente."""
    if not horarios:
        return "não informado"

    if isinstance(horarios, str):
        try:
            horarios = json.loads(horarios)
        except (json.JSONDecodeError, ValueError):
            return horarios

    if isinstance(horarios, dict):
        return "\n".join([f"- {dia}: {hora}" for dia, hora in horarios.items()])

    return str(horarios)


def garantir_frase_completa(txt: str) -> str:
    """Remove frase incompleta no final do texto para evitar resposta cortada."""
    if not txt:
        return txt
    txt = txt.strip()
    if not txt:
        return txt
    if txt[-1] in '.!?😊💪✅🏋🎯':
        return txt
    # Removemos '\n' para evitar que listas (bullets) sejam cortadas prematuramente
    for _sep in ['. ', '! ', '? ', '!\n', '?\n', '.\n']:
        _pos = txt.rfind(_sep)
        if _pos > len(txt) * 0.3:
            return txt[:_pos + 1].strip()
    return txt


def classificar_intencao(texto: str) -> str:
    """Classifica intenção principal com foco operacional (factual antes de LLM)."""
    t = normalizar(texto or "")
    if not t.strip():
        return "neutro"
    if eh_saudacao(t):
        return "saudacao"
    if re.search(r"(horario|horário|funcionamento|abre|fecha|que horas|aberto)", t):
        return "horario"
    if re.search(r"(endereco|endereço|localizacao|localização|onde fica|fica onde|como chegar)", t):
        return "endereco"
    if re.search(r"(telefone|whatsapp|contato|numero|número|ligar|falar com)", t):
        return "telefone"
    if re.search(r"(quais unidades|outras unidades|lista de unidades|quantas unidades|tem unidade|unidades)", t):
        return "unidades"
    if re.search(r"(preco|preço|valor|mensalidade|quanto custa|plano|planos|promo|promocao|promoção)", t):
        return "planos"
    if re.search(r"(grade de aulas?|grade|modalidade|modalidades|aulas?|musculacao|musculação|funcional|spinning|cross|pilates|yoga|zumba|fit\s?dance|fit\s?combat|muay|thai|jiu|jitsu|boxe|luta|lutas|jump|step|body\s?pump|body\s?balance|bike|hidroginastica|hidroginástica|natacao|natação|danca|dança|ballet|alongamento|rpg|circuito|hiit|treino)", t):
        return "modalidades"
    if re.search(r"(convenio|convênio|gympass|wellhub|totalpass)", t):
        return "convenio"
    return "llm"


def _faq_compativel_com_intencao(intencao: str, pergunta_faq: str) -> bool:
    """Evita FAQ fora de contexto (ex.: carnaval) para perguntas de grade/planos."""
    if not intencao or intencao in {"llm", "neutro", "saudacao"}:
        return True

    mapa = {
        "modalidades": {"aula", "aulas", "grade", "modalidade", "modalidades", "pilates", "zumba", "fit", "dance", "muay", "thai"},
        "horario": {"horario", "funcionamento", "abre", "fecha"},
        "endereco": {"endereco", "endereço", "local", "unidade", "fica"},
        "telefone": {"telefone", "whatsapp", "contato", "numero", "número"},
        "planos": {"plano", "planos", "valor", "preco", "preço", "mensalidade", "beneficio", "benefício"},
        "convenio": {"convenio", "convênio", "gympass", "wellhub", "totalpass"},
    }
    chaves = mapa.get(intencao)
    if not chaves:
        return True

    tokens_faq = {t for t in normalizar(pergunta_faq or "").split() if len(t) >= 3}
    return any(t in tokens_faq for t in chaves)


async def resolver_contexto_unidade(
    conversation_id: int,
    texto: str,
    empresa_id: int,
    slug_atual: Optional[str] = None
) -> Dict[str, Optional[str]]:
    """Resolve unidade da conversa em um único ponto (mensagem > contexto)."""
    # Prioriza contexto já salvo em Redis (mais confiável que slug transitório do webhook)
    slug_redis = await redis_client.get(f"unidade_escolhida:{conversation_id}")
    slug_salvo = slug_redis or slug_atual

    # Só tenta trocar unidade com evidência geográfica para evitar trocas acidentais.
    # Aqui consideramos:
    # 1) match direto de nome/cidade/bairro
    # 2) interseção de tokens significativos com nome da unidade (ex.: "ricardo jafet")
    texto_norm = normalizar(texto or "")
    tokens_texto_sig = {t for t in texto_norm.split() if len(t) >= 4}
    tem_geo = False
    try:
        unidades = await listar_unidades_ativas(empresa_id)
        for u in unidades:
            nome_u = normalizar(u.get("nome", "") or "")
            cidade_u = normalizar(u.get("cidade", "") or "")
            bairro_u = normalizar(u.get("bairro", "") or "")

            # Match direto
            if any(ind and len(ind) >= 4 and ind in texto_norm for ind in (nome_u, cidade_u, bairro_u)):
                tem_geo = True
                break

            # Match por tokens do nome da unidade (suporta "ricardo jafet" sem nome completo)
            tokens_nome_sig = {t for t in nome_u.split() if len(t) >= 4 and t not in {"red", "fitness", "academia", "unidade"}}
            if len(tokens_texto_sig & tokens_nome_sig) >= 1:
                tem_geo = True
                break
    except Exception:
        tem_geo = False

    slug_detectado = await buscar_unidade_na_pergunta(texto, empresa_id) if tem_geo else None

    if slug_detectado:
        mudou = slug_detectado != slug_salvo
        if mudou:
            await redis_client.setex(f"unidade_escolhida:{conversation_id}", 86400, slug_detectado)
        return {"slug": slug_detectado, "origem": "mensagem", "mudou": "true" if mudou else "false"}

    if slug_salvo:
        return {"slug": slug_salvo, "origem": "contexto", "mudou": "false"}

    return {"slug": None, "origem": "indefinido", "mudou": "false"}


def responder_horario(unidade: dict) -> str:
    nome = unidade.get("nome") or "da unidade"
    horarios = formatar_horarios_funcionamento(unidade.get("horarios"))
    return (
        f"🕒 O horário da unidade *{nome}* é:\n"
        f"{horarios}\n\n"
        "Se quiser, também posso te passar o endereço 😊"
    )


def extrair_endereco_unidade(unidade: dict) -> Optional[str]:
    """Monta endereço completo com número quando necessário."""
    endereco = (unidade.get("endereco_completo") or unidade.get("endereco") or "").strip()
    numero = str(unidade.get("numero") or "").strip()
    if not endereco:
        return None
    if numero and numero.lower() not in {"s/n", "sn"}:
        # Se número ainda não aparece no endereço, concatena
        if numero not in endereco:
            endereco = f"{endereco}, {numero}"
    return endereco


def normalizar_lista_campo(valor: Any) -> List[str]:
    """Converte campo de lista (list/json/string) em itens limpos para WhatsApp."""
    if not valor:
        return []
    if isinstance(valor, list):
        bruto = valor
    elif isinstance(valor, str):
        txt = valor.strip()
        if not txt:
            return []
        try:
            parsed = json.loads(txt)
            if isinstance(parsed, list):
                bruto = parsed
            elif isinstance(parsed, str):
                bruto = [parsed]
            else:
                bruto = [txt]
        except Exception:
            # Se vier texto corrido/grade, quebra por linha e separadores mais comuns
            bruto = [p for p in re.split(r"\n+|;|\|", txt) if p and p.strip()]
    else:
        bruto = [str(valor)]

    itens = []
    for item in bruto:
        t = str(item).strip()
        if not t:
            continue
        # Remove marcadores/bullets estranhos no início
        t = re.sub(r"^[•\-⁠​\s]+", "", t).strip()
        if len(t) <= 1:
            continue
        itens.append(t)

    # Se ainda parece texto por caractere, tenta recompor como única linha
    if itens and all(len(i) == 1 for i in itens):
        juntado = "".join(itens).strip()
        return [juntado] if juntado else []

    return itens


def extrair_telefone_unidade(unidade: dict) -> Optional[str]:
    return (
        unidade.get("telefone_principal")
        or unidade.get("telefone")
        or unidade.get("whatsapp")
    )


def responder_endereco(unidade: dict) -> str:
    nome = unidade.get("nome") or "da unidade"
    endereco = extrair_endereco_unidade(unidade)
    if not endereco:
        return (
            f"📍 No momento não encontrei o endereço da unidade *{nome}*.\n\n"
            "Se quiser, posso te passar o telefone da unidade."
        )
    return (
        f"📍 A unidade *{nome}* fica em:\n{endereco}\n\n"
        "Se quiser, também te passo o horário de funcionamento 😊"
    )


def responder_telefone(unidade: dict) -> str:
    nome = unidade.get("nome") or "da unidade"
    telefone = extrair_telefone_unidade(unidade)
    if not telefone:
        return (
            f"📞 No momento não encontrei o contato da unidade *{nome}*.\n\n"
            "Se quiser, posso te passar o endereço."
        )
    return (
        f"📞 O contato da unidade *{nome}* é:\n{telefone}\n\n"
        "Se quiser, também posso te passar o endereço ou horário."
    )


def responder_modalidades(unidade: dict) -> str:
    """Responde sobre modalidades/aulas da unidade usando dados textuais."""
    nome = unidade.get("nome") or "da unidade"
    modalidades = normalizar_lista_campo(unidade.get("modalidades"))

    if not modalidades:
        return (
            f"💪 Na unidade *{nome}* temos diversas atividades incríveis!\n\n"
            "Geralmente temos musculação, cardio e aulas coletivas. "
            "Qual modalidade você mais gosta? 😊"
        )

    lista = "\n".join([f"• {m}" for m in modalidades])
    resposta = f"💪 Na unidade *{nome}* temos:\n\n{lista}"

    foto_grade = unidade.get("foto_grade")
    if foto_grade:
        resposta += "\n\n🖼️ *Também tenho a grade completa com os horários das aulas!* Quer que eu te envie? 😊"
    else:
        resposta += "\n\nQual dessas você mais tem interesse? 😊"

    return resposta


async def responder_lista_unidades(empresa_id: int, texto: str) -> str:
    unidades = await listar_unidades_ativas(empresa_id)
    if not unidades:
        return "No momento não encontrei unidades cadastradas."

    texto_norm = normalizar(texto)
    cidade_filtro = None
    for u in unidades:
        cidade = normalizar(u.get("cidade", "") or "")
        if cidade and cidade in texto_norm:
            cidade_filtro = u.get("cidade")
            break

    if cidade_filtro:
        unidades = [u for u in unidades if normalizar(u.get("cidade", "") or "") == normalizar(cidade_filtro)]

    lista = "\n".join([f"• {u['nome']}" for u in unidades])
    if cidade_filtro:
        return (
            f"📍 Temos {len(unidades)} unidade(s) em *{cidade_filtro}*:\n\n{lista}\n\n"
            "Qual delas fica melhor para você? 😊"
        )
    return f"📍 Temos {len(unidades)} unidades:\n\n{lista}\n\nQual delas fica mais perto de você? 😊"


async def gerar_resposta_inteligente(
    conversation_id: int,
    empresa_id: int,
    texto_cliente: str,
    slug_atual: Optional[str] = None,
    nome_cliente: Optional[str] = None
) -> Dict[str, Any]:
    """Motor de decisão enxuto: fast-path apenas para horário/endereço."""
    ctx = await resolver_contexto_unidade(conversation_id, texto_cliente, empresa_id, slug_atual=slug_atual)
    slug = ctx.get("slug")
    intencao = classificar_intencao(texto_cliente)

    if intencao in {"horario", "endereco"} and not slug:
        _primeiro_nome = primeiro_nome_cliente(nome_cliente)
        _prefixo = f"{_primeiro_nome}, " if _primeiro_nome else ""
        return {
            "tipo": "texto",
            "resposta": f"{_prefixo}me fala a *cidade* ou *bairro* da unidade que você quer 😊",
            "slug": None,
            "intencao": intencao,
        }

    unidade = await carregar_unidade(slug, empresa_id) if slug else {}

    if intencao == "horario":
        return {"tipo": "texto", "resposta": responder_horario(unidade), "slug": slug, "intencao": intencao}
    if intencao == "endereco":
        return {"tipo": "texto", "resposta": responder_endereco(unidade), "slug": slug, "intencao": intencao}
    if intencao == "modalidades":
        return {"tipo": "texto", "resposta": responder_modalidades(unidade), "slug": slug, "intencao": intencao}

    return {"tipo": "llm", "resposta": None, "slug": slug, "intencao": "llm"}


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
    "modalidades": ["modalidades", "atividades", "exercícios", "treinos", "aula", "aulas", "grade", "grade de aula", "grade de aulas", "musculação", "cardio", "spinning", "alongamento", "crossfit", "funcional"],
    "infraestrutura": ["estacionamento", "vestiário", "chuveiro", "armários", "sauna", "piscina", "acessibilidade", "infraestrutura"],
    "matricula": ["matricula", "matrícula", "inscrição", "cadastro", "se inscrever", "assinar", "contratar"]
}

# Clientes de IA
cliente_ia = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY) if OPENROUTER_API_KEY else None
cliente_whisper = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Clientes Globais de Conexão
http_client: httpx.AsyncClient = None
redis_client: redis.Redis = None
db_pool: asyncpg.Pool = None
worker_tasks: List[asyncio.Task] = []
is_shutting_down = False
_LOCAL_REDIS_FALLBACK: Dict[str, tuple] = {}  # key -> (exp_ts, json_str)


def _log_worker_task_result(task: asyncio.Task):
    """Evita 'Task exception was never retrieved' e registra falhas de workers."""
    try:
        _ = task.exception()
    except asyncio.CancelledError:
        return
    except Exception as e:
        nome = task.get_name() if hasattr(task, 'get_name') else 'worker'
        if not is_shutting_down:
            logger.error(f"❌ {nome} finalizou com erro não tratado: {e}")

# --- CONTROLE DE CONCORRÊNCIA ---
whisper_semaphore = asyncio.Semaphore(5)
llm_semaphore = asyncio.Semaphore(15)
USAR_CACHE_SEMANTICO = os.getenv("USAR_CACHE_SEMANTICO", "false").lower() == "true"

LUA_RELEASE_LOCK = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

# Regex compiladas para intenções frequentes (manutenção centralizada)
REGEX_PEDIDO_PLANOS = re.compile(
    r"(preco|valor(es)?|quanto (custa|cobra|fica)|mensalidade|planos?|promocao|promoç|"
    r"beneficio|benefícios|benefíci|quais.{0,10}planos|me (fala|mostra|manda).{0,15}planos?|"
    r"tem planos?|ver planos?|quero (assinar|contratar|me matricular)|"
    r"como (faço|faz|funciona).{0,10}(matric|assinar|contratar)|"
    r"quanto (é|e|custa|vale) o plano|opcoes.{0,10}planos?|opções.{0,10}planos?)",
    re.IGNORECASE,
)
REGEX_PEDIDO_END_HOR = re.compile(
    r"(endereco|enderco|localizacao|fica onde|onde fica|como chego|qual o local|onde voces ficam"
    r"|horario|funcionamento|abre|fecha|que horas|ta aberto|esta aberto)",
    re.IGNORECASE,
)
REGEX_PEDIDO_CONTATO = re.compile(r"(telefone|contato|whatsapp|numero|ligar|falar com alguem)", re.IGNORECASE)
REGEX_LISTAR_UNIDADES = re.compile(
    r"(quais.{0,15}unidades?|quantas.{0,10}unidades?|tem.{0,20}unidades?|unidades?.{0,10}tem|"
    r"mais.{0,10}unidades?|outras.{0,10}unidades?|lista.{0,10}unidades?|onde.{0,10}academia|"
    r"academia.{0,15}(sp|sao paulo|rio|rj|mg|bh)|saber.{0,10}unidades?|todas.{0,10}unidades?|"
    r"unidades?.{0,10}existem|unidades?.{0,10}disponiveis|unidades?.{0,10}abertas|"
    r"unidades?.{0,15}(sp|sao paulo|rio|rj|mg|bh|campinas|curitiba|belo horizonte|brasilia))",
    re.IGNORECASE,
)

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
    global http_client, redis_client, db_pool, worker_tasks, is_shutting_down
    is_shutting_down = False
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
            # Roda migrations pendentes automaticamente
            try:
                from alembic.config import Config as AlembicConfig
                from alembic import command as alembic_command
                from alembic.script import ScriptDirectory
                alembic_cfg = AlembicConfig("alembic.ini")
                loop = asyncio.get_event_loop()

                # Descobre a head única dos arquivos de migration
                _script_dir = ScriptDirectory.from_config(alembic_cfg)
                _file_heads = _script_dir.get_heads()
                _target_head = _file_heads[0] if _file_heads else "head"

                # Limpa versões órfãs: se alembic_version tem múltiplas linhas, força para a head atual
                _temp_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=1, timeout=5)
                try:
                    _ver_rows = await _temp_pool.fetch("SELECT version_num FROM alembic_version")
                    _db_versions = [r["version_num"] for r in _ver_rows]
                    if len(_db_versions) > 1 or (len(_db_versions) == 1 and _db_versions[0] not in {r.revision for r in _script_dir.walk_revisions()}):
                        logger.warning(f"⚠️ alembic_version com {len(_db_versions)} entradas órfãs: {_db_versions} — limpando para {_target_head}")
                        await _temp_pool.execute("DELETE FROM alembic_version")
                        await _temp_pool.execute("INSERT INTO alembic_version (version_num) VALUES ($1)", _target_head)
                        logger.info(f"🔧 alembic_version limpa e fixada em {_target_head}")
                except Exception as _ver_err:
                    logger.debug(f"Verificação alembic_version: {_ver_err}")
                finally:
                    await _temp_pool.close()

                await loop.run_in_executor(
                    None,
                    lambda: alembic_command.upgrade(alembic_cfg, _target_head)
                )
                logger.info("✅ Migrations aplicadas com sucesso (alembic upgrade head)")
            except Exception as migration_err:
                logger.warning(f"⚠️ Falha ao aplicar migrations: {migration_err}")

            db_pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=2,
                max_size=10,
                command_timeout=10,
                timeout=5,
            )
            import src.core.database as core_database
            core_database.db_pool = db_pool
            logger.info("🐘 Conexão com PostgreSQL estabelecida com sucesso!")
        except asyncpg.PostgresConnectionStatusError as e:
            logger.error(f"❌ Falha de autenticação no PostgreSQL: {e}")
            raise e
        except asyncpg.CannotConnectNowError as e:
            logger.error(f"❌ PostgreSQL não está aceitando conexões: {e}")
            raise e
        except Exception as e:
            logger.error(f"❌ Erro ao conectar no PostgreSQL: {e}")
            raise e
    else:
        logger.warning("⚠️ DATABASE_URL não definida. As métricas não serão salvas.")

    if OPENROUTER_API_KEY and cliente_ia:
        logger.info("🤖 OpenRouter habilitado (OPENROUTER_API_KEY carregada)")

    worker_tasks = [
        asyncio.create_task(worker_followup(), name="worker_followup"),
        asyncio.create_task(worker_metricas_diarias(), name="worker_metricas_diarias"),
        asyncio.create_task(worker_sync_planos(), name="worker_sync_planos"),
        asyncio.create_task(worker_cleanup_followups(), name="worker_cleanup_followups"),
        # asyncio.create_task(worker_resumo_ia(), name="worker_resumo_ia"),
    ]
    for _task in worker_tasks:
        _task.add_done_callback(_log_worker_task_result)

    # ⚠️  Os workers usam _worker_leader_check() internamente para garantir que
    # apenas UM processo execute em ambientes multi-worker (uvicorn --workers N).


@app.on_event("shutdown")
async def shutdown_event():
    global is_shutting_down
    is_shutting_down = True

    for task in worker_tasks:
        task.cancel()
    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        worker_tasks.clear()

    await http_client.aclose()
    await redis_client.aclose()
    if db_pool:
        await db_pool.close()
        import src.core.database as core_database
        core_database.db_pool = None
    logger.info("🛑 Servidor desligado.")


# --- UTILITÁRIOS ---

def normalizar(texto: str) -> str:
    """Remove acentos e converte para minúsculas"""
    if not texto:
        return ""
    return unicodedata.normalize("NFD", str(texto).lower()).encode("ascii", "ignore").decode("utf-8")


def _render_followup_template(template: str, nome_contato: str, nome_unidade: str) -> str:
    texto = template or ""

    nome = (nome_contato or "").strip() or "você"
    unidade = (nome_unidade or "").strip()

    for token in ("{{nome}}", "{nome}"):
        texto = texto.replace(token, nome)

    for token in ("{{unidade}}", "{unidade}"):
        texto = texto.replace(token, unidade)

    if not unidade:
        texto = re.sub(r"\bsobre\s+a\s*\.?", "", texto, flags=re.IGNORECASE)
        texto = re.sub(r"\s{2,}", " ", texto).strip()

    return texto


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
    """Wrapper — usa versão completa do text_helpers."""
    return _limpar_nome_th(nome)


def primeiro_nome_cliente(nome: Optional[str]) -> str:
    """Wrapper — usa versão completa do text_helpers com blocklist de 100+ nomes."""
    return _primeiro_nome_completo(nome)


def nome_eh_valido(nome: Optional[str]) -> bool:
    """Wrapper — usa versão completa do text_helpers com blocklist de 100+ nomes.
    Detecta nomes falsos de WhatsApp: 'Boa', 'estrela', 'costureira', etc.
    """
    return _nome_eh_valido_completo(nome)


def extrair_nome_do_texto(texto: str) -> Optional[str]:
    """Wrapper — usa versão completa do text_helpers com padrões expandidos."""
    return _extrair_nome_completo(texto)


def _is_provider_unavailable_error(err: Exception) -> bool:
    """Detecta indisponibilidade de provedor LLM para acionar modo degradado."""
    msg = normalizar(str(err) or "")
    sinais = [
        "key limit exceeded", "limit exceeded", "quota", "insufficient credits",
        "credit", "rate limit", "error code: 403", "error code: 402",
    ]
    return any(s in msg for s in sinais)


def _is_openrouter_auth_error(err: Exception) -> bool:
    """Detecta erro de credencial/autorização da OPENROUTER_API_KEY."""
    msg = normalizar(str(err) or "")
    sinais = ["401", "unauthorized", "invalid api key", "authentication", "forbidden"]
    return any(s in msg for s in sinais)


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
        pattern = f"semcache:{slug}:*"
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
    Salva embedding (via API) + resposta no Redis para uso futuro.
    Chave: semcache:{slug}:{md5(texto)}
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
                _cur_lim, match=f"semcache:{slug}:*", count=100
            )
            _total_slug += len(_kk_lim)
            if _cur_lim == 0 or _total_slug >= 500:
                break
        if _total_slug >= 500:
            logger.debug(f"semcache: limite 500 atingido para slug={slug}, entrada descartada")
            return

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


async def coletar_mensagens_buffer(conversation_id: int) -> List[str]:
    """Coleta mensagens do buffer e limpa a fila da conversa.

    Faz uma coalescência curta para agrupar rajadas (2-4 mensagens seguidas)
    em uma única resposta, reduzindo respostas duplicadas e melhorando fluidez.
    """
    chave_buffet = f"buffet:{conversation_id}"

    mensagens_acumuladas: List[str] = []
    deadline = time.time() + 3.0  # janela de 3s para juntar rajada WhatsApp
    _checks_vazios = 0  # quantas vezes consecutivas o buffer estava vazio

    while True:
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.lrange(chave_buffet, 0, -1)
            pipe.delete(chave_buffet)
            resultado = await pipe.execute()
        lote = resultado[0] or []
        if lote:
            mensagens_acumuladas.extend(lote)
            _checks_vazios = 0
            if len(mensagens_acumuladas) >= 8 or time.time() >= deadline:
                break
            await asyncio.sleep(0.5)
            continue
        # Buffer vazio
        _checks_vazios += 1
        if time.time() >= deadline:
            break
        if mensagens_acumuladas and _checks_vazios >= 4:
            # Já tem msgs e buffer ficou vazio 4x seguidas — rajada acabou
            break
        await asyncio.sleep(0.5)

    logger.info(f"📦 Buffer tem {len(mensagens_acumuladas)} mensagens para conv {conversation_id}")
    return mensagens_acumuladas


async def aguardar_escolha_unidade_ou_reencaminhar(conversation_id: int, mensagens_acumuladas: List[str]) -> bool:
    """Reencaminha buffer quando conversa ainda está aguardando escolha de unidade."""
    if not await redis_client.exists(f"esperando_unidade:{conversation_id}"):
        return False

    logger.info(f"⏳ Conv {conversation_id} aguardando escolha de unidade — IA pausada")
    for m_json in mensagens_acumuladas:
        await redis_client.rpush(f"buffet:{conversation_id}", m_json)
    await redis_client.expire(f"buffet:{conversation_id}", 300)
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
                conversation_id, "mudanca_unidade", f"Contexto alterado para {slug}", score_incremento=1
            )

    return {"slug": slug, "mudou_unidade": mudou_unidade, "primeira_mensagem": primeira_mensagem}


async def persistir_mensagens_usuario(conversation_id: int, textos: List[str], transcricoes: List[str]):
    """Persiste histórico de mensagens do usuário (texto e áudio transcrito)."""
    for txt in textos:
        await bd_salvar_mensagem_local(conversation_id, "user", txt)
    for transc in transcricoes:
        await bd_salvar_mensagem_local(conversation_id, "user", f"[Áudio] {transc}")


async def redis_get_json(key: str, default=None):
    try:
        raw = await redis_client.get(key)
    except Exception:
        raw = None

    if raw is not None:
        try:
            return json.loads(raw)
        except Exception:
            return default

    # Fallback local em memória quando Redis estiver indisponível
    now = time.time()
    item = _LOCAL_REDIS_FALLBACK.get(key)
    if item:
        exp_ts, raw_local = item
        if exp_ts >= now:
            try:
                return json.loads(raw_local)
            except Exception:
                return default
        _LOCAL_REDIS_FALLBACK.pop(key, None)
    return default


async def redis_set_json(key: str, value: Any, ttl: int):
    payload = json.dumps(value, default=str)
    try:
        await redis_client.setex(key, ttl, payload)
    except Exception:
        _LOCAL_REDIS_FALLBACK[key] = (time.time() + max(1, ttl), payload)


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
    cache = await redis_get_json(cache_key)
    if cache is not None:
        return cache

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
            await redis_set_json(cache_key, config, 300)
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

            valor_total = item.get('value') or 0
            if not valor_total:
                continue

            # Só divide por 12 se o valor for maior que 1000 (ex: plano anual)
            valor_mensal = (valor_total / 12) if valor_total > 1000 else valor_total

            valor_promo_total = item.get('valuePromotionalPeriod')
            if valor_promo_total:
                valor_promo_mensal = (valor_promo_total / 12) if valor_promo_total > 1000 else valor_promo_total
            else:
                valor_promo_mensal = None

            plano = {
                'id': item.get('idMembership'),
                'nome': item.get('displayName') or item.get('nameMembership', 'Plano'),
                'valor': round(valor_mensal, 2) if valor_mensal else 0,
                'valor_promocional': round(valor_promo_mensal, 2) if valor_promo_mensal else None,
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
    cached = await redis_get_json(cache_key)
    if cached is not None:
        return cached

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

        await redis_set_json(cache_key, planos, 60)
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


# ── Distributed Leader Election ──────────────────────────────────────────────
# Garante que apenas UM processo (worker uvicorn) execute cada worker periódico.
# Sem isso, `uvicorn --workers 4` rodaria 4 instâncias de cada worker.
# Mecanismo: SET NX EX no Redis — quem grava a chave vira líder por `ttl` segundos.
# O líder renova a cada ciclo; os outros ficam dormindo e tentam novamente.

_WORKER_ID = str(uuid.uuid4())  # ID único deste processo

async def _is_worker_leader(nome: str, ttl: int) -> bool:
    """
    Tenta assumir a liderança para o worker `nome`.
    Retorna True se este processo é o líder (ou renovou a liderança).
    Retorna False se outro processo já é líder.
    ttl deve ser ligeiramente maior que o intervalo do worker.
    """
    chave = f"worker_leader:{nome}"
    # Tenta criar (NX = only if Not eXists)
    try:
        ganhou = await redis_client.set(chave, _WORKER_ID, nx=True, ex=ttl)
        if ganhou:
            return True
        # Verifica se JÁ é o líder atual (renovação)
        lider_atual = await redis_client.get(chave)
        if lider_atual == _WORKER_ID:
            await redis_client.expire(chave, ttl)  # renova TTL
            return True
        return False
    except asyncio.CancelledError:
        raise
    except redis.RedisError as e:
        if not is_shutting_down:
            logger.warning(f"⚠️ Falha ao verificar liderança do worker '{nome}': {e}")
        return False


async def worker_sync_planos():
    try:
        while True:
            if not db_pool:
                await asyncio.sleep(60)
                continue
            if not await _is_worker_leader("sync_planos", ttl=22000):
                logger.debug("⏭️ worker_sync_planos: não é líder, pulando ciclo")
                await asyncio.sleep(10)
                continue
            try:
                empresas = await db_pool.fetch("SELECT id FROM empresas")
                for emp in empresas:
                    await sincronizar_planos_evo(emp['id'])
                logger.info("✅ worker_sync_planos executado pelo líder")
            except Exception as e:
                logger.error(f"Erro no worker de sincronização de planos: {e}")
            await asyncio.sleep(21600)  # 6 horas
    except asyncio.CancelledError:
        logger.info("🛑 worker_sync_planos cancelado")
        raise


@app.get("/sync-planos/{empresa_id}")
async def sync_planos_manual(empresa_id: int):
    count = await sincronizar_planos_evo(empresa_id)
    await redis_client.delete(f"planos:ativos:{empresa_id}:todos")
    return {"status": "ok", "sincronizados": count}


# --- FUNÇÃO CENTRALIZADA DE ENVIO PARA O CHATWOOT ---

async def simular_digitacao(account_id: int, conversation_id: int, integracao: dict, segundos: float = 2.0, empresa_id: int = None):
    """
    Simula tempo de digitação humana e envia status de presença se for UAZAPI.
    """
    url_base = integracao.get('url') or integracao.get('base_url')
    token = extrair_token_chatwoot(integracao)
    
    # Detecta se é UazAPI (conforme lógica do enviar_mensagem_chatwoot)
    is_uazapi = "uazapi.com" in str(url_base).lower()
    uaz_integracao = integracao if is_uazapi else None
    
    if not is_uazapi and empresa_id:
        _uaz = await carregar_integracao(empresa_id, 'uazapi')
        if _uaz:
            uaz_integracao = _uaz
            is_uazapi = True

    if is_uazapi and uaz_integracao:
        try:
            _fone = await redis_client.get(f"fone_cliente:{conversation_id}")
            if not _fone and db_pool:
                _fone = await db_pool.fetchval(
                    "SELECT COALESCE(contato_fone, contato_telefone) FROM conversas WHERE conversation_id = $1",
                    conversation_id
                )
                if _fone:
                    await redis_client.setex(f"fone_cliente:{conversation_id}", 86400, str(_fone))
            if _fone:
                _fone_clean = "".join(filter(str.isdigit, str(_fone)))
                uaz_token = extrair_token_chatwoot(uaz_integracao)
                uaz_base = uaz_integracao.get('url') or uaz_integracao.get('base_url') or uaz_integracao.get('api_url')

                uaz_url = f"{str(uaz_base).rstrip('/')}/send/presence"
                uaz_payload = {
                    "number": _fone_clean,
                    "presence": "composing",
                    "delay": str(int(segundos * 1000))
                }
                uaz_headers = {"token": uaz_token, "Content-Type": "application/json"}
                await http_client.post(uaz_url, json=uaz_payload, headers=uaz_headers, timeout=5.0)
        except Exception as e:
            logger.error(f"⚠️ Erro ao simular digitação via UAZAPI: {e}")

    await asyncio.sleep(max(0.5, min(segundos, 6.0)))


def formatar_mensagem_saida(content: str) -> str:
    """Padroniza quebras de linha e espaços para mensagens mais legíveis."""
    txt = limpar_markdown(content or "")
    txt = txt.replace("\r\n", "\n").replace("\r", "\n")
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def suavizar_personalizacao_nome(content: str, nome: Optional[str]) -> str:
    """Evita vocativo artificial repetido e mantém menção natural ao nome."""
    txt = (content or "").strip()
    primeiro = primeiro_nome_cliente(nome)
    if not primeiro or not txt:
        return txt

    linhas = txt.split("\n")
    if linhas and re.fullmatch(rf"{re.escape(primeiro)}[,]?", linhas[0].strip(), flags=re.IGNORECASE):
        linhas = linhas[1:]
        while linhas and not linhas[0].strip():
            linhas = linhas[1:]
        txt = "\n".join(linhas).strip()

    inicio = txt[:120].lower()
    if primeiro.lower() not in inicio:
        txt = f"{primeiro}, {txt}"

    return txt.strip()


def extrair_token_chatwoot(integracao: dict) -> str:
    """Normaliza token da integração Chatwoot mesmo quando vier em formatos legados."""
    if not isinstance(integracao, dict):
        return ""
    token = integracao.get('token')
    if isinstance(token, dict):
        token = (
            token.get('api_access_token')
            or token.get('api_token')
            or token.get('access_token')
            or token.get('token')
        )
    if not token:
        token = (
            integracao.get('api_access_token')
            or integracao.get('api_token')
            or integracao.get('access_token')
        )
    return str(token).strip() if token else ""


async def atualizar_nome_contato_chatwoot(account_id: int, contact_id: int, nome: str, integracao: dict) -> bool:
    """Atualiza nome do contato no Chatwoot quando o nome válido é identificado."""
    if not contact_id or not nome_eh_valido(nome):
        return False
    url_base = integracao.get('url')
    token = extrair_token_chatwoot(integracao)
    if not url_base or not token:
        return False

    headers = {"api_access_token": token}
    payload = {"name": nome.strip()}
    url = f"{url_base}/api/v1/accounts/{account_id}/contacts/{contact_id}"
    try:
        resp = await http_client.put(url, json=payload, headers=headers, timeout=10.0)
        resp.raise_for_status()
        return True
    except Exception:
        try:
            resp = await http_client.patch(url, json=payload, headers=headers, timeout=10.0)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"Não foi possível atualizar nome do contato {contact_id} no Chatwoot: {e}")
            return False


def _label_unidade(slug: Optional[str]) -> Optional[str]:
    if not slug:
        return None
    base = re.sub(r"[^a-zA-Z0-9]+", "_", str(slug).strip().upper()).strip("_")
    return f"UNIDADE::{base}" if base else None


def _label_qualif(texto_cliente: str, novo_estado: str, intencao_compra: bool = False) -> str:
    txt = normalizar(texto_cliente or "")
    st = normalizar(novo_estado or "")

    if re.search(r"(ja sou aluno|já sou aluno|sou aluno|ja tenho cadastro|já tenho cadastro)", txt):
        return "QUALIF::ALUNO_EXISTENTE"
    if re.search(r"(nao tenho interesse|não tenho interesse|so queria saber|só queria saber|so pesquisando|só pesquisando)", txt):
        return "QUALIF::NAO_QUALIFICADO"

    if intencao_compra or any(k in st for k in ["conversao", "matricula"]):
        return "QUALIF::LEAD_QUENTE"
    if any(k in st for k in ["interessado", "animado", "hesitante"]) or re.search(r"(plano|planos|preco|preço|valor|matricul)", txt):
        return "QUALIF::LEAD_MORNO"
    return "QUALIF::LEAD_FRIO"


async def atualizar_labels_conversa_chatwoot(
    account_id: int,
    conversation_id: int,
    integracao: dict,
    slug: Optional[str],
    qualif_label: Optional[str],
):
    """Mescla labels da conversa sem sobrescrever labels não gerenciadas."""
    url_base = integracao.get('url')
    token = extrair_token_chatwoot(integracao)
    if not url_base or not token:
        return

    headers = {"api_access_token": token}
    conv_url = f"{url_base}/api/v1/accounts/{account_id}/conversations/{conversation_id}"

    atuais = []
    try:
        r_get = await http_client.get(conv_url, headers=headers, timeout=10.0)
        if r_get.status_code < 400:
            atuais = (r_get.json() or {}).get("labels") or []
    except Exception:
        atuais = []

    atuais_norm = [str(l).strip() for l in atuais if l]
    preservadas = [l for l in atuais_norm if not (l.startswith("QUALIF::") or l.startswith("UNIDADE::"))]

    novas = list(preservadas)
    if qualif_label:
        novas.append(qualif_label)
    lbl_unid = _label_unidade(slug)
    if lbl_unid:
        novas.append(lbl_unid)

    # dedupe preservando ordem
    finais = []
    seen = set()
    for l in novas:
        if l not in seen:
            seen.add(l)
            finais.append(l)

    payload = {"labels": finais}
    try:
        r = await http_client.put(conv_url, json=payload, headers=headers, timeout=10.0)
        if r.status_code >= 400:
            r = await http_client.patch(conv_url, json=payload, headers=headers, timeout=10.0)
            r.raise_for_status()
    except Exception as e:
        logger.warning(f"Falha ao atualizar labels da conversa {conversation_id}: {e}")


async def enviar_mensagem_chatwoot(
    account_id: int,
    conversation_id: int,
    content: str,
    nome_ia: str,
    integracao: dict,
    empresa_id: int = None,
    attachment_url: str = None
):
    url_base = integracao.get('url') or integracao.get('base_url')
    token = extrair_token_chatwoot(integracao)
    
    # Padroniza formatação
    content = formatar_mensagem_saida(content)

    # Personalização com nome
    try:
        _nome_salvo = await redis_client.get(f"nome_cliente:{conversation_id}")
    except Exception:
        _nome_salvo = None
    content = suavizar_personalizacao_nome(content, _nome_salvo)

    # Prepara payload base do Chatwoot antecipadamente
    payload = {
        "content": content if content else "",
        "message_type": "outgoing",
        "content_attributes": {
            "origin": "ai",
            "ai_agent": nome_ia,
            "ignore_webhook": True
        }
    }
    if attachment_url:
        payload["content_attributes"]["external_url"] = attachment_url

    # --- LÓGICA DE ENVIO DIRETO UAZAPI (Priority) ---
    # Detecta se é UazAPI — ou via URL ou carregando integração explícita
    is_uazapi = "uazapi.com" in str(url_base).lower()
    uaz_integracao = integracao if is_uazapi else None
    
    if not is_uazapi and empresa_id:
        # Se não é UazAPI na URL do Chatwoot, busca se a empresa tem uma integração UazAPI ativa
        _uaz = await carregar_integracao(empresa_id, 'uazapi')
        if _uaz:
            uaz_integracao = _uaz
            is_uazapi = True

    if is_uazapi and uaz_integracao:
        try:
            _fone = await redis_client.get(f"fone_cliente:{conversation_id}")
            if not _fone and db_pool:
                _fone = await db_pool.fetchval(
                    "SELECT COALESCE(contato_fone, contato_telefone) FROM conversas WHERE conversation_id = $1",
                    conversation_id
                )
                if _fone:
                    await redis_client.setex(f"fone_cliente:{conversation_id}", 86400, str(_fone))
            if _fone:
                _fone_clean = "".join(filter(str.isdigit, str(_fone)))
                uaz_token = extrair_token_chatwoot(uaz_integracao)
                uaz_base = uaz_integracao.get('url') or uaz_integracao.get('base_url') or uaz_integracao.get('api_url')

                # Cabeçalho sem emoticons
                _header = f"*{nome_ia}*\n" if nome_ia else ""

                if attachment_url:
                    uaz_url = f"{str(uaz_base).rstrip('/')}/send/media"
                    # Detecta tipo de mídia pela extensão da URL
                    _url_lower = attachment_url.lower().split('?')[0]
                    if any(_url_lower.endswith(ext) for ext in ('.mp4', '.mov', '.avi', '.mkv', '.webm')):
                        _media_type = "video"
                    elif any(_url_lower.endswith(ext) for ext in ('.mp3', '.wav', '.ogg', '.aac')):
                        _media_type = "audio"
                    else:
                        _media_type = "image"
                    uaz_payload = {
                        "number": _fone_clean,
                        "type": _media_type,
                        "file": attachment_url,
                        "caption": f"{_header}{content}" if (content or _header) else ""
                    }
                else:
                    uaz_url = f"{str(uaz_base).rstrip('/')}/send/text"
                    uaz_payload = {
                        "number": _fone_clean,
                        "text": f"{_header}{content}",
                        "delay": "1000"
                    }

                uaz_headers = {"token": uaz_token, "Content-Type": "application/json", "Accept": "application/json"}
                logger.info(f"🚀 [UAZAPI-DIRETO] Enviando para {_fone_clean} (Media={bool(attachment_url)}) url={uaz_url} token_len={len(uaz_token)} token_prefix={uaz_token[:8] if uaz_token else 'VAZIO'}...")
                uaz_resp = await http_client.post(uaz_url, json=uaz_payload, headers=uaz_headers, timeout=20.0)
                uaz_resp.raise_for_status()

                # Registra que enviamos direto para evitar eco no webhook.
                # Seta DUAS chaves: formato conv_id (Chatwoot webhook) + empresa:phone (UazAPI webhook)
                _echo_ttl = 120 if attachment_url else 60
                await redis_client.setex(f"uaz_bot_sent:{conversation_id}", _echo_ttl, "1")
                if empresa_id and _fone_clean:
                    await redis_client.setex(f"uaz_bot_sent:{empresa_id}:{_fone_clean}", _echo_ttl, "1")

                # UazAPI enviou com sucesso — retorna sem sync Chatwoot para evitar duplicação
                logger.info(f"✅ [UAZAPI-DIRETO] Enviado com sucesso para {_fone_clean}")
                return uaz_resp

        except Exception as e:
            logger.error(f"❌ Falha no UAZAPI DIRETO (Fallback p/ Chatwoot): {e}")

    # --- FLUXO CHATWOOT CLÁSSICO (Sync de Histórico) ---
    if not url_base or not token:
        logger.error("Integração Chatwoot incompleta para envio")
        return None

    url_m = f"{str(url_base).rstrip('/')}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    headers = {"api_access_token": str(token)}
    
    try:
        resp = await http_client.post(url_m, json=payload, headers=headers, timeout=20.0)
        resp.raise_for_status()
        
        # Armazena o ID da mensagem enviada no Redis para identificação no webhook
        try:
            msg_data = resp.json()
            if msg_data and "id" in msg_data:
                await redis_client.setex(f"ai_msg_id:{msg_data['id']}", 600, "1")
        except Exception:
            pass

        logger.info(f"📤 Mensagem sincronizada via Chatwoot (tipo={payload['message_type']})")
        return resp
    except Exception as e:
        logger.error(f"❌ Erro final ao enviar mensagem: {e}")
        return None
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
                    (SELECT id FROM conversas WHERE conversation_id = $1 AND empresa_id = $2),
                    $2,
                    (SELECT id FROM unidades WHERE slug = $3 AND empresa_id = $2),
                    $4, $5, $6, $7, $8, 'pendente'
                )
            """, conversation_id, empresa_id, slug, t["id"], t["tipo"], t["mensagem"], t["ordem"], agendado_para)

        logger.info(f"📅 {len(templates)} follow-ups agendados para conversa {conversation_id}")
    except Exception as e:
        logger.error(f"Erro ao agendar followups: {e}")


async def worker_followup():
    try:
        while True:
            await asyncio.sleep(30)
            # Garante que apenas 1 worker processe follow-ups em ambiente multi-processo
            if not await _is_worker_leader("followup", ttl=40):
                continue
            if not db_pool:
                continue
            try:
                agora = datetime.now(ZoneInfo("America/Sao_Paulo")).replace(tzinfo=None)

                pendentes = await db_pool.fetch("""
                    SELECT f.*, c.conversation_id, c.account_id, u.slug, c.empresa_id,
                           u.nome AS nome_unidade, c.contato_nome
                    FROM followups f
                    JOIN conversas c ON c.id = f.conversa_id
                    LEFT JOIN unidades u ON u.id = f.unidade_id
                    WHERE f.status = 'pendente' AND f.agendado_para <= $1
                    ORDER BY f.agendado_para
                    LIMIT 20
                    FOR UPDATE OF f SKIP LOCKED
                """, agora)

                for f in pendentes:
                    if (
                        await redis_client.get(f"atend_manual:{f['empresa_id']}:{f['conversation_id']}") == "1"
                        or await redis_client.get(f"pause_ia:{f['empresa_id']}:{f['conversation_id']}") == "1"
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

                    # Carrega nome_ia da personalidade (evita "Assistente Virtual" hardcoded)
                    _pers_fu = await carregar_personalidade(f['empresa_id']) or {}
                    _nome_ia_fu = _pers_fu.get('nome_ia') or 'Atendente'

                    nome_contato = (f['contato_nome'] or '').split()[0] if f['contato_nome'] else 'você'
                    nome_unidade = (f['nome_unidade'] or '').strip()
                    if not nome_unidade and f.get('slug'):
                        nome_unidade = str(f['slug']).replace('-', ' ').replace('_', ' ').title()
                    mensagem_followup = _render_followup_template(f['mensagem'] or '', nome_contato, nome_unidade)

                    await enviar_mensagem_chatwoot(
                        f['account_id'], f['conversation_id'], mensagem_followup, _nome_ia_fu, integracao, f['empresa_id']
                    )
                    await db_pool.execute(
                        "UPDATE followups SET status = 'enviado', enviado_em = NOW() WHERE id = $1", f['id']
                    )

            except Exception as e:
                logger.error(f"Erro no worker de follow-up: {e}")
    except asyncio.CancelledError:
        logger.info("🛑 worker_followup cancelado")
        raise

async def worker_cleanup_followups():
    """
    Worker que remove follow-ups com status 'cancelado' a cada 20 minutos.
    Evita que o banco de dados e a interface fiquem poluídos.
    """
    try:
        while True:
            await asyncio.sleep(1200) # 20 minutos
            if not db_pool:
                continue
            
            # Leader election para garantir que apenas um processo execute a limpeza
            if not await _is_worker_leader("cleanup_followups", ttl=1300):
                continue

            try:
                # Remove apenas os cancelados (conforme solicitado pelo usuário)
                res = await db_pool.execute(
                    "DELETE FROM followups WHERE status = 'cancelado'"
                )
                if res != "DELETE 0":
                    logger.info(f"♻️ worker_cleanup_followups: {res} removidos")
            except Exception as e:
                logger.error(f"Erro no worker de limpeza de follow-ups: {e}")
    except asyncio.CancelledError:
        logger.info("🛑 worker_cleanup_followups cancelado")
        raise


async def monitorar_escolha_unidade(account_id: int, conversation_id: int, empresa_id: int):
    await asyncio.sleep(120)
    if not await redis_client.exists(f"esperando_unidade:{conversation_id}"):
        return
    if await redis_client.exists(f"unidade_escolhida:{conversation_id}"):
        return

    integracao = await carregar_integracao(empresa_id, 'chatwoot')
    if not integracao:
        return

    _pers_mon = await carregar_personalidade(empresa_id) or {}
    _nome_ia_mon = _pers_mon.get('nome_ia') or 'Atendente'

    # Lembrete amigável — pergunta de novo sem listar todas as unidades
    await enviar_mensagem_chatwoot(
        account_id, conversation_id,
        "Só pra eu não te perder de vista 😊\n\nQual cidade ou bairro você prefere para treinar?",
        _nome_ia_mon, integracao, empresa_id
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
    cache = await redis_get_json(cache_key)
    if cache is not None:
        return cache

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
                CASE WHEN u.numero IS NOT NULL AND TRIM(u.numero) <> ''
                    THEN u.endereco || ', ' || u.numero
                    ELSE u.endereco
                END as endereco_completo,
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
        await redis_set_json(cache_key, data, 60)
        return data
    except asyncpg.PostgresError as e:
        logger.error(f"Erro PostgreSQL ao listar unidades para empresa {empresa_id}: {e}")
        if _PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="db_unidades_lista").inc()
        return []
    except Exception as e:
        logger.error(f"Erro inesperado ao listar unidades: {e}")
        return []


async def buscar_unidade_na_pergunta(texto: str, empresa_id: int, fuzzy_threshold: int = 85) -> Optional[str]:
    """
    Tenta identificar uma unidade mencionada na pergunta do cliente.
    Estratégia em 4 camadas:
      1. Função SQL customizada (se existir)
      2. Correspondência exata/parcial em nome, cidade, bairro e palavras-chave
      3. Correspondência por partes (tokens) — suporta nomes compostos e abreviações
      4. Fuzzy matching conservador (threshold ajustável)
    """
    if not db_pool or not texto:
        return None

    # Normalização agressiva para busca
    texto_bruto = texto.lower()
    texto_norm = normalizar(texto)
    tokens_texto = set(texto_norm.split())

    # 1. Função SQL customizada (mais precisa, se disponível no banco)
    try:
        query = "SELECT unidade_slug FROM buscar_unidades_por_texto($1, $2) LIMIT 1"
        row = await db_pool.fetchrow(query, empresa_id, texto)
        if row:
            return row['unidade_slug']
    except asyncpg.UndefinedFunctionError:
        pass
    except asyncpg.PostgresError as e:
        logger.error(f"Erro SQL ao buscar unidade: {e}")

    # 2. Busca por palavras-chave, nome, cidade e bairro
    unidades = await listar_unidades_ativas(empresa_id)
    

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

        # Matching por tokens
        tokens_nome    = set(nome_norm.split())
        tokens_cidade  = set(cidade_norm.split()) if cidade_norm else set()
        tokens_bairro  = set(bairro_norm.split()) if bairro_norm else set()

        _sig = lambda ts: {t for t in ts if len(t) >= 4}

        _match_nome = _sig(tokens_texto) & _sig(tokens_nome)
        if len(_match_nome) >= 2:
            return u['slug']
        
        if len(_match_nome) == 1 and all(len(t) >= 6 for t in _match_nome):
            return u['slug']

        if _sig(tokens_texto) & _sig(tokens_cidade):
            return u['slug']
        if _sig(tokens_texto) & _sig(tokens_bairro):
            return u['slug']

    # 3. Fuzzy matching conservador
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

    if maior_score >= fuzzy_threshold:
        return melhor_slug

    return None


async def carregar_unidade(slug: str, empresa_id: int) -> Dict[str, Any]:
    if not db_pool:
        return {}

    cache_key = f"cfg:unidade:{empresa_id}:{slug}:v2"
    cache = await redis_get_json(cache_key)
    if cache is not None:
        return cache

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
            await redis_set_json(cache_key, dados, 60)
            return dados
        return {}
    except Exception as e:
        logger.error(f"Erro ao carregar unidade {slug}: {e}")
        return {}


async def buscar_resposta_faq(pergunta: str, slug: str, empresa_id: int) -> Optional[str]:
    """
    Tenta encontrar uma resposta direta no FAQ sem precisar chamar a IA.
    Usa sobreposição de tokens (palavras significativas) entre a pergunta do
    cliente e as perguntas cadastradas no FAQ.
    Retorna a resposta do FAQ se similaridade >= threshold, senão None.
    """
    if not db_pool or not slug or not pergunta:
        return None

    cache_key = f"cfg:faq_raw:v2:{empresa_id}:{slug}"
    raw = await redis_client.get(cache_key)
    if raw:
        try:
            faq_rows = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            faq_rows = []
    else:
        try:
            faq_rows_db = await db_pool.fetch("""
                WITH unidade AS (
                    SELECT id
                    FROM unidades
                    WHERE slug = $1 AND empresa_id = $2
                    LIMIT 1
                )
                SELECT f.pergunta, f.resposta
                FROM faq f
                LEFT JOIN unidade u ON true
                WHERE f.empresa_id = $2
                  AND f.ativo = true
                  AND (
                      f.todas_unidades = true
                      OR (u.id IS NOT NULL AND f.unidade_id = u.id)
                      OR (u.id IS NOT NULL AND u.id = ANY(COALESCE(f.unidades_ids, '{}'::int[])))
                  )
                ORDER BY f.prioridade DESC NULLS LAST
                LIMIT 50
            """, slug, empresa_id)
            faq_rows = [{"pergunta": r["pergunta"], "resposta": r["resposta"]} for r in faq_rows_db]
            await redis_client.setex(cache_key, 300, json.dumps(faq_rows, ensure_ascii=False))
        except Exception:
            return None

    if not faq_rows:
        return None

    # Tokeniza a pergunta do cliente (palavras com >= 3 chars)
    pergunta_norm = normalizar(pergunta)
    tokens_cliente = {t for t in pergunta_norm.split() if len(t) >= 3}
    if not tokens_cliente:
        return None

    intencao_cliente = classificar_intencao(pergunta)

    melhor_score = 0.0
    melhor_resposta = None

    for item in faq_rows:
        if not _faq_compativel_com_intencao(intencao_cliente, item.get("pergunta", "")):
            continue
        tokens_faq = {t for t in normalizar(item["pergunta"]).split() if len(t) >= 3}
        if not tokens_faq:
            continue
        # Jaccard: intersecção / união
        intersecao = tokens_cliente & tokens_faq
        uniao = tokens_cliente | tokens_faq
        score = len(intersecao) / len(uniao) if uniao else 0.0
        if score > melhor_score:
            melhor_score = score
            melhor_resposta = item["resposta"]

    # Threshold dinâmico: intents factuais exigem match mais forte para evitar respostas erradas.
    threshold = 0.55 if intencao_cliente in {"modalidades", "planos", "horario", "endereco"} else 0.40
    if melhor_score >= threshold and melhor_resposta:
        logger.info(f"✅ FAQ fast-match (score={melhor_score:.2f}): '{pergunta[:50]}' → FAQ direto")
        return melhor_resposta.strip()

    return None


async def carregar_faq_unidade(slug: str, empresa_id: int) -> str:
    """
    Carrega as perguntas frequentes da unidade e retorna formatadas para o prompt da IA.
    Tenta duas queries: com prioridade+visualizacoes, e fallback sem visualizacoes
    (caso a coluna ainda não exista no banco).
    Loga aviso quando FAQ está vazio para facilitar diagnóstico.
    """
    if not db_pool:
        return ""

    cache_key = f"cfg:faq:{empresa_id}:{slug}:v4"
    cache = await redis_client.get(cache_key)
    if cache:
        return cache

    rows = []
    try:
        # Query principal — unidade específica, múltiplas unidades ou todas
        rows = await db_pool.fetch("""
            WITH unidade AS (
                SELECT id
                FROM unidades
                WHERE slug = $1 AND empresa_id = $2
                LIMIT 1
            )
            SELECT f.pergunta, f.resposta
            FROM faq f
            LEFT JOIN unidade u ON true
            WHERE f.empresa_id = $2
              AND f.ativo = true
              AND (
                  f.todas_unidades = true
                  OR (u.id IS NOT NULL AND f.unidade_id = u.id)
                  OR (u.id IS NOT NULL AND u.id = ANY(COALESCE(f.unidades_ids, '{}'::int[])))
              )
            ORDER BY f.prioridade DESC NULLS LAST, f.visualizacoes DESC NULLS LAST
            LIMIT 30
        """, slug, empresa_id)
    except asyncpg.UndefinedColumnError:
        # Fallback: sem a coluna visualizacoes
        try:
            rows = await db_pool.fetch("""
                WITH unidade AS (
                    SELECT id
                    FROM unidades
                    WHERE slug = $1 AND empresa_id = $2
                    LIMIT 1
                )
                SELECT f.pergunta, f.resposta
                FROM faq f
                LEFT JOIN unidade u ON true
                WHERE f.empresa_id = $2
                  AND f.ativo = true
                  AND (
                      f.todas_unidades = true
                      OR (u.id IS NOT NULL AND f.unidade_id = u.id)
                      OR (u.id IS NOT NULL AND u.id = ANY(COALESCE(f.unidades_ids, '{}'::int[])))
                  )
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
    dados_cache = await redis_get_json(cache_key)
    if dados_cache is not None:
        if dados_cache.get('ativo') is True:
            return dados_cache
        else:
            await redis_client.delete(cache_key)

    try:
        query = """
            SELECT p.*, fn_ia_esta_no_horario_v2(p.horario_atendimento_ia) AS esta_no_horario
            FROM personalidade_ia p
            WHERE p.empresa_id = $1 AND p.ativo = true
            ORDER BY p.updated_at DESC
            LIMIT 1
        """
        row = await db_pool.fetchrow(query, empresa_id)
        if row:
            dados = dict(row)
            for key, value in dados.items():
                if isinstance(value, Decimal):
                    dados[key] = float(value)
            await redis_set_json(cache_key, dados, 300)
            return dados
        else:
            await redis_set_json(cache_key, {}, 60)
            return {}
    except Exception as e:
        logger.error(f"Erro ao carregar personalidade da empresa {empresa_id}: {e}")
        return {}


async def carregar_configuracao_global(empresa_id: int) -> Dict[str, Any]:
    if not db_pool:
        return {}

    cache_key = f"cfg:global:empresa:{empresa_id}"
    cache = await redis_get_json(cache_key)
    if cache is not None:
        return cache

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
    contato_id: int = None, contato_nome: str = None, empresa_id: int = None,
    contato_telefone: str = None
):
    if not db_pool:
        return
    try:
        unidade_id = None
        if slug and slug != "uazapi":
            unidade = await db_pool.fetchrow(
                "SELECT id FROM unidades WHERE slug = $1 AND empresa_id = $2", slug, empresa_id
            )
            if unidade:
                unidade_id = unidade['id']
            else:
                logger.warning(f"Unidade {slug} não encontrada para empresa {empresa_id}. Prosseguindo sem unidade_id.")
        # Compatível com bancos sem constraint UNIQUE em conversation_id.
        # 1) tenta atualizar registro existente da mesma conta/conversa
        _updated = await db_pool.execute("""
            UPDATE conversas
               SET contato_id       = COALESCE($3, contato_id),
                   contato_nome     = $4,
                   unidade_id       = $5,
                   contato_telefone = COALESCE($7, contato_telefone),
                   status           = 'ativa',
                   updated_at       = NOW()
             WHERE conversation_id = $1
               AND account_id      = $2
               AND empresa_id      = $6
        """, conversation_id, account_id, contato_id, contato_nome, unidade_id, empresa_id, contato_telefone)

        # 2) se não atualizou nenhuma linha, insere nova conversa
        if str(_updated).endswith(" 0"):
            await db_pool.execute("""
                INSERT INTO conversas (
                    conversation_id, account_id, contato_id, contato_nome,
                    empresa_id, unidade_id, primeira_mensagem, status, contato_telefone
                )
                VALUES ($1, $2, $3, $4, $5, $6, NOW(), 'ativa', $7)
            """, conversation_id, account_id, contato_id, contato_nome, empresa_id, unidade_id, contato_telefone)
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


async def bd_obter_historico_local(conversation_id: int, limit: int = 12) -> Optional[str]:
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
        SELECT COUNT(DISTINCT contato_telefone) FROM conversas
        WHERE empresa_id = $1 AND unidade_id = $2
          AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
          AND NOT EXISTS (
              SELECT 1 FROM conversas c2
              WHERE c2.empresa_id = $1
                AND c2.contato_telefone = conversas.contato_telefone
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
    try:
        while True:
            await asyncio.sleep(3600)
            if not db_pool:
                continue
            if not await _is_worker_leader("metricas_diarias", ttl=3700):
                logger.debug("⏭️ worker_metricas_diarias: não é líder, pulando ciclo")
                continue
            try:
                hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
                empresas = await db_pool.fetch("SELECT id FROM empresas WHERE status = 'active'")

                total_unidades = 0
                for emp in empresas:
                    empresa_id = emp['id']
                    unidades = await db_pool.fetch(
                        "SELECT id FROM unidades WHERE empresa_id = $1 AND ativa = true",
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
    except asyncio.CancelledError:
        logger.info("🛑 worker_metricas_diarias cancelado")
        raise


async def worker_resumo_ia():
    """
    Worker que gera o Resumo Neural para conversas que ainda não têm resumo_ia.
    Roda a cada 10 min, processa até 10 conversas por ciclo usando o modelo
    mais econômico disponível no OpenRouter.
    """
    _RESUMO_MODEL = "google/gemini-2.0-flash-lite-001"
    _RESUMO_BATCH = 10
    _RESUMO_INTERVAL = 600

    try:
        while True:
            await asyncio.sleep(_RESUMO_INTERVAL)
            if not db_pool or not cliente_ia:
                continue
            if not await _is_worker_leader("resumo_ia", ttl=_RESUMO_INTERVAL + 60):
                continue
            try:
                pendentes = await db_pool.fetch("""
                    SELECT c.id, c.conversation_id, c.empresa_id, c.contato_nome
                    FROM conversas c
                    WHERE c.resumo_ia IS NULL
                      AND c.updated_at >= NOW() - INTERVAL '48 hours'
                      AND (
                          SELECT COUNT(*) FROM mensagens m
                          WHERE m.conversa_id = c.id AND m.role = 'user'
                      ) >= 3
                    ORDER BY c.updated_at DESC
                    LIMIT $1
                """, _RESUMO_BATCH)

                for conv in pendentes:
                    try:
                        msgs = await db_pool.fetch("""
                            SELECT role, conteudo as content FROM mensagens
                            WHERE conversa_id = $1
                            ORDER BY created_at ASC
                            LIMIT 40
                        """, conv['id'])

                        if not msgs:
                            continue

                        historico = "\n".join(
                            f"{'Lead' if m['role'] == 'user' else 'IA'}: {(m['content'] or '').strip()}"
                            for m in msgs
                        )

                        prompt = (
                            "Analise a conversa abaixo entre um lead e uma IA de vendas de academia. "
                            "Responda em português com no máximo 3 frases cobrindo: "
                            "1) o que o lead quer, 2) nível de interesse (quente/morno/frio), "
                            "3) próximo passo sugerido. Seja direto e objetivo.\n\n"
                            f"Conversa:\n{historico}"
                        )

                        resp = await cliente_ia.chat.completions.create(
                            model=_RESUMO_MODEL,
                            messages=[{"role": "user", "content": prompt}],
                            max_tokens=200,
                            temperature=0.3,
                        )
                        resumo = resp.choices[0].message.content.strip()
                        
                        from src.services.db_queries import bd_salvar_resumo_ia
                        await bd_salvar_resumo_ia(conv['conversation_id'], conv['empresa_id'], resumo)
                        logger.info(f"Resumo Neural gerado para conversa {conv['conversation_id']}")
                    except Exception as e:
                        logger.error(f"Erro ao gerar resumo para conversa {conv['conversation_id']}: {e}")
            except Exception as e:
                logger.error(f"Erro no worker_resumo_ia: {e}")
    except asyncio.CancelledError:
        logger.info("🛑 worker_resumo_ia cancelado")
        raise

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


@retry(
    wait=wait_exponential(multiplier=0.5, min=1, max=4),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError)),
    reraise=True,
)
async def baixar_midia_com_retry(url: str, timeout: float = 15.0, headers: Optional[Dict[str, str]] = None) -> httpx.Response:
    """Baixa mídia com retry para mitigar falhas transitórias de rede/provedor."""
    resp = await http_client.get(
        url,
        headers=headers,
        follow_redirects=True,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp


def get_tenant_key(empresa_id: int, suffix: str) -> str:
    """Gera uma chave de cache prefixada pelo ID da empresa para multi-tenancy."""
    return f"tenant:{empresa_id}:{suffix}"

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
    integracao_chatwoot: dict
):
    chave_lock = f"lock:{conversation_id}"
    chave_buffet = f"buffet:{conversation_id}"
    watchdog = asyncio.create_task(renovar_lock(chave_lock, lock_val))

    try:
        # ⏱️ Aguarda período para acumular rajada de mensagens (WhatsApp = msgs curtas em sequência)
        # Janela de 4s: captura rajadas típicas de WhatsApp (2-4 msgs em sequência)
        await asyncio.sleep(4.0)

        # --- NOVIDADE: Fluxo Visual de Triagem (n8n-style) ---
        # Se houver um fluxo ativo para a empresa, ele assume o controle ANTES da IA.
        _fluxo_config = await carregar_fluxo_triagem(empresa_id)
        if _fluxo_config and _fluxo_config.get("ativo"):
            # Recupera o telefone do Redis (armazenado pelo webhook)
            _fone_redis = await redis_client.get(f"fone_cliente:{conversation_id}")
            if _fone_redis:
                # Verifica se a IA está pausada para esta conversa
                _ia_pausada = bool(await redis_client.exists(f"pause_ia:{empresa_id}:{conversation_id}"))
                _phone_paused = bool(await redis_client.exists(f"pause_ia_phone:{empresa_id}:{_fone_redis}"))
                
                if not _ia_pausada and not _phone_paused:
                    # Carrega integração para envio
                    _integr_uaz = await carregar_integracao(empresa_id, 'uazapi')
                    if _integr_uaz:
                        _uaz_fluxo_cli = UazAPIClient(
                            base_url=_integr_uaz.get("url", ""),
                            token=_integr_uaz.get("token", ""),
                            instance_name=_integr_uaz.get("instance", "default")
                        )
                        # Pega a última mensagem do buffer para o fluxo
                        _mensagens_pool = await coletar_mensagens_buffer(conversation_id)
                        if _mensagens_pool:
                            _ultima_msg = _mensagens_pool[-1]
                            _tratou = await executar_fluxo(empresa_id, _fone_redis, _ultima_msg, _fluxo_config, _uaz_fluxo_cli)
                            if _tratou:
                                logger.info(f"✅ [FluxoTriagem Monolith] Mensagem tratada pelo fluxo visual para {_fone_redis}")
                                # Se tratou, libera o lock e encerra para evitar que a IA responda
                                try:
                                    await redis_client.eval(LUA_RELEASE_LOCK, 1, chave_lock, lock_val)
                                except Exception: pass
                                return True

        # --- FIM Fluxo Visual ---

        # --- NOVIDADE: Fluxo Visual de Triagem (n8n-style) ---
        # Se houver um fluxo ativo para a empresa, ele assume o controle ANTES da IA.
        _fluxo_config = await carregar_fluxo_triagem(empresa_id)
        if _fluxo_config and _fluxo_config.get("ativo"):
            # Recupera o telefone do Redis (armazenado pelo webhook)
            _fone_redis = await redis_client.get(f"fone_cliente:{conversation_id}")
            if _fone_redis:
                # Verifica se a IA está pausada para esta conversa
                _ia_pausada = bool(await redis_client.exists(f"pause_ia:{empresa_id}:{conversation_id}"))
                _phone_paused = bool(await redis_client.exists(f"pause_ia_phone:{empresa_id}:{_fone_redis}"))
                
                if not _ia_pausada and not _phone_paused:
                    # Carrega integração para envio
                    _integr_uaz = await carregar_integracao(empresa_id, 'uazapi')
                    if _integr_uaz:
                        _uaz_fluxo_cli = UazAPIClient(
                            base_url=_integr_uaz.get("url", ""),
                            token=_integr_uaz.get("token", ""),
                            instance_name=_integr_uaz.get("instance", "default")
                        )
                        # Pega a última mensagem do buffer para o fluxo
                        _mensagens_pool = await coletar_mensagens_buffer(conversation_id)
                        if _mensagens_pool:
                            _ultima_msg = _mensagens_pool[-1]
                            _tratou = await executar_fluxo(empresa_id, _fone_redis, _ultima_msg, _fluxo_config, _uaz_fluxo_cli)
                            if _tratou:
                                logger.info(f"✅ [FluxoTriagem Monolith] Mensagem tratada pelo fluxo visual para {_fone_redis}")
                                # Se tratou, libera o lock e encerra para evitar que a IA responda
                                try:
                                    await redis_client.eval(LUA_RELEASE_LOCK, 1, chave_lock, lock_val)
                                except Exception: pass
                                return True

        # --- FIM Fluxo Visual ---

        mensagens_acumuladas = await coletar_mensagens_buffer(conversation_id)
        if not mensagens_acumuladas:
            return

        # Verifica horário de atendimento da IA via Banco de Dados
        _pers_horario = await carregar_personalidade(empresa_id) or {}
        _db_esta_no_horario = _pers_horario.get("esta_no_horario", True)
        _horario_config = _pers_horario.get("horario_atendimento_ia")

        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        _agora_sp = _dt.now(_ZI("America/Sao_Paulo"))
        logger.info(
            f"🕒 [Bot Core Monolith] Horário SP={_agora_sp.strftime('%Y-%m-%d %H:%M:%S %Z')} | "
            f"DB_Check={_db_esta_no_horario} | Config: {_horario_config}"
        )

        if not _db_esta_no_horario:
            logger.info(f"⏰ IA fora do horário de atendimento para empresa {empresa_id}; conv {conversation_id} ignorada (silencioso)")
            return

        anexos = await processar_anexos_mensagens(mensagens_acumuladas)
        textos = anexos["textos"]
        transcricoes = anexos["transcricoes"]
        imagens_urls = anexos["imagens_urls"]
        mensagens_formatadas = anexos["mensagens_formatadas"]

        # Bypass 'waiting for unit' if user is asking for price, hours, etc.
        _texto_unificado_p = " ".join([t for t in (textos + transcricoes) if t]).lower()
        _bypass_pause = any(x in _texto_unificado_p for x in ["preço", "preco", "valor", "grade", "horario", "horário", "endereço", "endereco", "unidades", "grade de aula"])

        if not _bypass_pause and await aguardar_escolha_unidade_ou_reencaminhar(conversation_id, mensagens_acumuladas):
            return

        # ── Anti-duplicata: bloqueia reprocessamento do mesmo conteúdo ──────────
        # O drain loop pode recolocar mensagens no buffer após o processamento.
        # Se o hash das mensagens atuais é igual ao que foi respondido nos últimos
        # 2 minutos, descarta silenciosamente — a resposta já foi enviada.
        _hash_msgs = hashlib.md5(mensagens_formatadas.encode()).hexdigest()
        _ultima_resp_key = f"last_ai_msg:{conversation_id}"
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

        await persistir_mensagens_usuario(conversation_id, textos, transcricoes)

        unidade = await carregar_unidade(slug, empresa_id) or {}
        pers = await carregar_personalidade(empresa_id) or {}
        nome_ia = pers.get('nome_ia') or 'Atendente'
        nome_unidade = unidade.get('nome') or 'Unidade Matriz'

        estado_raw = await redis_client.get(f"estado:{conversation_id}")
        estado_atual = descomprimir_texto(estado_raw) or "neutro"

        texto_norm_fast = normalizar(primeira_mensagem or "")
        resposta_texto = ""
        novo_estado = estado_atual
        fast_reply = None          # str  — mensagem única (resposta fixa, sem LLM)
        fast_reply_lista = None   # List[str] — múltiplas mensagens (ex: planos)
        contexto_precarregado = ""  # Dados buscados do BD — LLM gera a resposta humanizada
        intencao_motor = None

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
            if _quer_todos_planos or len(_planos_filtrados) != len(planos_ativos):
                fast_reply_lista = formatar_planos_bonito(_planos_filtrados, destacar_melhor_preco=True)
                logger.info("⚡ Planos: envio em blocos com filtro por contexto e destaque de melhor preço")
            elif re.search(r"(quero saber dos planos|quais planos|planos)" , _texto_cliente_norm):
                fast_reply_lista = formatar_planos_bonito(planos_ativos, destacar_melhor_preco=True)
                logger.info("⚡ Planos: envio completo em blocos para pedido genérico")

        _intencoes_cacheaveis = {
            "horario", "endereco"
        }
        _usa_cache_por_intencao = bool(intencao and intencao in _intencoes_cacheaveis)

        if _usa_cache_por_intencao:
            chave_cache_ia = f"cache:intent:{slug}:{intencao}"
        else:
            hash_pergunta = hashlib.md5(texto_norm_fast.encode('utf-8')).hexdigest()
            chave_cache_ia = f"cache:ia:{slug}:{hash_pergunta}"

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
            _cache_sem = await buscar_cache_semantico(primeira_mensagem, slug)

        # Bypass cache se cliente pede tour/vídeo e a unidade tem tour disponível
        _pede_tour = any(k in normalizar(primeira_mensagem or "") for k in ("tour", "video", "ver por dentro", "mostrar a academia", "conhecer a unidade"))
        _tem_tour = bool(unidade.get("link_tour_virtual"))
        if _pede_tour and _tem_tour:
            resposta_cacheada = None

        prompt_sistema = None  # Inicializa para o drain (definido no fluxo IA)

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
            historico = await bd_obter_historico_local(conversation_id, limit=12) or "Sem histórico."

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
Horários:
{horarios_str}
Link de Matrícula / LP: {unidade.get('link_matricula') or 'não disponível'}
Planos (com links de matricula):
{planos_detalhados}
Site: {unidade.get('site') or 'não informado'}
Instagram: {unidade.get('instagram') or 'não informado'}
Modalidades: {modalidades_prompt}
Infraestrutura: {json.dumps(unidade.get('infraestrutura', {}), ensure_ascii=False) if unidade.get('infraestrutura') else 'não informado'}
Pagamentos: {pagamentos_prompt}
Convênios: {convenios_prompt}
Tour Virtual: {'vídeo disponível' if unidade.get('link_tour_virtual') else 'não disponível'}
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
                # Campos puramente visuais — não entram no prompt
                'emoji_cor', 'model_name', 'temperature', 'max_tokens',
                'usar_emoji', 'horario_atendimento_ia', 'menu_triagem',
                # Tour — consumidos programaticamente, não injetados como texto
                'estrategia_tour', 'oferecer_tour', 'tour_perguntar_primeira_visita',
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
                # Emojis rotativos — a IA deve alternar entre eles nas respostas
                'emoji_tipo':          'EMOJIS ROTATIVOS (alterne entre eles nas respostas)',
                'tour_mensagem_custom':'MENSAGEM CUSTOMIZADA PARA TOUR VIRTUAL (use como referência ao oferecer o tour)',
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
Você é um atendente — apenas responda o cliente diretamente.

Seu nome é {nome_ia}. Você é atendente da academia {nome_empresa}.
"""
            if slug:
                prompt_sistema += f"Você está atendendo agora pela unidade: {nome_unidade}.\n"
                prompt_sistema += "Se o cliente perguntar sobre OUTRA unidade da rede, responda normalmente usando as informações que você tem. Não diga que 'não pode' falar de outra unidade.\n"
            else:
                prompt_sistema += "Você é um consultor global da marca Red Fitness. Você atende todas as unidades da rede. Quando o cliente não especificar uma unidade, pergunte qual das nossas unidades ele gostaria de conhecer.\n"

            _foto_grade = unidade.get("foto_grade")
            _modalidades_texto = unidade.get("modalidades") or ""
            if _foto_grade or _modalidades_texto:
                prompt_sistema += "\n[GRADE DE AULAS & MODALIDADES — REGRAS]\n"
                if _modalidades_texto:
                    prompt_sistema += "Você TEM acesso ao conteúdo textual completo das modalidades e grade de aulas desta unidade. Os dados estão no campo 'Modalidades' nos DADOS DA UNIDADE.\n"
                    prompt_sistema += "REGRA PRIORITÁRIA: Sempre responda sobre aulas, modalidades, horários de aulas e grade usando o TEXTO que você já possui. Explique verbalmente.\n"
                    prompt_sistema += "Se o cliente perguntar sobre uma modalidade específica (ex: fit dance, pilates, yoga), busque nos dados textuais e responda com as informações que tem.\n"
                    prompt_sistema += "Se o cliente não consegue ler, tem dificuldade visual, ou pediu por áudio — NUNCA ofereça imagem. Use o texto para explicar verbalmente.\n"
                if _foto_grade:
                    prompt_sistema += "Esta unidade também TEM uma imagem da grade de aulas disponível.\n"
                    prompt_sistema += "A imagem é um COMPLEMENTO — ofereça APÓS já ter respondido com o texto. Exemplo: 'E se quiser ver a grade completa com os horários, posso te enviar a imagem também!'\n"
                    prompt_sistema += "NUNCA envie a imagem como primeira/única resposta. Sempre responda com texto primeiro.\n"
                    prompt_sistema += "NUNCA diga que não tem a grade. Se pedirem, ofereça o texto E a imagem.\n"

            # ── Tour Virtual — Estratégia Inteligente (4 modos) ──
            _link_tour = unidade.get("link_tour_virtual")
            logger.info(f"🎥 [Tour] conv={conversation_id} slug={slug} link_tour={'SIM: '+_link_tour[:60] if _link_tour else 'NÃO'}")
            if _link_tour:
                _estrategia_tour = pers.get("estrategia_tour")
                # Backward compat: se campo novo é NULL, usa legado
                if not _estrategia_tour:
                    _estrategia_tour = "proativo" if pers.get("oferecer_tour", True) else "off"

                _tipo_cli = detectar_tipo_cliente(primeira_mensagem or "")
                _eh_lead = _tipo_cli is None  # None = lead (não aluno, não gympass)

                # Redis dedup: por conversa+unidade + por telefone+unidade (7 dias)
                _tour_sent_key = f"tour_enviado:{empresa_id}:{conversation_id}:{slug}"
                _fone_dedup = await redis_client.get(f"fone_cliente:{conversation_id}")
                _phone_unit_key = f"tour_enviado:{empresa_id}:{_fone_dedup}:{slug}" if _fone_dedup else None
                _ja_enviou_tour = (
                    await redis_client.exists(_tour_sent_key) or
                    (bool(_phone_unit_key) and await redis_client.exists(_phone_unit_key))
                )

                logger.info(f"🎥 [Tour Strategy] conv={conversation_id} estrategia={_estrategia_tour} lead={_eh_lead} ja_enviou={_ja_enviou_tour}")

                if _estrategia_tour != "off":
                    if _ja_enviou_tour:
                        prompt_sistema += "\n[TOUR VIRTUAL — JÁ ENVIADO]\nO tour virtual desta unidade já foi enviado ao cliente. NÃO ofereça novamente.\n"
                    elif _estrategia_tour == "reativo":
                        prompt_sistema += """
[TOUR VIRTUAL — MODO REATIVO]
Esta unidade possui um vídeo de Tour Virtual disponível.
- SOMENTE envie o tour se o cliente PEDIR explicitamente para ver a academia, tour, vídeo, ou conhecer por dentro.
- NÃO ofereça espontaneamente.
- Para enviar: adicione <SEND_VIDEO> no final da sua resposta.
"""
                    elif _estrategia_tour == "proativo" and _eh_lead:
                        prompt_sistema += """
[TOUR VIRTUAL — MODO PROATIVO]
Esta unidade possui um vídeo de Tour Virtual disponível.

REGRA OBRIGATÓRIA DE ENVIO:
- Se o cliente PEDIR para ver o tour, vídeo, conhecer por dentro → ENVIE IMEDIATAMENTE adicionando <SEND_VIDEO> no final da resposta.
- Se demonstrar interesse mas NÃO pediu explicitamente → ofereça primeiro. Quando aceitar, use <SEND_VIDEO>.

OFERECIMENTO PROATIVO (este cliente é um LEAD):
1. Se demonstrar interesse na unidade, ofereça o tour.
2. Após 2-3 mensagens de rapport, ofereça naturalmente se ainda não ofereceu.
3. NÃO ofereça mais de uma vez. Se recusou, não insista.

COMO ENVIAR: adicione a tag <SEND_VIDEO> no final da sua resposta (o sistema envia o vídeo automaticamente).
"""
                    elif _estrategia_tour == "smart" and _eh_lead:
                        _perguntar_visita = pers.get("tour_perguntar_primeira_visita", True)
                        if _perguntar_visita:
                            prompt_sistema += f"""
[TOUR VIRTUAL — ESTRATÉGIA INTELIGENTE]
Esta unidade possui um vídeo de Tour Virtual disponível.

FLUXO OBRIGATÓRIO (siga na ordem):
1. Quando o cliente demonstrar interesse na unidade ou perguntar sobre ela, pergunte naturalmente: "Você já conhece nossa unidade {nome_unidade} pessoalmente, ou seria sua primeira vez?"
2. Se o cliente disser que é PRIMEIRA VEZ, NUNCA VISITOU, ou NUNCA FOI:
   → Responda algo como "Então deixa eu te mostrar como é por dentro!" e adicione <SEND_VIDEO> no final.
3. Se o cliente disser que JÁ CONHECE ou JÁ VISITOU:
   → NÃO envie o tour. Continue a conversa normalmente.
4. Se o cliente PEDIR explicitamente para ver o tour/vídeo (independente de já conhecer):
   → Envie com <SEND_VIDEO>.

REGRAS:
- NÃO faça a pergunta "já conhece?" mais de UMA VEZ na conversa.
- Se o cliente pedir o tour ANTES de você perguntar → envie direto com <SEND_VIDEO>, sem perguntar.
- COMO ENVIAR: adicione <SEND_VIDEO> no final da resposta (o sistema envia automaticamente).
"""
                        else:
                            prompt_sistema += """
[TOUR VIRTUAL — ENVIO AUTOMÁTICO PARA LEADS]
Esta unidade possui um vídeo de Tour Virtual.
Quando o lead demonstrar interesse na unidade, envie o tour automaticamente adicionando <SEND_VIDEO>.
Se o cliente PEDIR para ver → envie imediatamente com <SEND_VIDEO>.
NÃO ofereça mais de uma vez.
"""
                    elif not _eh_lead and _estrategia_tour != "off":
                        # Aluno/Gympass: modo reativo independente da estratégia
                        prompt_sistema += "\n[TOUR VIRTUAL]: Esta unidade tem tour virtual. Se o cliente pedir para ver, adicione <SEND_VIDEO> no final da resposta.\n"

            prompt_sistema += f"""
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
{lista_unidades_nomes}
(Se o cliente perguntar quais unidades existem, liste esses nomes. Para detalhes de endereço/horário de outra unidade, pergunte qual delas ele prefere para você buscar as informações.)

FAQ — RESPOSTAS PRONTAS (USE SEMPRE QUE A PERGUNTA DO CLIENTE SE ENCAIXAR):
{faq}

HISTÓRICO DA CONVERSA
{historico}

REGRAS CRÍTICAS — ANTI-ALUCINAÇÃO (OBRIGATÓRIO):
- Use EXCLUSIVAMENTE as informações presentes em "INFORMAÇÕES DA UNIDADE" acima.
- Se um campo estiver como "não informado" ou "não disponível", diga que não tem essa informação agora e que vai verificar com a equipe.
- NUNCA invente endereços, telefones, horários, links, planos, preços ou qualquer dado não informado.
- NUNCA ofereça ou prometa algo que NÃO esteja nos dados acima (promoções, descontos, benefícios, diárias, aulas experimentais, etc).
- NUNCA diga que a empresa tem "apenas uma unidade" — você não tem essa informação completa.
- Se a pergunta do cliente bater com algum item do FAQ acima, USE aquela resposta como base.
- Se "Link de Matrícula / LP" estiver disponível com URL (http), ENVIE O LINK IMEDIATAMENTE na resposta. NÃO peça dados pessoais antes. NÃO diga "vou buscar" ou "estou validando". Exemplo: "Dá uma olhada nos nossos planos aqui: [link]"
- Se "Link de Matrícula / LP" estiver como "não disponível", NÃO invente link — diga que o cliente pode entrar em contato diretamente com a unidade.
- NUNCA diga "vou buscar o link", "estou validando", "vou enviar em instantes" — se tem o link, ENVIE. Se não tem, diga que não tem.
- Você está atendendo a unidade indicada em "INFORMAÇÕES DA UNIDADE". Se o cliente perguntar sobre outra unidade, use os dados que tiver sobre ela (na lista de unidades) ou ofereça buscar.
- Você PODE perguntar o primeiro nome do cliente de forma natural (ex: "E qual seu nome?" ou "Com quem eu falo?"). Mas NUNCA peça outros dados pessoais (CPF, email, endereço, telefone, RG, data de nascimento). Você é um vendedor, NÃO um formulário.
- NUNCA diga "vou pedir para um consultor te chamar" ou "vou encaminhar para um consultor" — responda com as informações que você tem ou direcione para o link.

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
- NUNCA repita o nome do cliente na mesma resposta — use no máximo 1 vez, na saudação
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

            modelo_escolhido = pers.get("modelo_preferido") or (
                "google/gemini-2.5-flash" if imagens_urls else "google/gemini-2.5-flash-lite"
            )
            temperature = float(pers.get("temperatura") or 0.7)
            max_tokens = int(pers.get("max_tokens") or 1200)

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

                # Monta conteúdo do role "user":
                # - Com imagem: lista multimodal [imagem(s) + texto da pergunta]
                # - Sem imagem: string direta com as mensagens
                # Sem isso o modelo recebe a imagem mas não a pergunta real do cliente.
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
                            max_tokens=max_tokens,  # Usa o valor da personalidade_ia ou 1200 como porto seguro
                                              # Reduz custo e evita erro 402 de crédito insuficiente
                        ),
                        timeout=extra_timeout
                    )

                async with llm_semaphore:
                    try:
                        response = await _chamar_llm(modelo_escolhido, extra_timeout=25)
                        resposta_bruta = response.choices[0].message.content
                        # Resposta longa (length) agora é tratada deixando o texto fluir até o final natural dele (max_tokens generoso)
                        _finish = getattr(response.choices[0], 'finish_reason', None)
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
                            if _is_provider_unavailable_error(e2):
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
                        erro_provedor = _is_provider_unavailable_error(e)
                        if erro_provedor:
                            logger.warning("⚠️ IA indisponível temporariamente (OpenRouter)")
                            await redis_client.setex(llm_provider_pause_key, 300, "1")
                        elif _is_openrouter_auth_error(e):
                            logger.warning("⚠️ Falha de autenticação OpenRouter (verifique OPENROUTER_API_KEY)")
                            await redis_client.setex(llm_provider_pause_key, 600, "1")
                        else:
                            logger.warning("⚠️ Erro LLM primário — tentando fallback")
                        await cb_llm.record_failure()
                        if _PROMETHEUS_OK:
                            METRIC_ERROS_TOTAL.labels(tipo="llm_fallback").inc()

                        # Em indisponibilidade do provedor, evita nova tentativa imediata no fallback
                        # para reduzir ruído de log e latência.
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
                                if _is_provider_unavailable_error(e2):
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
                if _PROMETHEUS_OK:
                    METRIC_IA_LATENCY.observe(_latencia)

            if not goto_send:
                # ── Garante que NENHUMA resposta saia com frase cortada ──────────
                def _garantir_frase_completa(txt: str) -> str:
                    """Remove frase incompleta no final do texto.
                    Procura o último terminador de frase (. ! ? ou quebra de linha)
                    e descarta tudo depois, evitando enviar 'horários super est'."""
                    if not txt:
                        return txt
                    txt = txt.strip()
                    # Se termina com pontuação ou emoji, está OK
                    if txt[-1] in '.!?😊💪✅🏋🎯':
                        return txt
                    # Procura último ponto de corte seguro
                    for _sep in ['. ', '! ', '? ', '!\n', '?\n', '.\n', '\n']:
                        _pos = txt.rfind(_sep)
                        if _pos > len(txt) * 0.3:  # só corta se mantém >30% do texto
                            return txt[:_pos + 1].strip()
                    # Sem ponto de corte — retorna tudo (melhor inteiro que vazio)
                    return txt

                # ── A IA agora responde texto puro — sem JSON ──────────────────
                resposta_texto = limpar_markdown(resposta_bruta.strip())

                # Tenta extrair JSON legado caso o modelo ainda retorne JSON (backward compat)
                if resposta_texto.startswith('{'):
                    try:
                        _dados_legado = json.loads(corrigir_json(resposta_texto))
                        resposta_texto = limpar_markdown(_dados_legado.get("resposta", resposta_texto))
                        novo_estado = _dados_legado.get("estado", estado_atual).strip().lower()
                    except (json.JSONDecodeError, ValueError):
                        pass  # Não é JSON, usa como texto mesmo

                # Extrai tags de mídia ANTES de cortar frases (senão _garantir_frase_completa remove)
                _TAG_MIDIA_RE = re.compile(r'<SEND_(?:VIDEO|IMAGE)(?::[^>]*)?>')
                _tags_midia = _TAG_MIDIA_RE.findall(resposta_texto or '')
                if _tags_midia:
                    resposta_texto = _TAG_MIDIA_RE.sub('', resposta_texto).strip()

                # Aplica a garantia de frase completa para evitar truncamento feio (ativas no main tbm)
                resposta_texto = _garantir_frase_completa(resposta_texto)

                # Reanexa as tags de mídia ao final para processamento posterior
                if _tags_midia:
                    resposta_texto = resposta_texto + ' ' + ' '.join(_tags_midia)

                # Inferir estado emocional a partir das palavras-chave da resposta
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

                if not resposta_texto:
                    resposta_texto = "Desculpe, pode repetir sua pergunta? 😊"
                    novo_estado = estado_atual

                # Pós-processamento de conversão: se o cliente já sinalizou compra,
                # garante envio do link de matrícula e CTA de outros planos na mesma resposta.
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

                if not imagens_urls and resposta_texto and not _tags_midia:
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

                if link_plano in resposta_texto or "matricular" in resposta_texto.lower():
                    await bd_registrar_evento_funil(
                        conversation_id, "link_matricula_enviado", "Link enviado via IA", score_incremento=2
                    )
                if tel_banco and tel_banco in resposta_texto:
                    await bd_registrar_evento_funil(
                        conversation_id, "solicitacao_telefone", "IA forneceu telefone", score_incremento=3
                    )

        # --- Tour Virtual: detecta e limpa tag <SEND_VIDEO> ---
        _enviar_tour = False
        _link_tour_unidade = unidade.get("link_tour_virtual")
        _has_tag = bool(resposta_texto and "<SEND_VIDEO>" in resposta_texto)
        logger.info(f"🎥 [Tour Handler] conv={conversation_id} tag_detectada={_has_tag} link_tour={'SIM' if _link_tour_unidade else 'NÃO'}")
        if _has_tag:
            resposta_texto = resposta_texto.replace("<SEND_VIDEO>", "").strip()
            if _link_tour_unidade:
                _enviar_tour = True
            else:
                logger.warning(f"⚠️ [Tour] IA usou <SEND_VIDEO> mas unidade não tem link_tour_virtual!")

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

        try:
            qualif_label = _label_qualif(texto_cliente_unificado, novo_estado, _intencao_compra)
            await atualizar_labels_conversa_chatwoot(
                account_id=account_id,
                conversation_id=conversation_id,
                integracao=integracao_chatwoot,
                slug=slug,
                qualif_label=qualif_label,
            )
        except Exception as e:
            logger.warning(f"Falha ao classificar labels da conversa {conversation_id}: {e}")

        # --- NOVIDADE: PRIORIZAÇÃO GLOBAL DE MÍDIA (Grade, etc. - movido para depois do texto) ---
        _foto_grade = unidade.get("foto_grade")
        _texto_unificado_lower = " ".join([t for t in (textos + transcricoes) if t]).lower()
        _keywords_grade = ["grade", "cronograma", "quadro de aulas", "horario das aulas", "horário das aulas", "grade de aulas", "imagem da grade", "foto da grade", "horários", "horarios"]
        _quer_grade = any(x in _texto_unificado_lower for x in _keywords_grade)

        salvar_resposta_unica = bool(resposta_texto and resposta_texto.strip() and not fast_reply_lista)
        if salvar_resposta_unica:
            await bd_salvar_mensagem_local(conversation_id, "assistant", resposta_texto)

        is_manual = (await redis_client.get(f"atend_manual:{empresa_id}:{conversation_id}")) == "1"

        # ── TTS: detecta se cliente enviou áudio → responde com áudio ──
        _tts_ativo = pers.get("tts_ativo", True) if pers else True
        _tts_voz = pers.get("tts_voz", None) if pers else None
        _cliente_enviou_audio = len(transcricoes) > 0 if transcricoes else False
        _uaz_integ = await carregar_integracao(empresa_id, 'uazapi') if empresa_id else None
        _has_whatsapp = bool(_uaz_integ)
        _enviar_audio = _cliente_enviou_audio and _tts_ativo and _has_whatsapp
        logger.info(f"🔊 [TTS Check] conv={conversation_id} | audio_cliente={_cliente_enviou_audio} | tts_ativo={_tts_ativo} | voz={_tts_voz} | has_whatsapp={_has_whatsapp} | enviar_audio={_enviar_audio}")

        async def _enviar_tts_ptt(texto_para_tts: str) -> bool:
            """Envia áudio PTT via UazAPI se TTS estiver ativo. Retorna True se enviou."""
            if not _enviar_audio or not texto_para_tts:
                return False
            try:
                from src.services.tts_service import gerar_audio_resposta
                from src.utils.imagekit import upload_to_imagekit
                import uuid as _uuid

                # Busca telefone do cliente
                _fone = await redis_client.get(f"fone_cliente:{conversation_id}")
                if not _fone and db_pool:
                    _fone = await db_pool.fetchval(
                        "SELECT COALESCE(contato_fone, contato_telefone) FROM conversas WHERE conversation_id = $1",
                        conversation_id
                    )
                if not _fone:
                    logger.warning(f"⚠️ [TTS] Telefone não encontrado para conv={conversation_id}")
                    return False

                logger.info(f"🔊 [TTS] Gerando áudio para conv={conversation_id} (voz={_tts_voz})")
                audio_bytes = await gerar_audio_resposta(texto_para_tts, voz=_tts_voz)
                if not audio_bytes:
                    logger.warning(f"⚠️ [TTS] gerar_audio_resposta retornou None")
                    return False

                logger.info(f"🔊 [TTS] Áudio gerado: {len(audio_bytes)} bytes, uploading...")
                audio_url = await upload_to_imagekit(
                    audio_bytes,
                    f"tts_{_uuid.uuid4().hex[:8]}.wav",
                    folder="/tts"
                )
                if not audio_url:
                    logger.warning(f"⚠️ [TTS] Upload ImageKit falhou")
                    return False

                _uaz = UazAPIClient(
                    _uaz_integ.get('url') or _uaz_integ.get('api_url'),
                    _uaz_integ.get('token'),
                    _uaz_integ.get('instance', 'default')
                )
                # Marca echo ANTES de enviar para evitar que Chatwoot pause a IA
                await redis_client.setex(f"uaz_bot_sent:{conversation_id}", 120, "1")
                if empresa_id and _fone:
                    await redis_client.setex(f"uaz_bot_sent:{empresa_id}:{_fone}", 120, "1")
                ptt_ok = await _uaz.send_ptt(str(_fone), audio_url, delay=500)
                logger.info(f"🔊 [TTS] PTT enviado: ok={ptt_ok} url={audio_url}")
                return bool(ptt_ok)
            except Exception as e:
                logger.error(f"❌ [TTS] Erro: {e}", exc_info=True)
                return False

        if is_manual or await redis_client.exists(f"pause_ia:{empresa_id}:{conversation_id}"):
            pass  # IA pausada, não envia

        elif fast_reply_lista:
            # ── Planos: cada item da lista = 1 mensagem separada ──────────────
            _total_planos = len([b for b in fast_reply_lista if b.strip()])
            _plano_idx = 0
            for i, bloco_plano in enumerate(fast_reply_lista):
                if await redis_client.exists(f"pause_ia:{empresa_id}:{conversation_id}"):
                    break
                if not bloco_plano.strip():
                    continue
                _plano_idx += 1
                await bd_salvar_mensagem_local(conversation_id, "assistant", bloco_plano.strip())
                typing_time = min(len(bloco_plano) * 0.012, 3.0) + random.uniform(0.2, 0.6)
                await simular_digitacao(account_id, conversation_id, integracao_chatwoot, typing_time, empresa_id)
                # TTS PTT apenas no último bloco — se enviou áudio, pula texto
                _ptt_enviado = False
                if _plano_idx == _total_planos:
                    _ptt_enviado = await _enviar_tts_ptt(bloco_plano.strip())
                if not _ptt_enviado:
                    await enviar_mensagem_chatwoot(
                        account_id, conversation_id, bloco_plano.strip(), nome_ia, integracao_chatwoot, empresa_id
                    )
                await bd_atualizar_msg_ia(conversation_id)
                if i == 0:
                    await bd_registrar_primeira_resposta(conversation_id)

        elif fast_reply:
            # ── Fast-path: envia UMA mensagem (saudação, endereço, horário, etc.) ──
            if not resposta_texto:
                resposta_texto = fast_reply if isinstance(fast_reply, str) else ""
            typing_time = min(len(resposta_texto) * 0.015, 3.5) + random.uniform(0.3, 0.8)
            await simular_digitacao(account_id, conversation_id, integracao_chatwoot, typing_time, empresa_id)
            _ptt_enviado = await _enviar_tts_ptt(resposta_texto)
            if not _ptt_enviado:
                await enviar_mensagem_chatwoot(
                    account_id, conversation_id, resposta_texto, nome_ia, integracao_chatwoot, empresa_id
                )
            await bd_atualizar_msg_ia(conversation_id)
            await bd_registrar_primeira_resposta(conversation_id)

        else:
            # ── Resposta da IA: envia INTEIRA como UMA mensagem ──────────────
            if resposta_texto and resposta_texto.strip():
                _texto_final = resposta_texto.strip()

                typing_time = min(len(_texto_final) * 0.02, 4.0) + random.uniform(0.3, 0.8)
                await simular_digitacao(account_id, conversation_id, integracao_chatwoot, typing_time, empresa_id)
                _ptt_enviado = await _enviar_tts_ptt(_texto_final)
                if not _ptt_enviado:
                    await enviar_mensagem_chatwoot(
                        account_id, conversation_id, _texto_final, nome_ia, integracao_chatwoot, empresa_id
                    )
                await bd_atualizar_msg_ia(conversation_id)
                await bd_registrar_primeira_resposta(conversation_id)

        # ── PÓS-PROCESSAMENTO: Mídia (Grade, etc.) ──
        if _quer_grade and not (is_manual or await redis_client.exists(f"pause_ia:{empresa_id}:{conversation_id}")):
            if _foto_grade:
                try:
                    logger.info(f"🖼️ Enviando foto_grade (Pós-Texto) para conv {conversation_id}")
                    # Pequeno delay para garantir que o texto chegue antes
                    await asyncio.sleep(1.5)
                    await enviar_mensagem_chatwoot(
                        account_id, conversation_id, 
                        f"Aqui está a grade de aulas da unidade *{nome_unidade or 'selecionada'}* 😊", 
                        nome_ia, integracao_chatwoot, empresa_id,
                        attachment_url=_foto_grade
                    )
                except Exception as e:
                    logger.error(f"Erro ao enviar foto_grade: {e}")
            else:
                logger.warning(f"⚠️ Cliente pediu grade, mas a unidade {nome_unidade} (slug: {slug}) NÃO possui foto_grade cadastrada.")

        # ── PÓS-PROCESSAMENTO: Tour Virtual (vídeo) com dedup Redis ──
        if _enviar_tour and _link_tour_unidade and not (is_manual or await redis_client.exists(f"pause_ia:{empresa_id}:{conversation_id}")):
            _tour_dedup_key = f"tour_enviado:{empresa_id}:{conversation_id}:{slug}"
            _tour_ja_enviou = await redis_client.exists(_tour_dedup_key)
            if _tour_ja_enviou:
                logger.info(f"⏭️ Tour já enviado para conv {conversation_id}, ignorando duplicata")
            else:
                try:
                    logger.info(f"🎥 Enviando tour virtual para conv {conversation_id}")
                    await asyncio.sleep(2.0)
                    _fone_tour = await redis_client.get(f"fone_cliente:{conversation_id}")
                    _uaz_tour = await carregar_integracao(empresa_id, 'uazapi')
                    if _fone_tour and _uaz_tour:
                        _uaz_cli = UazAPIClient(
                            _uaz_tour.get('url') or _uaz_tour.get('api_url'),
                            _uaz_tour.get('token'),
                            _uaz_tour.get('instance', 'default')
                        )
                        _fone_clean = "".join(filter(str.isdigit, str(_fone_tour)))
                        await redis_client.setex(f"uaz_bot_sent:{conversation_id}", 120, "1")
                        await redis_client.setex(f"uaz_bot_sent:{empresa_id}:{_fone_clean}", 120, "1")
                        _tour_ok = await _uaz_cli.send_media(_fone_clean, _link_tour_unidade, media_type="video")
                        if not _tour_ok:
                            # Retry como document (vídeos grandes podem falhar como "video")
                            logger.warning(f"⚠️ Tour falhou como video, tentando como document...")
                            await redis_client.setex(f"uaz_bot_sent:{conversation_id}", 120, "1")
                            await redis_client.setex(f"uaz_bot_sent:{empresa_id}:{_fone_clean}", 120, "1")
                            _tour_ok = await _uaz_cli.send_media(_fone_clean, _link_tour_unidade, media_type="document")
                        if _tour_ok:
                            # Marca tour como enviado (7 dias TTL) — por conversa e por telefone+unidade
                            await redis_client.setex(_tour_dedup_key, 604800, "1")
                            if _fone_clean and slug:
                                await redis_client.setex(f"tour_enviado:{empresa_id}:{_fone_clean}:{slug}", 604800, "1")
                            logger.info(f"🎥 Tour virtual enviado com sucesso para conv {conversation_id}")
                        else:
                            logger.error(f"❌ Tour virtual falhou (video + document) para conv {conversation_id}")
                    else:
                        # Fallback: envia via Chatwoot com attachment_url
                        await enviar_mensagem_chatwoot(
                            account_id, conversation_id,
                            f"Tour virtual da unidade *{nome_unidade}*",
                            nome_ia, integracao_chatwoot, empresa_id,
                            attachment_url=_link_tour_unidade
                        )
                        await redis_client.setex(_tour_dedup_key, 604800, "1")
                except Exception as e:
                    logger.error(f"❌ Erro ao enviar tour virtual: {e}")

        # Registra hash das mensagens respondidas para bloquear duplicatas no drain
        await redis_client.setex(_ultima_resp_key, 120, _hash_msgs)

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
                    await bd_salvar_mensagem_local(conversation_id, "user", txt)

            if textos_drain and cliente_ia and prompt_sistema:
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
                        await simular_digitacao(account_id, conversation_id, integracao_chatwoot, typing_time, empresa_id)
                        await enviar_mensagem_chatwoot(
                            account_id, conversation_id, _drain_texto.strip(),
                            nome_ia, integracao_chatwoot, empresa_id
                        )
                        await bd_salvar_mensagem_local(conversation_id, "assistant", _drain_texto.strip())
                        await bd_atualizar_msg_ia(conversation_id)
                        logger.info(f"✅ Drain inline respondido (conv={conversation_id})")

                except Exception as e_drain_llm:
                    logger.warning(f"⚠️ Erro no drain inline LLM ({type(e_drain_llm).__name__}): {e_drain_llm}", exc_info=True)

    except Exception:
        logger.exception("🔥 Erro Crítico no processamento")
    finally:
        watchdog.cancel()
        try:
            await redis_client.eval(LUA_RELEASE_LOCK, 1, chave_lock, lock_val)
        except Exception:
            pass


# --- WEBHOOK ENDPOINT ---

@app.get("/webhook")
async def chatwoot_webhook_verify():
    """Endpoint de verificação para o Chatwoot (requisição GET de handshake)."""
    return {"status": "ok", "message": "Webhook ativo"}


@app.post("/webhook")
async def chatwoot_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_chatwoot_signature: str = Header(None),
    x_chatwoot_timestamp: str = Header(None)
):
    # Lê body bruto uma vez (FastAPI faz cache — pode ser lido novamente como JSON)
    body = await request.body()
    try:
        payload = json.loads(body)
    except Exception:
        logger.error("Webhook recebido com JSON invalido")
        return {"status": "json_invalido"}

    event = payload.get("event")
    id_conv = payload.get("conversation", {}).get("id") or payload.get("id")
    account_id = payload.get("account", {}).get("id")

    logger.info(f"Webhook recebido: event={event} account={account_id} conv={id_conv}")

    # Extrai flags importantes do Chatwoot
    is_private = payload.get("private") is True or (payload.get("message") or {}).get("private") is True

    if _PROMETHEUS_OK:
        METRIC_WEBHOOKS_TOTAL.labels(event=event or "unknown").inc()

    if not id_conv:
        return {"status": "ignorado_sem_conversation_id"}

    # Rate limit por conversa (anti-loop de webhook)
    rate_key = f"rl:conv:{id_conv}"
    contador = await redis_client.incr(rate_key)
    if contador == 1:
        await redis_client.expire(rate_key, 10)
    if contador > 10:
        from fastapi.responses import JSONResponse
        return JSONResponse({"status": "rate_limit"}, status_code=429)

    # Busca empresa pelo account_id
    empresa_id = await buscar_empresa_por_account_id(account_id)
    if not empresa_id:
        logger.error(f"Account {account_id} sem empresa associada")
        return {"status": "erro_sem_empresa"}

    # Carrega integração Chatwoot da empresa
    integracao = await carregar_integracao(empresa_id, 'chatwoot')
    if not integracao:
        logger.error(f"Empresa {empresa_id} sem integracao Chatwoot ativa")
        return {"status": "erro_sem_integracao"}

    # Valida assinatura HMAC — Chatwoot v4+ usa formato: sha256=HMAC(secret, "{timestamp}.{body}")
    webhook_secret = integracao.get("webhook_secret") or CHATWOOT_WEBHOOK_SECRET
    if webhook_secret and x_chatwoot_signature:
        sig = x_chatwoot_signature
        # Chatwoot v4+ envia "sha256={hex}" com message = "{timestamp}.{body}"
        if x_chatwoot_timestamp:
            message = f"{x_chatwoot_timestamp}.{body.decode()}"
            expected_hex = hmac.new(webhook_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
            expected_sig = f"sha256={expected_hex}"
            if not hmac.compare_digest(sig, expected_sig):
                logger.warning(f"Assinatura invalida para account={account_id} (formato timestamp.body)")
                raise HTTPException(status_code=401, detail="Assinatura inválida")
        else:
            # Fallback: formato legado (body puro, sem timestamp, sem prefixo sha256=)
            raw_sig = sig.removeprefix("sha256=") if sig.startswith("sha256=") else sig
            expected = hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(raw_sig, expected):
                logger.warning(f"Assinatura invalida para account={account_id} (formato legado)")
                raise HTTPException(status_code=401, detail="Assinatura inválida")

    logger.info(f"Webhook validado: empresa={empresa_id} event={event}")

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
            f"pause_ia:{empresa_id}:{id_conv}", f"estado:{id_conv}",
            f"unidade_escolhida:{id_conv}", f"esperando_unidade:{id_conv}",
            f"prompt_unidade_enviado:{id_conv}", f"nome_cliente:{id_conv}", f"aguardando_nome:{id_conv}",
            f"atend_manual:{empresa_id}:{id_conv}", f"lock:{id_conv}", f"buffet:{id_conv}"
        )
        logger.info(f"🆕 Nova conversa {id_conv} — Redis limpo")
        return {"status": "conversa_criada"}

    if event == "conversation_updated":
        status_conv = conv_obj.get("status") or payload.get("status")
        if status_conv in {"resolved", "closed"}:
            await bd_finalizar_conversa(id_conv)
            await redis_client.delete(
                f"pause_ia:{empresa_id}:{id_conv}", f"estado:{id_conv}",
                f"unidade_escolhida:{id_conv}", f"esperando_unidade:{id_conv}",
                f"prompt_unidade_enviado:{id_conv}", f"nome_cliente:{id_conv}", f"aguardando_nome:{id_conv}",
                f"atend_manual:{empresa_id}:{id_conv}"
            )
            return {"status": "conversa_encerrada"}
        return {"status": "conversa_atualizada"}

    if event != "message_created":
        return {"status": "ignorado"}

    message_type = payload.get("message_type")
    sender_type = payload.get("sender", {}).get("type", "").lower()
    content_attrs = payload.get("content_attributes") or {}
    conteudo_texto = str(payload.get("content", "") or "")
    
    # Identificação robusta de mensagens da IA (Sync ou Direta)
    # Verifica atributos no nível raiz do payload e também dentro do objeto message (comum em anexos)
    msg_obj = payload.get("message") or {}
    msg_attrs = msg_obj.get("content_attributes") or {}
    msg_id = payload.get("id") or msg_obj.get("id")

    # Verifica se o ID da mensagem está no Redis (marcado pela enviar_mensagem_chatwoot)
    is_ai_in_redis = False
    if msg_id:
        is_ai_in_redis = await redis_client.exists(f"ai_msg_id:{msg_id}")

    is_ai_message = (
        content_attrs.get("origin") == "ai" 
        or msg_attrs.get("origin") == "ai"
        or is_ai_in_redis
        or is_private
    )

    # --- ECHO PROTECTION: Ignora mensagens que o próprio bot enviou direto via UazAPI ---
    _fone_echo = await redis_client.get(f"fone_cliente:{id_conv}")
    is_uaz_echo = False
    if await redis_client.exists(f"uaz_bot_sent:{id_conv}"):
        is_uaz_echo = True
    elif _fone_echo and await redis_client.exists(f"uaz_bot_sent:{empresa_id}:{_fone_echo}"):
        is_uaz_echo = True

    if message_type == "outgoing" and is_uaz_echo:
        logger.info(f"♻️ Echo UazAPI detectado e ignorado para conv {id_conv}")
        return {"status": "eco_uazapi_ignorado"}

    # Ignora mensagens enviadas pela própria IA (via Chatwoot)
    if is_ai_message or sender_type == "bot":
        return {"status": "ignorado_msg_propria"}

    contato = payload.get("sender", {})
    nome_contato_raw = contato.get("name")
    nome_contato_limpo = limpar_nome(nome_contato_raw)
    nome_contato_valido = nome_eh_valido(nome_contato_limpo)

    if message_type == "incoming":
        _telefone = contato.get("phone_number")
        if _telefone:
            await redis_client.setex(f"fone_cliente:{id_conv}", 86400, str(_telefone))
            
        if nome_contato_valido:
            await redis_client.setex(f"nome_cliente:{id_conv}", 86400, nome_contato_limpo)
        else:
            _nome_informado = extrair_nome_do_texto(conteudo_texto or "")
            if _nome_informado:
                await redis_client.setex(f"nome_cliente:{id_conv}", 86400, _nome_informado)
                await redis_client.delete(f"aguardando_nome:{id_conv}")
                await atualizar_nome_contato_chatwoot(account_id, contato.get("id"), _nome_informado, integracao)
                logger.info(f"✅ Nome '{_nome_informado}' extraído da mensagem e atualizado no Chatwoot (conv={id_conv})")
            else:
                # Nome do contato é inválido e mensagem não contém nome — pedir
                _aguardando = await redis_client.get(f"aguardando_nome:{id_conv}")
                if not _aguardando:
                    _pers_nome = await carregar_personalidade(empresa_id) or {}
                    _nome_ia_nome = _pers_nome.get('nome_ia') or 'Atendente'
                    msg_nome = (
                        "Antes de continuar, me fala seu *nome* pra eu te atender certinho 😊\n\n"
                        "Pode me responder só com seu primeiro nome."
                    )
                    await enviar_mensagem_chatwoot(
                        account_id, id_conv, msg_nome,
                        _nome_ia_nome, integracao, empresa_id
                    )
                    await redis_client.setex(f"aguardando_nome:{id_conv}", 900, "1")
                    logger.info(f"🏷️ Nome inválido '{nome_contato_raw}' detectado — pedindo nome real (conv={id_conv})")
                    return {"status": "aguardando_nome"}

    # Idempotência básica: evita reprocessar o mesmo message_created em retries do webhook
    mensagem_id = payload.get("id")
    if message_type == "incoming" and mensagem_id:
        dedup_key = f"msg_incoming_processada:{id_conv}:{mensagem_id}"
        if not await redis_client.set(dedup_key, "1", nx=True, ex=120):
            logger.info(f"⏭️ Webhook duplicado ignorado conv={id_conv} msg={mensagem_id}")
            return {"status": "duplicado"}
    labels = payload.get("conversation", {}).get("labels", [])
    slug_label = next((str(l).lower().strip() for l in labels if l), None)
    slug_redis = await redis_client.get(f"unidade_escolhida:{id_conv}")
    # Regra de segurança: em operação multiunidade, NÃO usar label como fonte primária.
    # A unidade só é assumida por escolha explícita (Redis) ou por detecção no texto.
    slug = slug_redis
    slug_detectado = None
    esperando_unidade = await redis_client.get(f"esperando_unidade:{id_conv}")
    prompt_unidade_key = f"prompt_unidade_enviado:{id_conv}"

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
        _tem_geo_wh = False
        try:
            _units_wh = await listar_unidades_ativas(empresa_id)
            for _u in _units_wh:
                for _campo in ['nome', 'cidade', 'bairro']:
                    _val = normalizar(_u.get(_campo, '') or '')
                    if _val and len(_val) >= 4 and _val in _msg_norm_wh:
                        _tem_geo_wh = True
                        break
                if _tem_geo_wh:
                    break
        except Exception:
            pass

        # Troca unidade se: (a) está esperando escolha, (b) mencionou outra unidade por nome,
        # ou (c) pedido explícito com geo. Não exige mais keywords "trocar"/"mudar".
        if esperando_unidade or _tem_geo_wh:
            slug_detectado = await buscar_unidade_na_pergunta(
                conteudo_texto, empresa_id, fuzzy_threshold=82 if esperando_unidade else 90
            )
            if slug_detectado and slug_detectado != slug:
                logger.info(f"🔄 Webhook mudou contexto para {slug_detectado}")
                slug = slug_detectado
                await redis_client.setex(f"unidade_escolhida:{id_conv}", 86400, slug)
                if esperando_unidade:
                    await redis_client.delete(f"esperando_unidade:{id_conv}")
                await redis_client.delete(prompt_unidade_key)

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
            if not slug:
                # Múltiplas unidades — fluxo inteligente de identificação
                texto_cliente = normalizar(conteudo_texto).strip()

                # Tenta por nome/cidade/bairro já na primeira mensagem APENAS
                # quando houver indicador geográfico claro.
                _tem_geo_multi = False
                for _u in unidades_ativas:
                    for _campo in ["nome", "cidade", "bairro"]:
                        _v = normalizar(_u.get(_campo, "") or "")
                        if _v and len(_v) >= 4 and _v in texto_cliente:
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
                    await redis_client.setex(f"unidade_escolhida:{id_conv}", 86400, slug)
                    await redis_client.delete(f"esperando_unidade:{id_conv}")
                    await redis_client.delete(prompt_unidade_key)
                    contato = payload.get("sender", {})
                    _nome_contato = limpar_nome(contato.get("name"))
                    _telefone_contato = contato.get("phone_number")
                    await bd_iniciar_conversa(
                        id_conv, slug, account_id,
                        contato.get("id"), _nome_contato, empresa_id,
                        contato_telefone=_telefone_contato
                    )
                    await bd_registrar_evento_funil(
                        id_conv, "unidade_escolhida", f"Cliente escolheu {slug}", 3
                    )

                    # Envia confirmação humanizada com dados da unidade
                    _unid_dados = await carregar_unidade(slug, empresa_id) or {}
                    _nome_unid = _unid_dados.get('nome') or slug
                    _end_unid = extrair_endereco_unidade(_unid_dados) or ''
                    _hor_unid = _unid_dados.get('horarios')
                    _pers_temp = await carregar_personalidade(empresa_id) or {}
                    _nome_ia_temp = _pers_temp.get('nome_ia') or 'Atendente'

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
                    # Confirmação já enviada — NÃO cai no buffer/LLM
                    return {"status": "unidade_confirmada"}
                else:
                    # Unidade não identificada — permite que a IA responda como 'Global'
                    # e peça a unidade de forma natural conforme o System Prompt.
                    logger.info(f"🌐 Unidade não detectada para conv {id_conv}, prosseguindo com IA Global")
                    pass

    # Se chegamos aqui sem slug, a IA responderá como Consultor Global

    # Pausa IA se for mensagem de atendente humano
    if message_type == "outgoing" and sender_type == "user":
        if is_ai_message or is_uaz_echo:
            logger.info(f"🦾 Mensagem reconhecida como IA/bot (marker/echo) — mantendo fluxo ativo para conv {id_conv}")
            return {"status": "ignorado"}

        # Log de segurança para debugar se for uma mensagem da IA que escapou da detecção
        logger.warning(f"⏸️ Pausando IA para conv {id_conv} - Mensagem Outgoing sem marcador detectada (sender={sender_type}, origin={content_attrs.get('origin')}, msg_origin={msg_attrs.get('origin')}, ai_redis={is_ai_in_redis}, uaz_echo={is_uaz_echo})")

        await redis_client.setex(f"pause_ia:{empresa_id}:{id_conv}", 43200, "1")
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
    _nome_para_bd = nome_contato_limpo if nome_eh_valido(nome_contato_limpo) else (await redis_client.get(f"nome_cliente:{id_conv}")) or "Cliente"
    _telefone_para_bd = contato.get("phone_number")
    await bd_iniciar_conversa(
        id_conv, slug, account_id,
        contato.get("id"), _nome_para_bd, empresa_id,
        contato_telefone=_telefone_para_bd
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

    if await redis_client.exists(f"pause_ia:{empresa_id}:{id_conv}"):
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
            _nome_para_bd, lock_val, empresa_id, integracao
        )
        return {"status": "processando"}

    return {"status": "acumulando_no_buffet"}


@app.get("/desbloquear/{empresa_id}/{conversation_id}")
async def desbloquear_ia(empresa_id: int, conversation_id: int):
    if await redis_client.delete(f"pause_ia:{empresa_id}:{conversation_id}"):
        return {"status": "sucesso", "mensagem": f"✅ IA reativada para {conversation_id} na empresa {empresa_id}!"}
    return {"status": "aviso", "mensagem": f"A conversa {conversation_id} não estava pausada."}


# rota raiz consolidada em health() abaixo


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
        "versao": APP_VERSION,
    }


@app.get("/")
@app.head("/")
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
