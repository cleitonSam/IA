"""
[MKT-01/07] Router de leads e ROI — endpoints consumidos pelo dashboard.

Endpoints:
  GET  /api/leads/tier/{A|B|C|D}         — lista leads por tier
  POST /api/leads/{conv_id}/rescore      — recalcula score de uma conversa
  GET  /api/leads/stats                  — total por tier (para cards)

  GET  /api/alertas                      — alertas abertos de sentimento/escalacao
  POST /api/alertas/{id}/resolver        — marca alerta como resolvido

  GET  /api/roi                          — dashboard de ROI por periodo
  POST /api/roi/matricula                — registra matricula (webhook do ERP)
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.core.tenant import require_tenant
from src.services.lead_scoring import (
    score_conversa, listar_leads_por_tier, tier_from_score,
)
from src.services.sentiment_realtime import (
    listar_alertas_abertos, resolver_alerta,
)
from src.services.roi_attribution import (
    record_matricula, compute_roi,
)


router = APIRouter(prefix="/api/leads", tags=["leads"])


# ============================================================
# Leads
# ============================================================

@router.get("/tier/{tier}")
async def api_leads_por_tier(
    tier: str,
    limit: int = 50,
    tenant: dict = Depends(require_tenant),
):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    tier = tier.upper()
    if tier not in {"A", "B", "C", "D"}:
        raise HTTPException(status_code=400, detail="tier invalido")
    leads = await listar_leads_por_tier(empresa_id, tier=tier, limit=min(limit, 200))
    for lead in leads:
        lead["tier"] = tier_from_score(lead.get("score_lead") or 0)
    return {"tier": tier, "total": len(leads), "leads": leads}


@router.post("/{conversation_id}/rescore")
async def api_rescore(conversation_id: int, tenant: dict = Depends(require_tenant)):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    result = await score_conversa(
        conversation_id=conversation_id,
        empresa_id=empresa_id,
        use_cache=False,
        persist=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="conversa nao encontrada ou erro")
    return {
        "conversation_id": result.conversation_id,
        "score": result.score,
        "tier": result.tier,
        "explicacao": result.explicacao,
    }


@router.get("/stats")
async def api_stats(tenant: dict = Depends(require_tenant)):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    stats = {}
    for t in ("A", "B", "C", "D"):
        leads = await listar_leads_por_tier(empresa_id, tier=t, limit=500)
        stats[t] = len(leads)
    return {"empresa_id": empresa_id, "tiers": stats, "total": sum(stats.values())}


# ============================================================
# Alertas
# ============================================================

alertas_router = APIRouter(prefix="/api/alertas", tags=["alertas"])


@alertas_router.get("")
async def api_alertas(
    severidade_min: str = "baixa",
    limit: int = 100,
    tenant: dict = Depends(require_tenant),
):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    items = await listar_alertas_abertos(empresa_id, severidade_min=severidade_min, limit=min(limit, 500))
    return {"alertas": items, "total": len(items)}


class ResolverRequest(BaseModel):
    observacao: Optional[str] = Field(None, max_length=500)


@alertas_router.post("/{alerta_id}/resolver")
async def api_resolver(
    alerta_id: int,
    body: ResolverRequest,
    tenant: dict = Depends(require_tenant),
):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    ok = await resolver_alerta(
        alerta_id=alerta_id,
        empresa_id=empresa_id,
        resolvido_por=tenant.get("email") or "system",
        observacao=body.observacao,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="alerta nao encontrado")
    return {"resolved": True, "id": alerta_id}


# ============================================================
# ROI
# ============================================================

roi_router = APIRouter(prefix="/api/roi", tags=["roi"])


class MatriculaRequest(BaseModel):
    contato_fone: str = Field(..., min_length=8, max_length=30)
    plano: Optional[str] = Field(None, max_length=100)
    valor_mensal: float = Field(0.0, ge=0)
    lookback_dias: int = Field(30, ge=1, le=90)


@roi_router.get("")
async def api_roi_dashboard(
    periodo_dias: int = 30,
    custo_mensal_bot_brl: float = 0.0,
    tenant: dict = Depends(require_tenant),
):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    data = await compute_roi(
        empresa_id=empresa_id,
        periodo_dias=min(max(periodo_dias, 1), 365),
        custo_mensal_bot_brl=max(0.0, custo_mensal_bot_brl),
    )
    return data


@roi_router.post("/matricula")
async def api_record_matricula(
    body: MatriculaRequest,
    tenant: dict = Depends(require_tenant),
):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    result = await record_matricula(
        empresa_id=empresa_id,
        contato_fone=body.contato_fone,
        plano=body.plano,
        valor_mensal=body.valor_mensal,
        lookback_dias=body.lookback_dias,
    )
    return result
