"""
[CACHE-01] Endpoints admin para manipular cache.

Botão "Limpar memória do bot" no dashboard — força recarregamento do banco
na próxima mensagem. Útil quando admin fez muitas alterações e quer forçar
a IA a usar o conteúdo atualizado imediatamente.

Endpoints:
  POST /api/cache/flush          — limpa tudo da empresa (botão do admin)
  POST /api/cache/flush/faq      — só FAQ
  POST /api/cache/flush/kb       — só knowledge base
  POST /api/cache/flush/personalidade — só personalidade+menu+fluxo
  POST /api/cache/flush/all      — NUCLEAR: limpa TODAS as empresas (só admin_master)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.core.config import logger
from src.core.tenant import require_tenant, require_admin_master
from src.middleware.rate_limit import rate_limit
from src.services.cache_invalidation import (
    flush_empresa,
    flush_all,
    invalidate_faq,
    invalidate_kb,
    invalidate_personalidade,
    invalidate_integracao,
    invalidate_planos,
)


router = APIRouter(prefix="/api/cache", tags=["cache-admin"])


@router.post(
    "/flush",
    dependencies=[Depends(rate_limit(key="cache_flush", max_calls=20, window=60))],
)
async def api_flush_empresa(tenant: dict = Depends(require_tenant)):
    """Limpa TODO o cache da empresa — proxima request recarrega do banco."""
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    n = await flush_empresa(empresa_id)
    logger.info(f"[cache.flush] user={tenant.get('email')} empresa={empresa_id} keys_apagadas={n}")
    return {"status": "ok", "empresa_id": empresa_id, "keys_apagadas": n}


@router.post("/flush/faq")
async def api_flush_faq(tenant: dict = Depends(require_tenant)):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    n = await invalidate_faq(empresa_id)
    return {"status": "ok", "tipo": "faq", "keys_apagadas": n}


@router.post("/flush/kb")
async def api_flush_kb(tenant: dict = Depends(require_tenant)):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    n = await invalidate_kb(empresa_id)
    return {"status": "ok", "tipo": "knowledge_base", "keys_apagadas": n}


@router.post("/flush/personalidade")
async def api_flush_personalidade(tenant: dict = Depends(require_tenant)):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    n = await invalidate_personalidade(empresa_id)
    return {"status": "ok", "tipo": "personalidade+menu+fluxo", "keys_apagadas": n}


@router.post("/flush/integracao")
async def api_flush_integracao(tipo: str | None = None, tenant: dict = Depends(require_tenant)):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    n = await invalidate_integracao(empresa_id, tipo=tipo)
    return {"status": "ok", "tipo": f"integracao:{tipo or 'todos'}", "keys_apagadas": n}


@router.post("/flush/planos")
async def api_flush_planos(tenant: dict = Depends(require_tenant)):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    n = await invalidate_planos(empresa_id)
    return {"status": "ok", "tipo": "planos", "keys_apagadas": n}


@router.post("/flush/all")
async def api_flush_all(tenant: dict = Depends(require_admin_master)):
    """NUCLEAR: apaga cache de TODAS as empresas. Apenas admin_master."""
    n = await flush_all()
    logger.warning(f"[cache.flush_all] TODAS empresas — keys_apagadas={n} por {tenant.get('email')}")
    return {"status": "ok", "tipo": "global", "keys_apagadas": n}


# ============================================================
# [CACHE-02] Auditoria de configuracao — mostra campos vazios
# ============================================================

# Campos da personalidade que SE VAZIOS, o bot usa fallback hardcoded e perde personalidade
_CAMPOS_CRITICOS_PERSONALIDADE = [
    ("nome_ia", "Nome da IA (ex: Laura, Ana, Bot da Fluxo)"),
    ("personalidade", "Descricao da personalidade (ex: amigavel, objetiva, consultiva)"),
    ("tom_voz", "Tom de voz (ex: formal, casual, entusiasmado)"),
    ("instrucoes_base", "Instrucoes base de como responder"),
    ("saudacao_personalizada", "Saudacao de abertura (ex: Oi! Eu sou a Laura...)"),
    ("objetivos_venda", "Objetivos comerciais (ex: qualificar lead, agendar avaliacao)"),
    ("publico_alvo", "Publico-alvo (ex: mulheres 25-45, iniciantes, praticantes)"),
    ("diferenciais", "Diferenciais da academia (ex: sala climatizada, aulas coletivas)"),
    ("script_vendas", "Script de vendas (como conduzir a conversa)"),
    ("scripts_objecoes", "Scripts para objecoes comuns (preco alto, falta de tempo)"),
    ("despedida_personalizada", "Despedida (ex: Ate breve! Qualquer coisa chama)"),
    ("restricoes", "O que a IA NAO deve falar/fazer"),
]


@router.get("/config-status")
async def api_config_status(tenant: dict = Depends(require_tenant)):
    """
    Retorna uma auditoria da personalidade: quais campos estao preenchidos e
    quais estao vazios (e vao usar fallback hardcoded no bot).

    Use no dashboard como indicador de 'completude' — idealmente todos os campos
    criticos devem estar preenchidos para o bot usar 100% do conteudo customizado.
    """
    import src.core.database as _database
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")

    if not _database.db_pool:
        raise HTTPException(status_code=503, detail="Banco indisponivel")

    # Busca a personalidade ativa
    row = await _database.db_pool.fetchrow(
        """
        SELECT * FROM personalidade_ia
        WHERE empresa_id = $1 AND ativo = true
        ORDER BY updated_at DESC LIMIT 1
        """,
        empresa_id,
    )

    if not row:
        return {
            "empresa_id": empresa_id,
            "tem_personalidade_ativa": False,
            "aviso": "Nenhuma personalidade ativa — o bot vai usar fallbacks genericos em TUDO. Crie/ative uma personalidade no dashboard.",
            "campos_vazios": [{"campo": c, "descricao": d} for c, d in _CAMPOS_CRITICOS_PERSONALIDADE],
            "completude_pct": 0,
        }

    campos_vazios = []
    campos_ok = []
    for campo, descricao in _CAMPOS_CRITICOS_PERSONALIDADE:
        valor = row.get(campo)
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            campos_vazios.append({"campo": campo, "descricao": descricao})
        else:
            campos_ok.append(campo)

    # Contagens complementares (FAQ, KB, planos)
    n_faqs = await _database.db_pool.fetchval(
        "SELECT COUNT(*) FROM faq WHERE empresa_id = $1 AND ativo = true", empresa_id,
    ) or 0
    n_kb = await _database.db_pool.fetchval(
        "SELECT COUNT(*) FROM knowledge_base WHERE empresa_id = $1 AND ativo = true", empresa_id,
    ) or 0
    n_planos = await _database.db_pool.fetchval(
        "SELECT COUNT(*) FROM planos WHERE empresa_id = $1 AND ativo = true", empresa_id,
    ) or 0
    n_unidades = await _database.db_pool.fetchval(
        "SELECT COUNT(*) FROM unidades WHERE empresa_id = $1 AND ativa = true", empresa_id,
    ) or 0

    total = len(_CAMPOS_CRITICOS_PERSONALIDADE)
    ok = len(campos_ok)
    completude_pct = round(100 * ok / total, 1)

    alertas = []
    if completude_pct < 50:
        alertas.append("ATENCAO: menos de 50% dos campos da personalidade estao preenchidos. O bot vai usar muitos fallbacks.")
    if n_faqs == 0:
        alertas.append("Nenhuma FAQ cadastrada — o bot vai depender 100% do RAG/IA para responder.")
    if n_kb == 0 and n_faqs < 5:
        alertas.append("Base de conhecimento vazia e poucas FAQs — bot pode alucinar respostas.")
    if n_planos == 0:
        alertas.append("Nenhum plano cadastrado — bot nao vai conseguir falar de precos/mensalidades.")
    if n_unidades == 0:
        alertas.append("Nenhuma unidade ativa — bot nao vai conseguir falar de endereco/horario.")

    return {
        "empresa_id": empresa_id,
        "tem_personalidade_ativa": True,
        "completude_pct": completude_pct,
        "campos_ok": campos_ok,
        "campos_vazios": campos_vazios,
        "contadores": {
            "faqs_ativas": int(n_faqs),
            "kb_items": int(n_kb),
            "planos_ativos": int(n_planos),
            "unidades_ativas": int(n_unidades),
        },
        "alertas": alertas,
    }
