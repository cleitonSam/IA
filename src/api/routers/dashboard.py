import uuid as _uuid
import re
import json
import base64
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel

from src.core.config import logger
from src.core.security import get_current_user_token
from src.core.redis_client import redis_client
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
        return [{
            "id": u["id"],
            "nome": u["nome"],
            "slug": u["slug"],
            "nome_abreviado": u.get("nome_abreviado"),
            "cidade": u.get("cidade"),
            "bairro": u.get("bairro"),
            "estado": u.get("estado"),
            "whatsapp": u.get("whatsapp"),
            "instagram": u.get("instagram"),
            "convenios": u.get("convenios"),
        } for u in unidades]
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
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
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

        # Batch Redis lookup para evitar N+1 (1 pipeline ao invés de N calls)
        result_data = [dict(r) for r in rows]
        if result_data:
            pause_keys = [f"pause_ia:{empresa_id}:{d['conversation_id']}" for d in result_data]
            try:
                pause_values = await redis_client.mget(*pause_keys)
                for d, pv in zip(result_data, pause_values):
                    d["pausada"] = pv is not None
            except Exception:
                for d in result_data:
                    d["pausada"] = False

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


@router.post("/conversations/{conversation_id}/limpar-memoria")
async def limpar_memoria_conversa(
    conversation_id: int,
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Limpa o histórico de mensagens e o estado Redis da IA para uma conversa.
    A IA passa a responder sem memória do histórico anterior.
    """
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não identificada")

    from src.services.db_queries import bd_limpar_historico_conversa
    ok = await bd_limpar_historico_conversa(conversation_id, empresa_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversa não encontrada ou sem permissão")

    # Deleta todas as chaves Redis da conversa (formato padronizado: {empresa_id}:{chave}:{conversation_id})
    await redis_client.delete(
        f"{empresa_id}:estado:{conversation_id}",
        f"{empresa_id}:unidade_escolhida:{conversation_id}",
        f"{empresa_id}:esperando_unidade:{conversation_id}",
        f"{empresa_id}:buffet:{conversation_id}",
        f"{empresa_id}:buffet_drain:{conversation_id}",
        f"{empresa_id}:prompt_unidade_enviado:{conversation_id}",
        # formatos legados (cleanup)
        f"estado:{empresa_id}:{conversation_id}",
        f"unidade_escolhida:{conversation_id}",
        f"esperando_unidade:{empresa_id}:{conversation_id}",
        f"buffet:{empresa_id}:{conversation_id}",
        f"buffet_drain:{empresa_id}:{conversation_id}",
        f"prompt_unidade_enviado:{empresa_id}:{conversation_id}",
    )

    return {"status": "ok", "mensagem": "Memória da IA limpa com sucesso"}


@router.get("/conversations/{conversation_id}/eventos")
async def get_eventos_funil(
    conversation_id: int,
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Retorna o histórico de eventos de pontuação (funil) de uma conversa específica.
    """
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não identificada")

    row = await _database.db_pool.fetchrow(
        "SELECT id FROM conversas WHERE conversation_id = $1 AND empresa_id = $2",
        conversation_id, empresa_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    try:
        eventos = await _database.db_pool.fetch(
            """SELECT tipo_evento, descricao, score_incremento, created_at
               FROM eventos_funil WHERE conversa_id = $1 ORDER BY created_at ASC""",
            row["id"]
        )
        return [dict(e) for e in eventos]
    except Exception as e:
        logger.error(f"Erro ao buscar eventos funil para conversa {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar eventos de pontuação")


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
    Realiza o upload de imagem ou vídeo para o ImageKit.
    Aceita: imagens (JPG, PNG, WebP) e vídeos (MP4, MOV, AVI).
    Limite: 50MB.
    """
    content_type = (file.content_type or "").lower()
    is_image = content_type.startswith("image/")
    is_video = content_type.startswith("video/")

    if not is_image and not is_video:
        raise HTTPException(
            status_code=400,
            detail=f"Formato não suportado: {content_type}. Envie imagem (JPG, PNG) ou vídeo (MP4, MOV)."
        )

    # Limite de tamanho: 100MB para vídeos, 10MB para imagens
    max_size = (100 if is_video else 10) * 1024 * 1024
    content = await file.read()
    if len(content) > max_size:
        size_mb = len(content) / (1024 * 1024)
        limit_mb = 100 if is_video else 10
        raise HTTPException(
            status_code=400,
            detail=f"Arquivo muito grande ({size_mb:.1f}MB). O limite é {limit_mb}MB."
        )

    try:
        # Pasta separada para vídeos
        folder = "/unidades/videos" if is_video else "/unidades"
        url = await upload_to_imagekit(content, file.filename, folder=folder)
        if not url:
            raise HTTPException(status_code=500, detail="Erro ao fazer upload. Tente novamente.")

        return {"url": url, "type": "video" if is_video else "image"}
    except Exception as e:
        logger.error(f"Erro no endpoint de upload: {e}")
        raise HTTPException(status_code=500, detail="Erro interno no upload. Tente novamente.")


class ExtrairGradeRequest(BaseModel):
    image_url: str

@router.post("/unidades/extrair-grade")
async def extrair_grade_ia(
    body: ExtrairGradeRequest,
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Usa IA Vision (Gemini 2.0 Flash via OpenRouter) para extrair modalidades,
    horários e detalhes de uma imagem de grade de aulas.
    """
    from src.services.llm_service import cliente_ia

    if not cliente_ia:
        raise HTTPException(status_code=500, detail="Cliente IA não configurado (OPENROUTER_API_KEY ausente)")

    image_url = body.image_url.strip()
    if not image_url:
        raise HTTPException(status_code=400, detail="URL da imagem é obrigatória")

    # 1. Baixar a imagem
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(image_url, timeout=20.0)
            resp.raise_for_status()
            image_bytes = resp.content
            content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if content_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                content_type = "image/jpeg"
    except Exception as e:
        logger.error(f"❌ Erro ao baixar imagem da grade: {e}")
        raise HTTPException(status_code=400, detail=f"Não foi possível baixar a imagem: {e}")

    # 2. Base64 encode
    img_b64 = base64.b64encode(image_bytes).decode("utf-8")

    # 3. Chamar IA Vision
    prompt_extracao = """Você é um especialista em academias fitness no Brasil.
Analise esta imagem de grade de aulas/horários e extraia TODAS as informações visíveis.

FORMATO DE RESPOSTA:

MODALIDADES: (lista separada por vírgula de todas as modalidades/aulas encontradas)

GRADE DE HORÁRIOS:
- Modalidade: Dias e horários

OBSERVAÇÕES: (qualquer informação extra visível na imagem, como professores, regras, avisos)

REGRAS IMPORTANTES:
- Transcreva EXATAMENTE o que está na imagem, sem inventar informações
- Se não conseguir ler algo com certeza, use [?] para indicar
- Se a imagem NÃO for uma grade de aulas, responda apenas: "ERRO: A imagem não parece ser uma grade de aulas/horários."
- Inclua TODOS os dias da semana e horários visíveis
- Mantenha os nomes das modalidades como aparecem na imagem"""

    try:
        result = await cliente_ia.chat.completions.create(
            model="google/gemini-2.0-flash-001",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_extracao},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{content_type};base64,{img_b64}"}
                    }
                ]
            }],
            temperature=0.1,
            max_tokens=4000,
        )

        texto_extraido = result.choices[0].message.content.strip()
        logger.info(f"✅ Extração de grade via IA: {len(texto_extraido)} chars extraídos")

        return {"success": True, "modalidades": texto_extraido}

    except Exception as e:
        logger.error(f"❌ Erro na extração de grade via IA: {e}")
        raise HTTPException(status_code=500, detail=f"Erro na extração via IA: {e}")


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
        # Limpa cache individual da unidade (usado pelo carregar_unidade do bot)
        _slug_updated = body.nome.lower().replace(" ", "-") if body.nome else None
        # Busca slug real do banco para garantir
        _row_slug = await _database.db_pool.fetchval("SELECT slug FROM unidades WHERE id = $1", unidade_id)
        if _row_slug:
            await redis_client.delete(f"cfg:unidade:{empresa_id}:{_row_slug}:v2")
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


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 4 — MÉTRICAS AVANÇADAS (Timeseries, Funil, Performance IA)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/metrics/timeseries")
async def get_metrics_timeseries(
    days: int = Query(30, le=90, description="Dias retroativos (máx 90)"),
    granularity: str = Query("day", description="Granularidade: hour ou day"),
    unidade_id: Optional[int] = Query(None, description="Filtrar por unidade"),
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Retorna métricas agregadas por hora ou dia para gráficos de linha/área.
    Dados: conversas, leads, intenção de compra, tempo de resposta, custo IA.
    """
    empresa_id = token_payload.get("empresa_id")
    perfil = token_payload.get("perfil")
    if perfil == "admin_master" and not empresa_id and unidade_id:
        empresa_id = await _get_empresa_id_da_unidade(unidade_id)
    if not empresa_id and perfil != "admin_master":
        raise HTTPException(status_code=400, detail="Empresa não identificada")

    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()

    # Monta date truncation baseado na granularidade
    if granularity == "hour" and days <= 3:
        trunc = "DATE_TRUNC('hour', c.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo')"
    else:
        trunc = "DATE_TRUNC('day', c.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo')"

    try:
        # Filtros dinâmicos
        conditions = []
        params: list = []

        if empresa_id:
            params.append(empresa_id)
            conditions.append(f"c.empresa_id = ${len(params)}")

        if unidade_id:
            params.append(unidade_id)
            conditions.append(f"c.unidade_id = ${len(params)}")

        params.append(hoje)
        params.append(days)
        conditions.append(
            f"DATE(c.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') "
            f"BETWEEN (${len(params)-1}::date - (${len(params)} * interval '1 day')) AND ${len(params)-1}"
        )

        where = " AND ".join(conditions)

        # Query de séries temporais
        rows = await _database.db_pool.fetch(f"""
            SELECT
                {trunc} AS periodo,
                COUNT(DISTINCT c.id) AS conversas,
                COUNT(DISTINCT CASE WHEN c.lead_qualificado THEN c.id END) AS leads,
                COUNT(DISTINCT CASE WHEN c.intencao_de_compra THEN c.id END) AS intencao,
                COALESCE(AVG(
                    EXTRACT(EPOCH FROM (c.primeira_resposta_em - c.primeira_mensagem))
                ) FILTER (WHERE c.primeira_resposta_em IS NOT NULL AND c.primeira_mensagem IS NOT NULL), 0) AS tempo_resp
            FROM conversas c
            WHERE {where}
            GROUP BY periodo
            ORDER BY periodo ASC
        """, *params)

        # Query de custo IA por período (separada para não complicar o JOIN)
        ia_conditions = [c.replace("c.", "ui.") for c in conditions]
        ia_where = " AND ".join(ia_conditions)
        ia_trunc = trunc.replace("c.", "ui.")

        rows_ia = await _database.db_pool.fetch(f"""
            SELECT
                {ia_trunc} AS periodo,
                COALESCE(SUM(ui.custo_usd), 0) AS custo_usd,
                COALESCE(SUM(ui.tokens_prompt + ui.tokens_completion), 0) AS tokens
            FROM uso_ia ui
            WHERE {ia_where}
            GROUP BY periodo
            ORDER BY periodo ASC
        """, *params)

        # Merge os dados por período
        ia_by_period = {}
        for r in rows_ia:
            key = r["periodo"].isoformat() if r["periodo"] else ""
            ia_by_period[key] = {"custo_usd": round(float(r["custo_usd"]), 4), "tokens": r["tokens"]}

        series = []
        for r in rows:
            period_key = r["periodo"].isoformat() if r["periodo"] else ""
            ia_data = ia_by_period.get(period_key, {"custo_usd": 0, "tokens": 0})
            series.append({
                "periodo": period_key,
                "conversas": r["conversas"],
                "leads": r["leads"],
                "intencao": r["intencao"],
                "tempo_resp": round(float(r["tempo_resp"]), 1),
                "custo_usd": ia_data["custo_usd"],
                "tokens": ia_data["tokens"],
            })

        return {
            "granularity": granularity if granularity == "hour" and days <= 3 else "day",
            "days": days,
            "series": series
        }
    except Exception as e:
        logger.error(f"Erro ao buscar timeseries: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar dados de séries temporais")


@router.get("/metrics/funnel")
async def get_metrics_funnel(
    days: int = Query(30, le=90),
    unidade_id: Optional[int] = Query(None),
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Retorna funil de conversão em 5 estágios:
    Contatos → Engajados → Interessados → Link Enviado → Matriculados
    """
    empresa_id = token_payload.get("empresa_id")
    perfil = token_payload.get("perfil")
    if perfil == "admin_master" and not empresa_id and unidade_id:
        empresa_id = await _get_empresa_id_da_unidade(unidade_id)
    if not empresa_id and perfil != "admin_master":
        raise HTTPException(status_code=400, detail="Empresa não identificada")

    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()

    try:
        conditions = []
        params: list = []

        if empresa_id:
            params.append(empresa_id)
            conditions.append(f"c.empresa_id = ${len(params)}")

        if unidade_id:
            params.append(unidade_id)
            conditions.append(f"c.unidade_id = ${len(params)}")

        params.append(hoje)
        params.append(days)
        conditions.append(
            f"DATE(c.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') "
            f"BETWEEN (${len(params)-1}::date - (${len(params)} * interval '1 day')) AND ${len(params)-1}"
        )

        where = " AND ".join(conditions)

        row = await _database.db_pool.fetchrow(f"""
            SELECT
                COUNT(DISTINCT c.id) AS contatos,
                COUNT(DISTINCT CASE WHEN c.total_mensagens_cliente >= 2 THEN c.id END) AS engajados,
                COUNT(DISTINCT CASE WHEN c.lead_qualificado OR c.intencao_de_compra THEN c.id END) AS interessados,
                COUNT(DISTINCT CASE WHEN ef_link.conversa_id IS NOT NULL THEN c.id END) AS link_enviado,
                COUNT(DISTINCT CASE WHEN ef_mat.conversa_id IS NOT NULL THEN c.id END) AS matriculados
            FROM conversas c
            LEFT JOIN eventos_funil ef_link ON ef_link.conversa_id = c.id AND ef_link.tipo_evento = 'link_matricula_enviado'
            LEFT JOIN eventos_funil ef_mat ON ef_mat.conversa_id = c.id AND ef_mat.tipo_evento IN ('matricula_realizada','checkout_concluido')
            WHERE {where}
        """, *params)

        data = dict(row) if row else {}
        stages = [
            {"id": "contatos", "label": "Contatos", "value": data.get("contatos", 0), "color": "#6366f1"},
            {"id": "engajados", "label": "Engajados", "value": data.get("engajados", 0), "color": "#3b82f6"},
            {"id": "interessados", "label": "Interessados", "value": data.get("interessados", 0), "color": "#00d2ff"},
            {"id": "link_enviado", "label": "Link Enviado", "value": data.get("link_enviado", 0), "color": "#10b981"},
            {"id": "matriculados", "label": "Matriculados", "value": data.get("matriculados", 0), "color": "#22c55e"},
        ]

        # Calcular taxas de conversão entre estágios
        for i in range(1, len(stages)):
            prev_val = stages[i - 1]["value"]
            curr_val = stages[i]["value"]
            stages[i]["taxa"] = round((curr_val / max(prev_val, 1)) * 100, 1)
        stages[0]["taxa"] = 100.0

        return {"days": days, "stages": stages}
    except Exception as e:
        logger.error(f"Erro ao buscar funil: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar funil de conversão")


@router.get("/metrics/ai-performance")
async def get_metrics_ai_performance(
    days: int = Query(7, le=30),
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Métricas de performance da IA:
    - Cache hit rate, latência média, chamadas por hora
    - Taxa de fallback, taxa de escalação
    - Mensagens por conversa, distribuição de sentimento
    - Custo médio por conversa
    """
    empresa_id = token_payload.get("empresa_id")
    perfil = token_payload.get("perfil")
    if not empresa_id and perfil != "admin_master":
        raise HTTPException(status_code=400, detail="Empresa não identificada")

    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()

    try:
        conditions_c = []
        conditions_ia = []
        params: list = []

        if empresa_id:
            params.append(empresa_id)
            conditions_c.append(f"c.empresa_id = ${len(params)}")
            conditions_ia.append(f"ui.empresa_id = ${len(params)}")

        params.append(hoje)
        params.append(days)
        date_filter_c = (
            f"DATE(c.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') "
            f"BETWEEN (${len(params)-1}::date - (${len(params)} * interval '1 day')) AND ${len(params)-1}"
        )
        date_filter_ia = date_filter_c.replace("c.", "ui.")
        conditions_c.append(date_filter_c)
        conditions_ia.append(date_filter_ia)

        where_c = " AND ".join(conditions_c) if conditions_c else "TRUE"
        where_ia = " AND ".join(conditions_ia) if conditions_ia else "TRUE"

        # 1. Métricas de uso da IA (apenas colunas que existem na tabela)
        row_ia = await _database.db_pool.fetchrow(f"""
            SELECT
                COUNT(*) AS total_chamadas,
                COALESCE(SUM(ui.custo_usd), 0) AS custo_total,
                COALESCE(SUM(ui.tokens_prompt + ui.tokens_completion), 0) AS total_tokens
            FROM uso_ia ui
            WHERE {where_ia}
        """, *params)

        # 2. Métricas de conversas
        row_conv = await _database.db_pool.fetchrow(f"""
            SELECT
                COUNT(DISTINCT c.id) AS total_conversas,
                COALESCE(AVG(c.total_mensagens_cliente), 0) AS msgs_cliente_media,
                COALESCE(AVG(c.total_mensagens_ia), 0) AS msgs_ia_media,
                COALESCE(AVG(
                    EXTRACT(EPOCH FROM (c.primeira_resposta_em - c.primeira_mensagem))
                ) FILTER (WHERE c.primeira_resposta_em IS NOT NULL AND c.primeira_mensagem IS NOT NULL), 0) AS tempo_resp_medio
            FROM conversas c
            WHERE {where_c}
        """, *params)

        # 3. Eventos de escalação e sentimento
        ef_conditions = [c.replace("c.", "c2.") for c in conditions_c]
        ef_where = " AND ".join(ef_conditions) if ef_conditions else "TRUE"
        row_esc = await _database.db_pool.fetchrow(f"""
            SELECT
                COUNT(DISTINCT CASE WHEN ef.tipo_evento = 'escalacao_sentimento' THEN ef.conversa_id END) AS escalacoes,
                COUNT(DISTINCT CASE WHEN ef.tipo_evento = 'mensagem_lida' THEN ef.conversa_id END) AS mensagens_lidas
            FROM eventos_funil ef
            JOIN conversas c2 ON c2.id = ef.conversa_id
            WHERE {ef_where}
        """, *params)

        # 4. Distribuição por hora (para gráfico de atividade)
        rows_hora = await _database.db_pool.fetch(f"""
            SELECT
                EXTRACT(HOUR FROM ui.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo')::int AS hora,
                COUNT(*) AS chamadas
            FROM uso_ia ui
            WHERE {where_ia}
            GROUP BY hora
            ORDER BY hora
        """, *params)

        ia = dict(row_ia) if row_ia else {}
        conv = dict(row_conv) if row_conv else {}
        esc = dict(row_esc) if row_esc else {}

        total_chamadas = ia.get("total_chamadas", 0) or 1
        total_conversas = conv.get("total_conversas", 0) or 1

        # Calcula tempo médio de resposta como proxy de latência
        tempo_resp = float(conv.get("tempo_resp_medio", 0))
        latencia_estimada = round(tempo_resp * 1000, 0) if tempo_resp > 0 and tempo_resp < 60 else 0

        return {
            "days": days,
            "ia": {
                "total_chamadas": ia.get("total_chamadas", 0),
                "latencia_media_ms": latencia_estimada,
                "cache_hit_rate": 0.0,  # Requer coluna cache_hit na tabela uso_ia
                "fallback_rate": 0.0,   # Requer coluna fallback na tabela uso_ia
                "custo_total_usd": round(float(ia.get("custo_total", 0)), 4),
                "custo_por_conversa": round(float(ia.get("custo_total", 0)) / total_conversas, 4),
                "total_tokens": ia.get("total_tokens", 0),
            },
            "conversas": {
                "total": conv.get("total_conversas", 0),
                "msgs_cliente_media": round(float(conv.get("msgs_cliente_media", 0)), 1),
                "msgs_ia_media": round(float(conv.get("msgs_ia_media", 0)), 1),
                "tempo_resposta_medio": round(float(conv.get("tempo_resp_medio", 0)), 1),
            },
            "escalacoes": esc.get("escalacoes", 0),
            "mensagens_lidas": esc.get("mensagens_lidas", 0),
            "taxa_escalacao": round((esc.get("escalacoes", 0) / total_conversas) * 100, 1),
            "atividade_por_hora": [
                {"hora": r["hora"], "chamadas": r["chamadas"]} for r in rows_hora
            ],
        }
    except Exception as e:
        logger.error(f"Erro ao buscar métricas AI performance: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar métricas de performance da IA")
