"""
main.py — Entry point for Motor SaaS IA

Thin wrapper that:
1. Creates FastAPI app with CORS
2. Registers all routers (auth, dashboard, management, webhooks, ws)
3. Runs Alembic migrations on startup
4. Delegates lifecycle to bot_core.startup_event / shutdown_event
5. Exposes system endpoints (/metrics, /status, /metricas/diagnostico, /sync-planos)
"""
import os
import sys
import asyncio

# Garante que o diretório raiz esteja no sys.path para imports modularizados
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.append(_root)

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import (
    logger, FRONTEND_URL, APP_VERSION,
    PROMETHEUS_OK, generate_latest, CONTENT_TYPE_LATEST,
)

# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI()

# ── CORS ─────────────────────────────────────────────────────────────────────

_cors_origins = list({o for o in [FRONTEND_URL, "http://localhost:3000"] if o})
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────

from src.api.routers.auth import router as auth_router
from src.api.routers.dashboard import router as dashboard_router
from src.api.routers.management import router as management_router
from src.api.routers.uaz_webhook import router as uaz_webhook_router
from src.api.routers.ws import router as ws_router
from src.api.routers.webhook import router as webhook_router

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(management_router)
app.include_router(uaz_webhook_router)
app.include_router(ws_router)
app.include_router(webhook_router)

# ── Rate Limit Middleware ────────────────────────────────────────────────────

from src.services.bot_core import rate_limit_middleware

app.middleware("http")(rate_limit_middleware)

# ── Lifecycle ────────────────────────────────────────────────────────────────

from src.services.bot_core import startup_event, shutdown_event


@app.on_event("startup")
async def _startup():
    # Run Alembic migrations before initializing services
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command as alembic_command

        alembic_cfg = AlembicConfig("alembic.ini")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: alembic_command.upgrade(alembic_cfg, "heads")
        )
        logger.info("✅ Migrations aplicadas com sucesso (alembic upgrade heads)")
    except Exception as e:
        logger.warning(f"⚠️ Falha ao aplicar migrations: {e}")

    await startup_event()


@app.on_event("shutdown")
async def _shutdown():
    await shutdown_event()


# ── System Endpoints ─────────────────────────────────────────────────────────

from src.services.bot_core import (
    metrics_endpoint as _metrics,
    metricas_diagnostico as _diagnostico,
    status_endpoint as _status,
)
from src.services.workers import sync_planos_manual as _sync_planos
from typing import Optional


@app.get("/sync-planos/{empresa_id}")
async def sync_planos(empresa_id: int):
    return await _sync_planos(empresa_id)


@app.get("/metrics")
async def metrics():
    return await _metrics()


@app.get("/metricas/diagnostico")
async def metricas_diagnostico(
    empresa_id: Optional[int] = None,
    data: Optional[str] = None,
    dias: int = 7,
):
    return await _diagnostico(empresa_id=empresa_id, data=data, dias=dias)


@app.get("/status")
async def status():
    return await _status()


# ── Health Check ─────────────────────────────────────────────────────────────


@app.get("/")
@app.head("/")
async def health():
    return {"status": "ok", "service": "Motor SaaS IA", "version": APP_VERSION}
