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
    for _sep in ['. ', '! ', '? ', '!\n', '?\n', '.\n', '\n']:
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
    if re.search(r"(grade de aulas?|grade|modalidade|modalidades|aulas?|musculacao|musculação|funcional|spinning|cross)", t):
        return "modalidades"
    if re.search(r"(convenio|convênio|gympass|wellhub|totalpass)", t):
        return "convenio"
    return "llm"


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
    """Motor de decisão: unidade -> intenção -> estruturado -> FAQ -> LLM."""
    ctx = await resolver_contexto_unidade(conversation_id, texto_cliente, empresa_id, slug_atual=slug_atual)
    slug = ctx.get("slug")
    intencao = classificar_intencao(texto_cliente)
    _primeiro_nome = primeiro_nome_cliente(nome_cliente)
    _prefixo_nome = f"{_primeiro_nome}, " if _primeiro_nome else ""
    _abertura_ajuda = f"{_prefixo_nome}pra eu te ajudar direitinho" if _prefixo_nome else "Pra eu te ajudar direitinho"
    _abertura_claro = f"{_prefixo_nome}claro!" if _prefixo_nome else "Claro!"
    _abertura_perfeito = f"{_prefixo_nome}perfeito!" if _prefixo_nome else "Perfeito!"

    pending_key = f"pending_offer:{conversation_id}"
    pending_offer = await redis_client.get(pending_key)
    if pending_offer and intencao in {"llm", "saudacao", "neutro"} and eh_confirmacao_curta(texto_cliente):
        intencao = pending_offer
        await redis_client.delete(pending_key)

    if intencao == "unidades":
        return {"tipo": "texto", "resposta": await responder_lista_unidades(empresa_id, texto_cliente), "slug": slug, "intencao": intencao}

    if intencao in {"horario", "endereco", "telefone", "planos", "modalidades", "convenio"} and not slug:
        return {
            "tipo": "texto",
            "resposta": f"{_abertura_ajuda}, me conta em qual *cidade* ou *bairro* você quer treinar 😊",
            "slug": None,
            "intencao": intencao,
        }

    unidade = await carregar_unidade(slug, empresa_id) if slug else {}

    if intencao == "horario":
        await redis_client.setex(pending_key, 600, "endereco")
        return {"tipo": "texto", "resposta": responder_horario(unidade), "slug": slug, "intencao": intencao}
    if intencao == "endereco":
        await redis_client.setex(pending_key, 600, "horario")
        return {"tipo": "texto", "resposta": responder_endereco(unidade), "slug": slug, "intencao": intencao}
    if intencao == "telefone":
        await redis_client.delete(pending_key)
        return {"tipo": "texto", "resposta": responder_telefone(unidade), "slug": slug, "intencao": intencao}
    if intencao == "planos":
        await redis_client.delete(pending_key)
        planos = await buscar_planos_ativos(empresa_id, unidade.get("id"), force_sync=True)
        return {"tipo": "lista", "resposta": formatar_planos_bonito(planos) if planos else [], "slug": slug, "intencao": intencao}
    if intencao == "modalidades":
        modalidades = normalizar_lista_campo(unidade.get("modalidades"))
        if modalidades:
            lista = "\n".join([f"• {m}" for m in modalidades])
            return {
                "tipo": "texto",
                "resposta": (
                    f"{_abertura_claro} Na unidade *{unidade.get('nome', slug)}* essa é a nossa grade de aulas/modalidades:\n\n"
                    f"{lista}\n\n"
                    "Se quiser, já te passo também os planos 😉"
                ),
                "slug": slug,
                "intencao": intencao,
            }
    if intencao == "convenio":
        convenios = normalizar_lista_campo(unidade.get("convenios"))
        if convenios:
            lista = "\n".join([f"• {c}" for c in convenios])
            return {"tipo": "texto", "resposta": f"✅ A unidade *{unidade.get('nome', slug)}* trabalha com:\n{lista}\n\nSe quiser, também posso te passar os planos da unidade.", "slug": slug, "intencao": intencao}

    if slug and intencao == "llm" and ctx.get("origem") == "mensagem":
        unidade_nome = unidade.get("nome") or slug
        horario_hoje = horario_hoje_formatado(unidade.get("horarios")) if unidade else None
        _extra = f"\n🕒 Hoje: *{horario_hoje}*" if horario_hoje else ""
        return {
            "tipo": "texto",
            "resposta": f"{_abertura_perfeito} Vamos falar da unidade *{unidade_nome}*.{_extra}\n\nMe diz sua dúvida que já te respondo direto 😊",
            "slug": slug,
            "intencao": "contexto_unidade"
        }


    if slug:
        faq = await buscar_resposta_faq(texto_cliente, slug, empresa_id)
        if faq:
            return {"tipo": "texto", "resposta": faq, "slug": slug, "intencao": "faq"}

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
            db_pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=2,
                max_size=10,
                command_timeout=20,
                timeout=10,
            )
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

    worker_tasks = [
        asyncio.create_task(worker_followup(), name="worker_followup"),
        asyncio.create_task(worker_metricas_diarias(), name="worker_metricas_diarias"),
        asyncio.create_task(worker_sync_planos(), name="worker_sync_planos"),
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


def primeiro_nome_cliente(nome: Optional[str]) -> str:
    nome_limpo = limpar_nome(nome) if nome else ""
    if not nome_limpo or nome_limpo.lower() in {"cliente", "contato", "visitante"}:
        return ""
    return nome_limpo.split()[0].capitalize()


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
        linhas.append(f"{emoji} *{nome}*")

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
    """Coleta mensagens do buffer e limpa a fila da conversa."""
    chave_buffet = f"buffet:{conversation_id}"
    async with redis_client.pipeline(transaction=True) as pipe:
        pipe.lrange(chave_buffet, 0, -1)
        pipe.delete(chave_buffet)
        resultado = await pipe.execute()
    mensagens_acumuladas = resultado[0]
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
    raw = await redis_client.get(key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


async def redis_set_json(key: str, value: Any, ttl: int):
    await redis_client.setex(key, ttl, json.dumps(value, default=str))


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

    await redis_set_json(cache_key, planos, 300)
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
    except asyncio.CancelledError:
        logger.info("🛑 worker_followup cancelado")
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
        await redis_set_json(cache_key, data, 300)
        return data
    except asyncpg.PostgresError as e:
        logger.error(f"Erro PostgreSQL ao listar unidades para empresa {empresa_id}: {e}")
        if _PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="db_unidades_lista").inc()
        return []
    except Exception as e:
        logger.error(f"Erro inesperado ao listar unidades: {e}")
        return []


async def buscar_unidade_na_pergunta(texto: str, empresa_id: int, fuzzy_threshold: int = 90) -> Optional[str]:
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

        # Token matching no NOME — exige ≥2 tokens para evitar falso positivo
        # Ex: "Ricardo Jafet" → {"ricardo", "jafet"} ∩ tokens do texto → 2 matches → OK
        _match_nome = _sig(tokens_texto) & _sig(tokens_nome)
        if len(_match_nome) >= 2:
            return u['slug']
        # Para nomes com 1 único token significativo (ex: "Andorinha"),
        # aceita match direto se esse token ≥6 chars (mais específico)
        if len(_match_nome) == 1 and all(len(t) >= 6 for t in _match_nome):
            return u['slug']

        if _sig(tokens_texto) & _sig(tokens_cidade):
            return u['slug']
        if _sig(tokens_texto) & _sig(tokens_bairro):
            return u['slug']

        # Verifica se alguma palavra-chave é um token presente no texto
        for p in palavras_chave:
            tokens_pchave = set(p.split())
            if _sig(tokens_texto) & _sig(tokens_pchave):
                return u['slug']

    # 3. Fuzzy matching conservador — threshold ajustável para evitar falsos positivos
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
            await redis_set_json(cache_key, dados, 300)
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

    cache_key = f"cfg:faq_raw:{slug}:{empresa_id}"
    raw = await redis_client.get(cache_key)
    if raw:
        try:
            faq_rows = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            faq_rows = []
    else:
        try:
            faq_rows_db = await db_pool.fetch("""
                SELECT f.pergunta, f.resposta
                FROM faq f
                JOIN unidades u ON u.id = f.unidade_id
                WHERE u.slug = $1 AND u.empresa_id = $2 AND f.ativo = true
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
    tokens_cliente = {t for t in normalizar(pergunta).split() if len(t) >= 3}
    if not tokens_cliente:
        return None

    melhor_score = 0.0
    melhor_resposta = None

    for item in faq_rows:
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

    # Threshold: pelo menos 40% de sobreposição para aceitar
    if melhor_score >= 0.40 and melhor_resposta:
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
    dados_cache = await redis_get_json(cache_key)
    if dados_cache is not None:
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
    except asyncio.CancelledError:
        logger.info("🛑 worker_metricas_diarias cancelado")
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
    chave_buffet = f"buffet:{conversation_id}"
    watchdog = asyncio.create_task(renovar_lock(chave_lock, lock_val))

    try:
        # ⏱️ Aguarda curto período para acumular mensagens sem sacrificar latência
        await asyncio.sleep(0.8)

        mensagens_acumuladas = await coletar_mensagens_buffer(conversation_id)
        if not mensagens_acumuladas:
            return

        if await aguardar_escolha_unidade_ou_reencaminhar(conversation_id, mensagens_acumuladas):
            return

        anexos = await processar_anexos_mensagens(mensagens_acumuladas)
        textos = anexos["textos"]
        transcricoes = anexos["transcricoes"]
        imagens_urls = anexos["imagens_urls"]
        mensagens_formatadas = anexos["mensagens_formatadas"]

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
        nome_ia = pers.get('nome_ia') or 'Assistente Virtual'

        estado_raw = await redis_client.get(f"estado:{conversation_id}")
        estado_atual = descomprimir_texto(estado_raw) or "neutro"

        texto_norm_fast = normalizar(primeira_mensagem or "")
        resposta_texto = ""
        novo_estado = estado_atual
        fast_reply = None          # str  — mensagem única (resposta fixa, sem LLM)
        fast_reply_lista = None   # List[str] — múltiplas mensagens (ex: planos)
        contexto_precarregado = ""  # Dados buscados do BD — LLM gera a resposta humanizada
        intencao_motor = None

        # Motor principal: factual -> FAQ -> LLM (somente quando necessário)
        texto_cliente_unificado = " ".join([t for t in (textos + transcricoes) if t]).strip()
        if texto_cliente_unificado and not imagens_urls:
            _motor = await gerar_resposta_inteligente(
                conversation_id=conversation_id,
                empresa_id=empresa_id,
                texto_cliente=texto_cliente_unificado,
                slug_atual=slug,
                nome_cliente=nome_cliente,
            )
            intencao_motor = _motor.get("intencao")
            _slug_motor = _motor.get("slug")
            if _slug_motor and _slug_motor != slug:
                slug = _slug_motor
                unidade = await carregar_unidade(slug, empresa_id) or {}
            if _motor.get("tipo") == "texto":
                fast_reply = _motor.get("resposta")
            elif _motor.get("tipo") == "lista":
                fast_reply_lista = _motor.get("resposta") or []

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

        # ==================== FAST-PATH ====================
        # Texto combinado de TODAS as mensagens acumuladas para detectar intenção
        texto_combinado_norm = normalizar(" ".join(textos))

        # Quando o buffer tem MÚLTIPLAS mensagens com intenções diferentes,
        # desabilita o fast-path de intenção única e deixa a IA responder tudo de uma vez.
        # Exceção: detecção de tipo de cliente (aluno/gympass) e saudação sempre rodam.
        _multi_intencao = len(textos) > 1
        _pedido_planos = bool(REGEX_PEDIDO_PLANOS.search(texto_combinado_norm))
        _pedido_end_hor = bool(REGEX_PEDIDO_END_HOR.search(texto_combinado_norm))
        _pedido_contato = bool(REGEX_PEDIDO_CONTATO.search(texto_combinado_norm))

        if not imagens_urls and not fast_reply and not fast_reply_lista:

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

            # Saudação — deixa o LLM gerar resposta dinâmica e natural
            # Apenas informa o contexto (primeiro contato ou retorno)
            elif all(eh_saudacao(t) for t in textos) and textos:
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
                    contexto_precarregado = (
                        "[SAUDAÇÃO DE RETORNO] O cliente já conversou antes.\n"
                        "Responda de forma CURTA e natural — sem se apresentar novamente.\n"
                        "Exemplo: 'E aí, tudo certo? Como posso ajudar? 😊'"
                    )
                    logger.info(f"⚡ Saudação de retorno → LLM vai gerar para {nome_cliente}")
                else:
                    contexto_precarregado = (
                        "[PRIMEIRO CONTATO] O cliente está chegando agora.\n"
                        "Se apresente brevemente (seu nome), seja acolhedor.\n"
                        "Pergunte como pode ajudar — NÃO liste serviços nem empurre planos."
                    )
                    logger.info(f"⚡ Primeiro contato → LLM vai gerar saudação para {nome_cliente}")

            # Fast-path: listar unidades (prioridade ANTES do FAQ)
            # Dado estruturado puro — resposta montada aqui mesmo, sem passar por LLM
            # Funciona mesmo com múltiplas mensagens acumuladas
            elif REGEX_LISTAR_UNIDADES.search(texto_combinado_norm):
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
                            f"📍 Temos {total} {'unidade' if total == 1 else 'unidades'} em {_cidade_filtro}:\n\n"
                            f"{lista_str}\n\n"
                            "Qual delas fica mais perto de você? 😊"
                        )
                    else:
                        fast_reply = random.choice(RESPOSTAS_UNIDADES).format(
                            total=total, lista_str=lista_str
                        )
                    logger.info(f"⚡ Fast-path: {total} unidade(s) — resposta direta (sem LLM)")
                    await bd_registrar_evento_funil(
                        conversation_id, "consulta_unidades",
                        f"Cliente solicitou unidades{' em ' + _cidade_filtro if _cidade_filtro else ''}",
                        score_incremento=1
                    )
                else:
                    fast_reply = "No momento não há unidades cadastradas. 😕"

            # Fast-path: FAQ — último fallback antes da IA
            # Usa texto combinado para funcionar mesmo quando cliente envia 2+ mensagens
            elif slug and not (_pedido_end_hor or _pedido_planos or _pedido_contato):
                _faq_resposta = await buscar_resposta_faq(" ".join(textos), slug, empresa_id)
                if _faq_resposta:
                    contexto_precarregado = (
                        f"[FAQ] Resposta cadastrada para esta pergunta:\n{_faq_resposta}\n\n"
                        "(Use essa resposta como base — pode reformular de forma natural, "
                        "mas não altere informações factuais nem adicione dados inexistentes.)"
                    )
                    logger.info(f"⚡ Fast-path: FAQ encontrado, LLM vai humanizar para conv {conversation_id}")
                    if _PROMETHEUS_OK and hasattr(METRIC_FAST_PATH_TOTAL, 'labels'):
                        METRIC_FAST_PATH_TOTAL.labels(tipo="faq").inc()

            # Fast-path: planos — desabilitado quando há múltiplas mensagens acumuladas
            # (a IA responde todas as perguntas de uma vez de forma mais coesa)
            elif not _multi_intencao and _pedido_planos:
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

            # Fast-path: endereço e/ou horário
            # Detecta cada um independentemente e combina numa resposta só
            elif unidade and _pedido_end_hor:
                _quer_end = bool(re.search(
                    r"(endereco|enderco|localizacao|fica onde|onde fica|como chego|qual o local|onde voces ficam)",
                    texto_combinado_norm
                ))
                _quer_hor = bool(re.search(
                    r"(horario|funcionamento|abre|fecha|que horas|ta aberto|esta aberto)",
                    texto_combinado_norm
                ))

                _partes = []

                if _quer_end and end_banco and str(end_banco).strip().lower() not in ['não informado', 'none', '']:
                    _partes.append(f"📍 Endereço:\n{end_banco}")

                if _quer_hor and hor_banco:
                    _hor_str = formatar_horarios_funcionamento(hor_banco)
                    _partes.append(f"🕒 Horário de funcionamento:\n{_hor_str}")

                if _partes:
                    fast_reply = "\n\n".join(_partes) + "\n\nSe quiser, também posso te ajudar com planos e matrícula. 😊"
                    logger.info("⚡ Fast-path: endereço/horário respondido sem LLM")

            # Fast-path: contato — passa número ao LLM para resposta humanizada
            elif unidade and _pedido_contato:
                if tel_banco and str(tel_banco).strip().lower() not in ['não informado', 'none', '']:
                    fast_reply = random.choice(RESPOSTAS_CONTATO).format(tel_banco=tel_banco)
                    logger.info("⚡ Fast-path: contato respondido sem LLM")
                    await bd_registrar_evento_funil(
                        conversation_id, "solicitacao_telefone",
                        "Cliente solicitou telefone", score_incremento=3
                    )

        # ===================================================

        # Cache: usa chave por intenção APENAS para intenções factuais/estáveis.
        # Nunca usar cache por intenção para "llm"/"saudacao", senão uma resposta
        # genérica (ex: boas-vindas) pode ser repetida para perguntas diferentes.
        intencao = intencao_motor or (detectar_intencao(primeira_mensagem) if primeira_mensagem else None)
        _intencoes_cacheaveis = {
            "horario", "endereco", "telefone", "planos", "unidades",
            "modalidades", "convenio", "faq", "contexto_unidade"
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

UNIDADES DA REDE {nome_empresa.upper()}:
{lista_unidades_nomes}
(Se o cliente perguntar quais unidades existem, liste esses nomes. Para detalhes de endereço/horário de outra unidade, pergunte qual delas ele prefere para você buscar as informações.)

FAQ — RESPOSTAS PRONTAS (USE SEMPRE QUE A PERGUNTA DO CLIENTE SE ENCAIXAR):
{faq}

HISTÓRICO DA CONVERSA
{historico}

REGRAS CRÍTICAS — ANTI-ALUCINAÇÃO (OBRIGATÓRIO):
- Use EXCLUSIVAMENTE as informações presentes em "INFORMAÇÕES DA UNIDADE" acima.
- Se um campo estiver como "não informado", diga que não tem essa informação agora.
- NUNCA invente endereços, telefones, horários ou qualquer dado não informado.
- NUNCA diga que a empresa tem "apenas uma unidade" — você não tem essa informação completa.
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
                if not cliente_ia:
                    resposta_texto = "Estou com uma indisponibilidade técnica no momento. Pode tentar novamente em instantes? 😊"
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
                            max_tokens=1200,  # Margem generosa — prompt pede resposta curta, mas nunca trunca
                                              # Reduz custo e evita erro 402 de crédito insuficiente
                        ),
                        timeout=extra_timeout
                    )

                async with llm_semaphore:
                    try:
                        response = await _chamar_llm(modelo_escolhido, extra_timeout=25)
                        resposta_bruta = response.choices[0].message.content
                        # Detecta resposta truncada por max_tokens
                        _finish = getattr(response.choices[0], 'finish_reason', None)
                        if _finish == "length" and resposta_bruta:
                            logger.warning(f"⚠️ Resposta truncada (finish_reason=length) conv {conversation_id}")
                            # Corta na última frase completa para não enviar frase pela metade
                            for _sep in ['. ', '! ', '? ', '\n']:
                                _pos = resposta_bruta.rfind(_sep)
                                if _pos > len(resposta_bruta) * 0.3:
                                    resposta_bruta = resposta_bruta[:_pos + 1]
                                    break
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

                # 🔧 Pós-processamento: se a IA gerou resposta com múltiplos planos → reformata
                _qtd_precos = resposta_texto.count("R$")
                _qtd_links  = resposta_texto.count("http")
                if planos_ativos and (_qtd_precos >= 2 or _qtd_links >= 2):
                    logger.info("🔧 Pós-processamento: resposta da IA contém planos — reformatando em msgs separadas")
                    fast_reply_lista = formatar_planos_bonito(planos_ativos)
                    resposta_texto = ""
                    if _PROMETHEUS_OK:
                        METRIC_PLANOS_ENVIADOS.inc()

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

                if link_plano in resposta_texto or "matricular" in resposta_texto.lower():
                    await bd_registrar_evento_funil(
                        conversation_id, "link_matricula_enviado", "Link enviado via IA", score_incremento=2
                    )
                if tel_banco and tel_banco in resposta_texto:
                    await bd_registrar_evento_funil(
                        conversation_id, "solicitacao_telefone", "IA forneceu telefone", score_incremento=3
                    )

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

        salvar_resposta_unica = bool(resposta_texto and resposta_texto.strip() and not fast_reply_lista)
        if salvar_resposta_unica:
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
                await bd_salvar_mensagem_local(conversation_id, "assistant", bloco_plano.strip())
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
            # ── Resposta da IA: envia INTEIRA como UMA mensagem ──────────────
            # Split por parágrafo causava frases cortadas no meio ("Uma ótima opção
            # para conhecer..." em mensagem separada). O cliente recebe a resposta
            # completa de uma vez, como um humano digitaria.
            if resposta_texto and resposta_texto.strip():
                _texto_final = garantir_frase_completa(resposta_texto)
                typing_time = min(len(_texto_final) * 0.02, 4.0) + random.uniform(0.3, 0.8)
                await simular_digitacao(account_id, conversation_id, integracao_chatwoot, typing_time)
                await enviar_mensagem_chatwoot(
                    account_id, conversation_id, _texto_final, nome_ia, integracao_chatwoot
                )
                await bd_atualizar_msg_ia(conversation_id)
                await bd_registrar_primeira_resposta(conversation_id)

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

    if not id_conv:
        return {"status": "ignorado_sem_conversation_id"}

    # Rate limiting por conversa
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
            f"prompt_unidade_enviado:{id_conv}",
            f"atend_manual:{id_conv}", f"lock:{id_conv}", f"buffet:{id_conv}"
        )
        logger.info(f"🆕 Nova conversa {id_conv} — Redis limpo")
        return {"status": "conversa_criada"}

    if event == "conversation_updated":
        status_conv = conv_obj.get("status") or payload.get("status")
        if status_conv in {"resolved", "closed"}:
            await bd_finalizar_conversa(id_conv)
            await redis_client.delete(
                f"pause_ia:{id_conv}", f"estado:{id_conv}",
                f"unidade_escolhida:{id_conv}", f"esperando_unidade:{id_conv}",
                f"prompt_unidade_enviado:{id_conv}",
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

        if _tem_geo_wh or esperando_unidade:
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

                # Tenta por nome/cidade/bairro já na primeira mensagem (ex: "ricardo jafet")
                if not slug_detectado:
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
                    # Evita loop de mensagens repetidas quando já pedimos a unidade
                    # (ex.: múltiplos webhooks da mesma conversa em sequência).
                    if esperando_unidade or await redis_client.get(prompt_unidade_key) == "1":
                        logger.info(f"⏭️ Já aguardando unidade para conv {id_conv}, ignorando '{conteudo_texto[:30]}'")
                        return {"status": "aguardando_escolha_unidade"}

                    # Unidade não identificada — pergunta direta, sem saudação fixa
                    msg = (
                        "Me ajuda rapidinho pra eu te atender melhor 😊\n\n"
                        "Qual *cidade* ou *bairro* fica melhor pra você treinar?"
                    )
                    await enviar_mensagem_chatwoot(account_id, id_conv, msg, "Assistente Virtual", integracao)
                    await redis_client.setex(f"esperando_unidade:{id_conv}", 86400, "1")
                    await redis_client.setex(prompt_unidade_key, 600, "1")
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
