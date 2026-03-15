from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Dict, Any
from datetime import datetime, date
from zoneinfo import ZoneInfo
from src.core.config import logger
from src.core.security import get_current_user_token
from src.services.db_queries import _coletar_metricas_unidade, _database, listar_unidades_ativas

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("/unidades")
async def get_unidades(
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Lista todas as unidades ativas da empresa do usuário.
    """
    empresa_id = token_payload.get("empresa_id")
    try:
        unidades = await listar_unidades_ativas(empresa_id)
        # Retornamos apenas os campos necessários para o seletor
        return [
            {"id": u["id"], "nome": u["nome"], "slug": u["slug"]}
            for u in unidades
        ]
    except Exception as e:
        logger.error(f"Erro ao listar unidades para dashboard: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar lista de unidades")

@router.get("/metrics")
async def get_metrics(
    unidade_id: int = Query(..., description="ID da unidade para filtrar métricas"),
    data: date = Query(None, description="Data base para métricas (YYYY-MM-DD)"),
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Retorna as métricas consolidadas de uma unidade para uma data específica.
    """
    empresa_id = token_payload.get("empresa_id")
    # Verificação básica de permissão: usuário comum só vê dados da sua empresa
    # (Futuramente podemos refinar por unidade_id se o perfil for 'atendente')
    
    hoje = data or datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    
    try:
        metrics = await _coletar_metricas_unidade(empresa_id, unidade_id, hoje)
        return {
            "status": "success",
            "date": hoje.isoformat(),
            "unidade_id": unidade_id,
            "metrics": metrics
        }
    except Exception as e:
        logger.error(f"Erro ao buscar métricas para dashboard: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao processar métricas")

@router.get("/conversations")
async def get_recent_conversations(
    unidade_id: int = Query(..., description="ID da unidade"),
    limit: int = Query(10, le=50),
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Retorna a lista de conversas mais recentes com seus scores e intensões.
    """
    empresa_id = token_payload.get("empresa_id")
    
    try:
        query = """
            SELECT conversation_id, contato_nome, contato_fone, score_lead, 
                   lead_qualificado, intencao_de_compra, updated_at, status
            FROM conversas
            WHERE empresa_id = $1 AND unidade_id = $2
            ORDER BY updated_at DESC
            LIMIT $3
        """
        rows = await _database.db_pool.fetch(query, empresa_id, unidade_id, limit)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Erro ao listar conversas para dashboard: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar histórico de conversas")
