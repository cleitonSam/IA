from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

# Importações globais do Core Services
from src.core.config import APP_VERSION
from src.services.bot_core import startup_event, shutdown_event, rate_limit_middleware

# Importações dos novos Roteadores do Motor SaaS
from src.api.routers.system import router as system_router
from src.api.routers.webhook import router as webhook_router
from src.api.routers.uaz_webhook import router as uaz_webhook_router
from src.api.routers.auth import router as auth_router
from src.api.routers.dashboard import router as dashboard_router
from src.api.routers.management import router as management_router

# Inicialização limpa e abstrata do FastAPI
app = FastAPI(title="Motor SaaS IA Gym", version=APP_VERSION, docs_url=None, redoc_url=None)

# Filtro de CORS básico
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware HTTP centralizado extraído do bot_core
@app.middleware("http")
async def main_rate_limit(request: Request, call_next):
    return await rate_limit_middleware(request, call_next)

# Registro de Eventos da Aplicação
app.add_event_handler("startup", startup_event)
app.add_event_handler("shutdown", shutdown_event)

# Injeção de Dependências - Roteadores
app.include_router(webhook_router, tags=["Webhooks Chatwoot"])
app.include_router(uaz_webhook_router, tags=["Webhooks UazAPI"])
app.include_router(system_router, tags=["Sistema Base SaaS"])
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(management_router)

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
