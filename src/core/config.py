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
except (ImportError, ValueError):
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
    
    # Métricas de Fila (Redis Streams)
    METRIC_QUEUE_SIZE       = Gauge("saas_queue_size", "Tamanho atual da fila de mensagens")
    METRIC_WORKER_LATENCY   = Histogram("saas_worker_latency_seconds", "Tempo total de processamento no worker",
                                         buckets=[1, 2, 5, 10, 30, 60])
    METRIC_WORKER_PROCESSED = Counter("saas_worker_messages_total", "Total de mensagens processadas pelo worker", ["status"])
except (ImportError, ValueError):
    PROMETHEUS_OK = False
    generate_latest = None
    CONTENT_TYPE_LATEST = None
    METRIC_WEBHOOKS_TOTAL = None
    METRIC_IA_LATENCY = None
    METRIC_FAST_PATH_TOTAL = None
    METRIC_ERROS_TOTAL = None
    METRIC_CONVERSAS_ATIVAS = None
    METRIC_PLANOS_ENVIADOS = None
    METRIC_ALUNO_DETECTADO = None
    METRIC_QUEUE_SIZE = None
    METRIC_WORKER_LATENCY = None
    METRIC_WORKER_PROCESSED = None

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

# --- DASHBOARD SECURITY ---
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY não definido — defina uma chave secreta segura como variável de ambiente")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 1440)) # 24h

EMPRESA_ID_PADRAO = 1
APP_VERSION = "2.5.0"

# --- EMAIL / SMTP ---
SMTP_ADDRESS = os.getenv("SMTP_ADDRESS", "smtp.hostinger.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
MAILER_SENDER_EMAIL = os.getenv("MAILER_SENDER_EMAIL", "Antigravity IA <ti@fluxodigitaltech.com.br>")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
APP_MODE = os.getenv("APP_MODE", "both").lower()  # api, worker, both

# --- GOOGLE (Gemini TTS) ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# --- IMAGEKIT ---
IMAGEKIT_ID = os.getenv("IMAGEKIT_ID", "")
IMAGEKIT_PUBLIC_KEY = os.getenv("IMAGEKIT_PUBLIC_KEY", "")
IMAGEKIT_PRIVATE_KEY = os.getenv("IMAGEKIT_PRIVATE_KEY", "")
IMAGEKIT_URL_ENDPOINT = f"https://ik.imagekit.io/{IMAGEKIT_ID}/" if IMAGEKIT_ID else ""
