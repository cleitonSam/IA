"""
[INF-10] Inicialização do Sentry para error tracking.

Uso em main.py, antes de criar o app FastAPI:

    from src.core.sentry_init import init_sentry
    init_sentry()
    app = FastAPI(...)

Variáveis de ambiente:
  SENTRY_DSN                     (se vazio, Sentry fica desabilitado)
  SENTRY_ENVIRONMENT             (dev/staging/prod; default = APP_MODE)
  SENTRY_TRACES_SAMPLE_RATE      (0.0 a 1.0; default 0.1)
  SENTRY_RELEASE                 (commit sha; opcional)
"""

import os
from src.core.config import (
    logger, SENTRY_DSN, SENTRY_ENVIRONMENT, SENTRY_TRACES_SAMPLE_RATE,
)


def init_sentry() -> bool:
    """Inicializa Sentry se DSN estiver definido. Retorna True se habilitado."""
    if not SENTRY_DSN:
        logger.info("[INF-10] SENTRY_DSN não definido — error tracking desabilitado")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.asyncio import AsyncioIntegration
        from sentry_sdk.integrations.redis import RedisIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        logger.warning(
            "[INF-10] sentry-sdk não instalado. "
            "Adicione 'sentry-sdk[fastapi]>=1.40.0' ao requirements.txt"
        )
        return False

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=SENTRY_ENVIRONMENT,
        release=os.getenv("SENTRY_RELEASE") or os.getenv("GIT_SHA") or None,
        traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
        profiles_sample_rate=0.0,
        send_default_pii=False,  # LGPD — nao envia IP/user id automaticamente
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            AsyncioIntegration(),
            RedisIntegration(),
            LoggingIntegration(level=None, event_level=None),
        ],
        before_send=_scrub_pii,
    )
    logger.info(f"[INF-10] Sentry habilitado (env={SENTRY_ENVIRONMENT})")
    return True


def _scrub_pii(event, hint):
    """Remove telefones/emails dos payloads antes de enviar ao Sentry (LGPD)."""
    import re
    PHONE_RE = re.compile(r"\b\d{10,13}\b")
    EMAIL_RE = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b")

    def _scrub(v):
        if isinstance(v, str):
            v = PHONE_RE.sub("[PHONE_REDACTED]", v)
            v = EMAIL_RE.sub("[EMAIL_REDACTED]", v)
            return v
        if isinstance(v, dict):
            return {k: _scrub(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_scrub(x) for x in v]
        return v

    try:
        if "message" in event:
            event["message"] = _scrub(event["message"])
        if "exception" in event and "values" in event["exception"]:
            for val in event["exception"]["values"]:
                if "value" in val:
                    val["value"] = _scrub(val["value"])
        if "extra" in event:
            event["extra"] = _scrub(event["extra"])
    except Exception:
        pass
    return event
