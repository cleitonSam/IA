import uuid as _uuid
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, date
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel

from src.core.config import logger
from src.core.security import get_current_user_token
from src.core.redis_client import redis_client
import json
from src.services.db_queries import _coletar_metricas_unidade, _database, listar_unidades_ativas
from src.utils.imagekit import upload_to_imagekit


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
    horarios: Optional[Any] = None
    modalidades: Optional[Any] = None
    planos: Optional[Any] = None
    formas_pagamento: Optional[Any] = None
    convenios: Optional[Any] = None
    infraestrutura: Optional[Any] = None
    servicos: Optional[Any] = None
    palavras_chave: Optional[Any] = None
    foto_grade: Optional[str] = None
    link_tour_virtual: Optional[str] = None

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
        if perfil == "admin_master":
            # Retorna todas as unidades ativas de todas as empresas (legítimo para admin_master)
            rows = await _database.db_pool.fetch(
                """
                SELECT u.id, u.nome, u.slug, e.nome as empresa_nome
                FROM unidades u
                JOIN empresas e ON e.id = u.empresa_id
                WHERE u.ativa = true
                ORDER BY e.nome, u.nome
                """
            )
            return [dict(r) for r in rows]

        if not empresa_id:
            raise HTTPException(status_code=400, detail="Empresa não vinculada ao usuário")

        unidades = await listar_unidades_ativas(empresa_id)
        return [{"id": u["id"], "nome": u["nome"], "slug": u["slug"]} for u in unidades]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao listar unidades para dashboard: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar lista de unidades")

@router.get("/metrics")
async def get_metrics(
    unidade_id: int = Query(..., description="ID da unidade para filtrar métricas"),
    days: int = Query(30, description="Número de dias retroativos (padrão 30)"),
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Retorna as métricas consolidadas de uma unidade para um período.
    Por padrão usa os últimos 30 dias para que o dashboard sempre exiba dados.
    """
    empresa_id = token_payload.get("empresa_id")
    perfil = token_payload.get("perfil")
    if perfil == "admin_master" or not empresa_id:
        empresa_id = await _get_empresa_id_da_unidade(unidade_id)
    if not empresa_id:
        raise HTTPException(status_code=404, detail="Unidade não encontrada")

    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()

    try:
        # Busca dados agregados dos últimos `days` dias
        where_date = "DATE(c.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3"
        params_date = [empresa_id, unidade_id, hoje]
        if days > 1:
            where_date = "DATE(c.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') BETWEEN ($3::date - ($4 * interval '1 day')) AND $3"
            params_date = [empresa_id, unidade_id, hoje, days]

        row = await _database.db_pool.fetchrow(f"""
            SELECT
                COUNT(DISTINCT c.id)                                                      AS total_conversas,
                COUNT(DISTINCT CASE WHEN c.lead_qualificado THEN c.id END)               AS leads_qualificados,
                COUNT(DISTINCT CASE WHEN c.intencao_de_compra THEN c.id END)             AS intencao_compra,
                COALESCE(AVG(
                    EXTRACT(EPOCH FROM (c.primeira_resposta_em - c.primeira_mensagem))
                ) FILTER (WHERE c.primeira_resposta_em IS NOT NULL AND c.primeira_mensagem IS NOT NULL), 0) AS tempo_medio_resposta,
                COUNT(DISTINCT CASE WHEN c.status IN ('encerrada','resolved','closed') THEN c.id END) AS conversas_encerradas
            FROM conversas c
            WHERE c.empresa_id = $1 AND c.unidade_id = $2
              AND {where_date}
        """, *params_date)

        # Eventos funil
        row_funil = await _database.db_pool.fetchrow(f"""
            SELECT
                COUNT(DISTINCT CASE WHEN ef.tipo_evento = 'link_matricula_enviado' THEN ef.conversa_id END) AS total_links_enviados,
                COUNT(DISTINCT CASE WHEN ef.tipo_evento = 'plano_exibido' THEN ef.conversa_id END)          AS total_planos_enviados,
                COUNT(DISTINCT CASE WHEN ef.tipo_evento IN ('matricula_realizada','checkout_concluido') THEN ef.conversa_id END) AS total_matriculas
            FROM eventos_funil ef
            JOIN conversas c ON c.id = ef.conversa_id
            WHERE c.empresa_id = $1 AND c.unidade_id = $2
              AND {where_date}
        """, *params_date)

        metrics = dict(row) if row else {}
        funil = dict(row_funil) if row_funil else {}
        total_conv = metrics.get("total_conversas") or 0
        leads = metrics.get("leads_qualificados") or 0
        metrics["taxa_conversao"] = round((leads / total_conv * 100), 1) if total_conv > 0 else 0.0
        metrics["tempo_medio_resposta"] = round(float(metrics.get("tempo_medio_resposta") or 0), 1)
        metrics["total_links_enviados"] = funil.get("total_links_enviados") or 0
        metrics["total_planos_enviados"] = funil.get("total_planos_enviados") or 0
        metrics["total_matriculas"] = funil.get("total_matriculas") or 0

        return {
            "status": "success",
            "date": hoje.isoformat(),
            "days": days,
            "unidade_id": unidade_id,
            "metrics": metrics
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao buscar métricas para dashboard: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar métricas")

@router.get("/conversations")
async def get_conversations(
    unidade_id: Optional[int] = Query(None, description="Filtrar por unidade (omitir = todas da empresa)"),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    status: Optional[str] = Query(None, description="Filtro de status: open, resolved, closed"),
    busca: Optional[str] = Query(None, description="Busca por nome ou telefone"),
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Lista conversas da empresa com paginação e filtros.
    """
    empresa_id = token_payload.get("empresa_id")
    perfil = token_payload.get("perfil")
    if perfil == "admin_master" and not empresa_id and unidade_id:
        empresa_id = await _get_empresa_id_da_unidade(unidade_id)
    if not empresa_id:
        raise HTTPException(status_code=404, detail="Unidade não encontrada")

    conditions = ["c.empresa_id = $1"]
    params: list = [empresa_id]

    if unidade_id:
        params.append(unidade_id)
        conditions.append(f"c.unidade_id = ${len(params)}")

    if status:
        params.append(status)
        conditions.append(f"c.status = ${len(params)}")

    if busca:
        params.append(f"%{busca}%")
        conditions.append(f"(c.contato_nome ILIKE ${len(params)} OR c.contato_fone ILIKE ${len(params)} OR c.contato_telefone ILIKE ${len(params)})")

    where = " AND ".join(conditions)

    try:
        query = f"""
            SELECT c.id, c.conversation_id, c.contato_nome, c.contato_fone, c.contato_telefone,
                   c.score_lead, c.lead_qualificado, c.intencao_de_compra, c.status,
                   c.updated_at, c.created_at, c.total_mensagens_cliente, c.total_mensagens_ia,
                   c.resumo_ia, c.canal, u.nome as unidade_nome
            FROM conversas c
            LEFT JOIN unidades u ON u.id = c.unidade_id
            WHERE {where}
            ORDER BY c.updated_at DESC
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
        """
        params.extend([limit, offset])
        rows = await _database.db_pool.fetch(query, *params)

        total_query = f"SELECT COUNT(*) FROM conversas c WHERE {where}"
        total = await _database.db_pool.fetchval(total_query, *params[:-2])

        result_data = []
        for r in rows:
            d = dict(r)
            # Verifica se a IA está pausada no Redis
            d["pausada"] = await redis_client.exists(f"pause_ia:{empresa_id}:{d['conversation_id']}")
            result_data.append(d)

        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "data": result_data
        }
    except Exception as e:
        logger.error(f"Erro ao listar conversas: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar conversas")


@router.post("/conversations/{conversation_id}/toggle-ia")
async def toggle_ia_conversation(
    conversation_id: int,
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Alterna o status da IA (Ativa/Pausada) para uma conversa específica.
    """
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não identificada")

    # Verifica se a conversa pertence à empresa
    exists = await _database.db_pool.fetchval(
        "SELECT id FROM conversas WHERE conversation_id = $1 AND empresa_id = $2",
        conversation_id, empresa_id
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Conversa não encontrada ou sem permissão")

    key = f"pause_ia:{empresa_id}:{conversation_id}"
    if await redis_client.exists(key):
        await redis_client.delete(key)
        return {"status": "ativa", "pausada": False}
    else:
        # Pausa por 24h (ou até ser reativada)
        await redis_client.setex(key, 86400, "1")
        return {"status": "pausada", "pausada": True}


@router.post("/conversations/{conversation_id}/resumo")
async def manual_summary_conversation(
    conversation_id: int,
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Gera o Resumo Neural manualmente para uma conversa específica.
    """
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não identificada")

    # Verifica se a conversa pertence à empresa
    row = await _database.db_pool.fetchrow(
        "SELECT id FROM conversas WHERE conversation_id = $1 AND empresa_id = $2",
        conversation_id, empresa_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Conversa não encontrada ou sem permissão")

    from src.services.workers import gerar_resumo_conversa
    resumo = await gerar_resumo_conversa(row['id'], conversation_id, empresa_id)
    
    return {"status": "success", "resumo_ia": resumo}


@router.get("/metrics/empresa")
async def get_metrics_empresa(
    data: Optional[date] = Query(None),
    days: int = Query(30, description="Número de dias para retroceder (padrão 30)"),
    empresa_id_param: Optional[int] = Query(None, alias="empresa_id", description="Filtrar por empresa (admin_master only)"),
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Retorna métricas agregadas de TODAS as unidades da empresa para um período.
    admin_master sem empresa_id no token agrega TODAS as empresas (ou filtra por empresa_id query param).
    """
    empresa_id = token_payload.get("empresa_id")
    perfil = token_payload.get("perfil")
    is_admin_master = perfil == "admin_master"

    # admin_master pode não ter empresa_id no token — usa query param ou agrega tudo
    if not empresa_id:
        if is_admin_master:
            empresa_id = empresa_id_param  # pode ser None = agrega tudo
        else:
            raise HTTPException(status_code=400, detail="Empresa não identificada")

    hoje = data or datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    try:
        # Monta filtro de empresa_id e datas dinamicamente
        # Os índices dos parâmetros mudam dependendo se há empresa_id
        if empresa_id:
            empresa_cond = "c.empresa_id = $1 AND"
            unit_empresa_cond = "u.empresa_id = $1 AND"
            params: list = [empresa_id, hoje]
            if days > 1:
                where_date = "DATE(c.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') BETWEEN ($2::date - ($3 * interval '1 day')) AND $2"
                params.append(days)
            else:
                where_date = "DATE(c.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $2"
        else:
            # admin_master sem filtro de empresa — agrega TODAS as empresas
            empresa_cond = ""
            unit_empresa_cond = ""
            params = [hoje]
            if days > 1:
                where_date = "DATE(c.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') BETWEEN ($1::date - ($2 * interval '1 day')) AND $1"
                params.append(days)
            else:
                where_date = "DATE(c.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $1"

        # 1. Métricas de Conversas e Lead Scoring
        query_totals = f"""
            SELECT
                COUNT(DISTINCT c.id)                                                      AS total_conversas,
                COUNT(DISTINCT CASE WHEN c.lead_qualificado THEN c.id END)               AS leads_qualificados,
                COUNT(DISTINCT CASE WHEN c.intencao_de_compra THEN c.id END)             AS intencao_compra,
                COALESCE(AVG(
                    EXTRACT(EPOCH FROM (c.primeira_resposta_em - c.primeira_mensagem))
                ) FILTER (WHERE c.primeira_resposta_em IS NOT NULL), 0)                   AS tempo_medio_resposta,
                COUNT(DISTINCT CASE WHEN c.status IN ('encerrada','resolved','closed') THEN c.id END) AS conversas_encerradas,
                COUNT(DISTINCT c.unidade_id)                                              AS total_unidades_ativas
            FROM conversas c
            WHERE {empresa_cond}
              {where_date}
        """
        row = await _database.db_pool.fetchrow(query_totals, *params)

        # 2. Métricas de Uso de IA (Tokens e Custos)
        where_ia = where_date.replace("c.", "ui.")
        ia_empresa_cond = empresa_cond.replace("c.", "ui.")
        query_ia = f"""
            SELECT
                COALESCE(SUM(tokens_prompt + tokens_completion), 0) as total_tokens,
                COALESCE(SUM(custo_usd), 0) as custo_total
            FROM uso_ia ui
            WHERE {ia_empresa_cond}
              {where_ia}
        """
        row_ia = await _database.db_pool.fetchrow(query_ia, *params)

        # 3. Distribuição por Unidade
        query_units = f"""
            SELECT
                u.id, u.nome,
                COUNT(DISTINCT c.id)                                             AS total_conversas,
                COUNT(DISTINCT CASE WHEN c.lead_qualificado THEN c.id END)      AS leads_qualificados,
                COUNT(DISTINCT CASE WHEN c.intencao_de_compra THEN c.id END)    AS intencao_compra
            FROM unidades u
            LEFT JOIN conversas c ON c.unidade_id = u.id
                AND {where_date}
            WHERE {unit_empresa_cond} u.ativa = true
            GROUP BY u.id, u.nome
            ORDER BY total_conversas DESC
        """
        units_rows = await _database.db_pool.fetch(query_units, *params)

        total = dict(row) if row else {}
        ia_data = dict(row_ia) if row_ia else {"total_tokens": 0, "custo_total": 0}
        
        total_conv = total.get("total_conversas") or 0
        leads = total.get("leads_qualificados") or 0
        total["taxa_conversao"] = round((leads / total_conv * 100), 1) if total_conv > 0 else 0
        total["tempo_medio_resposta"] = round(float(total.get("tempo_medio_resposta") or 0), 1)
        
        # Merge AI data
        total["total_tokens"] = ia_data["total_tokens"]
        total["custo_total_usd"] = round(float(ia_data["custo_total"]), 4)

        return {
            "date": hoje.isoformat(),
            "days": days,
            "totals": total,
            "por_unidade": [dict(r) for r in units_rows]
        }
    except Exception as e:
        logger.error(f"Erro ao buscar métricas da empresa: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar métricas da empresa")


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
                uuid, empresa_id, slug, nome, nome_abreviado, cidade, bairro,
                estado, endereco, numero, telefone_principal, whatsapp, site,
                instagram, link_matricula, horarios, modalidades, planos,
                formas_pagamento, convenios, infraestrutura, servicos, palavras_chave,
                foto_grade, link_tour_virtual, ativa, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25,
                true, NOW(), NOW()
            )
            RETURNING id
            """,
            str(_uuid.uuid4()), empresa_id, slug, body.nome, body.nome_abreviado,
            body.cidade, body.bairro, body.estado, body.endereco, body.numero,
            body.telefone_principal, body.whatsapp, body.site, body.instagram,
            body.link_matricula, body.horarios, body.modalidades,
            body.planos or {}, body.formas_pagamento or {}, body.convenios or {},
            body.infraestrutura or {}, body.servicos or {}, body.palavras_chave or [],
            body.foto_grade, body.link_tour_virtual
        )
        from src.core.redis_client import redis_client
        await redis_client.delete(f"cfg:unidades:lista:empresa:{empresa_id}")
        logger.info(f"✅ Unidade '{body.nome}' criada (id={row['id']}, empresa_id={empresa_id})")
        return {"id": row["id"], "slug": slug, "nome": body.nome, "empresa_id": empresa_id}
    except Exception as e:
        logger.error(f"Erro ao criar unidade: {e}")
        raise HTTPException(status_code=500, detail="Erro ao criar unidade")

@router.post("/unidades/upload")
async def upload_unidade_foto(
    file: UploadFile = File(...),
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Realiza o upload de uma imagem para o ImageKit.
    Retorna a URL da imagem.
    """
    # Validação simples de tipo
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="O arquivo deve ser uma imagem")
    
    try:
        content = await file.read()
        url = await upload_to_imagekit(content, file.filename)
        if not url:
            raise HTTPException(status_code=500, detail="Erro ao fazer upload para o ImageKit")
        
        return {"url": url}
    except Exception as e:
        logger.error(f"Erro no endpoint de upload: {e}")
        raise HTTPException(status_code=500, detail="Erro interno no upload")


@router.get("/unidades/{unidade_id}")
async def get_unidade(
    unidade_id: int,
    token_payload: dict = Depends(get_current_user_token),
):
    """
    Retorna dados completos de uma unidade para edição.
    """
    empresa_id = token_payload.get("empresa_id")
    perfil = token_payload.get("perfil")

    if perfil == "admin_master" and not empresa_id:
        empresa_id = await _get_empresa_id_da_unidade(unidade_id)

    row = await _database.db_pool.fetchrow(
        """
        SELECT id, nome, nome_abreviado, cidade, bairro, estado,
               endereco, numero, telefone_principal, whatsapp,
               site, instagram, link_matricula, slug, ativa,
               horarios, modalidades, planos, formas_pagamento,
               convenios, infraestrutura, servicos, palavras_chave, foto_grade, link_tour_virtual
        FROM unidades
        WHERE id = $1 AND empresa_id = $2
        """,
        unidade_id, empresa_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Unidade não encontrada")
    return dict(row)


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
                horarios = $13, modalidades = $14, planos = $15, 
                formas_pagamento = $16, convenios = $17, infraestrutura = $18,
                servicos = $19, palavras_chave = $20, foto_grade = $21, link_tour_virtual = $22,
                updated_at = NOW()
            WHERE id = $23 AND empresa_id = $24
            """,
            body.nome, body.nome_abreviado, body.cidade, body.bairro,
            body.estado, body.endereco, body.numero, body.telefone_principal,
            body.whatsapp, body.site, body.instagram, body.link_matricula,
            body.horarios, body.modalidades, body.planos or {}, 
            body.formas_pagamento or {}, body.convenios or {}, body.infraestrutura or {},
            body.servicos or {}, body.palavras_chave or [], body.foto_grade, body.link_tour_virtual,
            unidade_id, empresa_id
        )
        from src.core.redis_client import redis_client
        await redis_client.delete(f"cfg:unidades:lista:empresa:{empresa_id}")
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
        from src.core.redis_client import redis_client
        await redis_client.delete(f"cfg:unidades:lista:empresa:{empresa_id}")
        return {"status": "success", "message": "Unidade desativada"}
    except Exception as e:
        logger.error(f"Erro ao excluir unidade: {e}")
        raise HTTPException(status_code=500, detail="Erro ao excluir unidade")
