import uuid as _uuid
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, date
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.core.config import logger
from src.core.security import get_current_user_token
from src.services.db_queries import _coletar_metricas_unidade, _database, listar_unidades_ativas


class CriarUnidadeRequest(BaseModel):
    nome: str
    nome_abreviado: Optional[str] = None
    cidade: Optional[str] = None
    bairro: Optional[str] = None
    estado: Optional[str] = None
    endereco: Optional[str] = None
    numero: Optional[str] = None
    telefone_principal: Optional[str] = None
    whatsapp: Optional[str] = None
    site: Optional[str] = None
    instagram: Optional[str] = None
    link_matricula: Optional[str] = None

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

async def _get_empresa_id_da_unidade(unidade_id: int) -> Optional[int]:
    """Resolve o empresa_id a partir do unidade_id."""
    row = await _database.db_pool.fetchrow(
        "SELECT empresa_id FROM unidades WHERE id = $1", unidade_id
    )
    return row["empresa_id"] if row else None


@router.get("/unidades")
async def get_unidades(
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Lista unidades ativas. admin_master vê todas; outros veem só da sua empresa.
    """
    empresa_id = token_payload.get("empresa_id")
    perfil = token_payload.get("perfil")
    try:
        if perfil == "admin_master" or not empresa_id:
            # Retorna todas as unidades ativas de todas as empresas
            rows = await _database.db_pool.fetch(
                """
                SELECT u.id, u.nome, u.slug, e.nome as empresa_nome
                FROM unidades u
                JOIN empresas e ON e.id = u.empresa_id
                WHERE u.ativa = true
                ORDER BY e.nome, u.nome
                """
            )
            return [
                {"id": r["id"], "nome": r["nome"], "slug": r["slug"], "empresa_nome": r["empresa_nome"]}
                for r in rows
            ]
        unidades = await listar_unidades_ativas(empresa_id)
        return [{"id": u["id"], "nome": u["nome"], "slug": u["slug"]} for u in unidades]
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
    perfil = token_payload.get("perfil")
    if perfil == "admin_master" or not empresa_id:
        empresa_id = await _get_empresa_id_da_unidade(unidade_id)

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
    perfil = token_payload.get("perfil")
    if perfil == "admin_master" or not empresa_id:
        empresa_id = await _get_empresa_id_da_unidade(unidade_id)

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


@router.post("/unidades", status_code=201)
async def criar_unidade(
    body: CriarUnidadeRequest,
    token_payload: dict = Depends(get_current_user_token),
):
    """
    Cria uma unidade vinculada à empresa do usuário logado.
    O empresa_id vem do JWT — o usuário não pode criar unidade em outra empresa.
    """
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada")

    # Gera slug a partir do nome
    slug = re.sub(r"[^a-z0-9]+", "-", body.nome.lower()).strip("-")

    # Garante slug único dentro da empresa
    existing = await _database.db_pool.fetchval(
        "SELECT id FROM unidades WHERE slug = $1 AND empresa_id = $2",
        slug, empresa_id
    )
    if existing:
        slug = f"{slug}-{_uuid.uuid4().hex[:6]}"

    try:
        row = await _database.db_pool.fetchrow(
            """
            INSERT INTO unidades (
                uuid, slug, nome, nome_abreviado,
                cidade, bairro, estado, endereco, numero,
                telefone_principal, whatsapp,
                site, instagram, link_matricula,
                empresa_id, ativa, created_at
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, $7, $8, $9,
                $10, $11,
                $12, $13, $14,
                $15, true, NOW()
            ) RETURNING id, slug, nome
            """,
            str(_uuid.uuid4()), slug, body.nome, body.nome_abreviado,
            body.cidade, body.bairro, body.estado, body.endereco, body.numero,
            body.telefone_principal, body.whatsapp,
            body.site, body.instagram, body.link_matricula,
            empresa_id,
        )
        logger.info(f"✅ Unidade '{body.nome}' criada (id={row['id']}, empresa_id={empresa_id})")
        return {"id": row["id"], "slug": row["slug"], "nome": row["nome"], "empresa_id": empresa_id}
    except Exception as e:
        logger.error(f"Erro ao criar unidade: {e}")
        raise HTTPException(status_code=500, detail="Erro ao criar unidade")


@router.put("/unidades/{unidade_id}")
async def atualizar_unidade(
    unidade_id: int,
    body: CriarUnidadeRequest,
    token_payload: dict = Depends(get_current_user_token),
):
    """
    Atualiza dados de uma unidade. Verifica se pertence à empresa do admin.
    """
    empresa_id = token_payload.get("empresa_id")
    perfil = token_payload.get("perfil")
    
    # Se for admin_master e não tiver empresa_id no token, busca o da unidade
    if perfil == "admin_master" and not empresa_id:
        empresa_id = await _get_empresa_id_da_unidade(unidade_id)

    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não identificada")

    # Verifica se a unidade pertence à empresa
    existing = await _database.db_pool.fetchrow(
        "SELECT id FROM unidades WHERE id = $1 AND empresa_id = $2",
        unidade_id, empresa_id
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Unidade não encontrada ou acesso negado")

    try:
        await _database.db_pool.execute(
            """
            UPDATE unidades SET
                nome = $1, nome_abreviado = $2, cidade = $3, bairro = $4,
                estado = $5, endereco = $6, numero = $7, telefone_principal = $8,
                whatsapp = $9, site = $10, instagram = $11, link_matricula = $12,
                updated_at = NOW()
            WHERE id = $13 AND empresa_id = $14
            """,
            body.nome, body.nome_abreviado, body.cidade, body.bairro,
            body.estado, body.endereco, body.numero, body.telefone_principal,
            body.whatsapp, body.site, body.instagram, body.link_matricula,
            unidade_id, empresa_id
        )
        return {"status": "success", "message": "Unidade atualizada"}
    except Exception as e:
        logger.error(f"Erro ao atualizar unidade: {e}")
        raise HTTPException(status_code=500, detail="Erro ao atualizar unidade")


@router.delete("/unidades/{unidade_id}")
async def excluir_unidade(
    unidade_id: int,
    token_payload: dict = Depends(get_current_user_token),
):
    """
    Desativa uma unidade (soft delete setando ativa=false).
    """
    empresa_id = token_payload.get("empresa_id")
    perfil = token_payload.get("perfil")
    
    if perfil == "admin_master" and not empresa_id:
        empresa_id = await _get_empresa_id_da_unidade(unidade_id)

    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não identificada")

    try:
        # Usamos soft delete para evitar quebra de logs/histórico
        await _database.db_pool.execute(
            "UPDATE unidades SET ativa = false, updated_at = NOW() WHERE id = $1 AND empresa_id = $2",
            unidade_id, empresa_id
        )
        return {"status": "success", "message": "Unidade desativada"}
    except Exception as e:
        logger.error(f"Erro ao excluir unidade: {e}")
        raise HTTPException(status_code=500, detail="Erro ao excluir unidade")
