import os
import logging
from dotenv import load_dotenv

load_dotenv()

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
    PROMETHEUS_OK = True

    METRIC_WEBHOOKS_TOTAL  = Counter("saas_webhooks_total",  "Total de webhooks recebidos", ["event"])
    METRIC_IA_LATENCY      = Histogram("saas_ia_latency_seconds", "Latência do LLM em segundos",
                                        buckets=[0.5, 1, 2, 5, 10, 30])
    METRIC_FAST_PATH_TOTAL = Counter("saas_fast_path_total", "Respostas via fast-path", ["tipo"])
    METRIC_ERROS_TOTAL     = Counter("saas_erros_total",     "Erros críticos por tipo", ["tipo"])
    METRIC_CONVERSAS_ATIVAS = Gauge("saas_conversas_ativas", "Conversas ativas no Redis")
    METRIC_PLANOS_ENVIADOS  = Counter("saas_planos_enviados_total", "Planos enviados ao cliente")
    METRIC_ALUNO_DETECTADO  = Counter("saas_tipo_cliente_total", "Tipo de cliente detectado", ["tipo"])
except ImportError:
    PROMETHEUS_OK = False

# --- VARIÁVEIS DE AMBIENTE ---
CHATWOOT_URL = os.getenv("CHATWOOT_URL")
CHATWOOT_TOKEN = os.getenv("CHATWOOT_TOKEN")
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
