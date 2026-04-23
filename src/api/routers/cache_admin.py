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
    ("mensagem_fora_horario", "Mensagem quando fora do horario (ex: Volto a falar com voce as 8h)"),
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


# ============================================================
# [HORA-01] Diagnostico de horario — mostra EXATAMENTE por que a IA esta
# ou nao dentro do horario de atendimento neste momento.
# ============================================================

@router.get("/horario-status")
async def api_horario_status(tenant: dict = Depends(require_tenant)):
    """
    Diagnostico completo e cruzado de horario:

    1. Estado da IA (bot_core / horario_atendimento_ia)
    2. Estado do FLUXO de triagem + no BusinessHours dentro dele
    3. Simulacao do que vai acontecer AGORA se uma mensagem chegar
    4. Deteccao de conflitos: gap (horas sem ninguem) ou sobreposicao (dois atendendo)
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import json as _json
    import src.core.database as _database
    from src.utils.time_helpers import ia_esta_no_horario

    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    if not _database.db_pool:
        raise HTTPException(status_code=503, detail="Banco indisponivel")

    agora_brt = datetime.now(ZoneInfo("America/Sao_Paulo"))
    dia_semana_num = agora_brt.weekday()
    hora_atual_str = agora_brt.strftime("%H:%M")

    # ── 1. Config da IA (personalidade_ia) ──────────────────────────────
    pers_row = await _database.db_pool.fetchrow(
        """
        SELECT id, ativo, horario_atendimento_ia, horario_comercial, fluxo_triagem,
               fn_ia_esta_no_horario_v2(horario_atendimento_ia) AS db_esta_no_horario
        FROM personalidade_ia
        WHERE empresa_id = $1 AND ativo = true
        ORDER BY updated_at DESC LIMIT 1
        """,
        empresa_id,
    )

    if not pers_row:
        return {
            "empresa_id": empresa_id,
            "agora_brt": agora_brt.strftime("%Y-%m-%d %H:%M:%S (%A)"),
            "erro": "Nenhuma personalidade ativa — crie uma e ative no dashboard",
        }

    horario_ia = pers_row["horario_atendimento_ia"]
    if isinstance(horario_ia, str):
        try: horario_ia = _json.loads(horario_ia)
        except Exception: horario_ia = None

    try:
        py_result = ia_esta_no_horario(horario_ia)
    except Exception as e:
        py_result = f"ERRO: {e}"

    db_result = pers_row["db_esta_no_horario"]
    ia_dentro_horario = bool(db_result) if db_result is not None else bool(py_result)

    # ── 2. Config do fluxo triagem (busca no fluxo_triagem da personalidade) ──
    fluxo_raw = pers_row["fluxo_triagem"]
    if isinstance(fluxo_raw, str):
        try: fluxo_raw = _json.loads(fluxo_raw)
        except Exception: fluxo_raw = None

    fluxo_ativo = bool(fluxo_raw and fluxo_raw.get("ativo"))

    # Acha o primeiro no BusinessHours do fluxo (se houver)
    business_hours_node = None
    if fluxo_raw and isinstance(fluxo_raw.get("nodes"), list):
        for node in fluxo_raw["nodes"]:
            if node.get("type") == "businessHours":
                business_hours_node = node.get("data") or {}
                break

    fluxo_is_open_agora = None  # None = nao tem nó
    fluxo_modo = None
    fluxo_horarios_visiveis = None
    if business_hours_node:
        fluxo_modo = business_hours_node.get("modo", "global")
        if fluxo_modo == "custom" and business_hours_node.get("horarios"):
            horarios = business_hours_node["horarios"]
            horario_dia = horarios.get(str(dia_semana_num), {})
            fluxo_horarios_visiveis = horarios
            if horario_dia.get("ativo"):
                inicio = horario_dia.get("inicio", "00:00")
                fim = horario_dia.get("fim", "23:59")
                fluxo_is_open_agora = inicio <= hora_atual_str <= fim
            else:
                fluxo_is_open_agora = False
        else:
            # modo=global — usa horario_comercial da personalidade
            horario_com = pers_row["horario_comercial"]
            if isinstance(horario_com, str):
                try: horario_com = _json.loads(horario_com)
                except Exception: horario_com = None
            fluxo_horarios_visiveis = horario_com
            try:
                fluxo_is_open_agora = ia_esta_no_horario(horario_com) if horario_com else None
            except Exception:
                fluxo_is_open_agora = None

    # ── 3. Simulacao: o que acontece se uma mensagem chegar AGORA? ──
    cenario = []
    if fluxo_ativo and business_hours_node:
        if fluxo_is_open_agora is True:
            cenario.append("Fluxo triagem ATIVO → nó BusinessHours → 'aberto' → roda o fluxo estruturado (menu)")
        elif fluxo_is_open_agora is False:
            cenario.append("Fluxo triagem ATIVO → nó BusinessHours → 'fechado' → o que tiver conectado no handle 'fechado' (geralmente IA livre)")
        else:
            cenario.append("Fluxo triagem ATIVO → nó BusinessHours → sem config de horário do dia → rota 'fechado'")
    elif fluxo_ativo:
        cenario.append("Fluxo triagem ATIVO mas SEM nó BusinessHours → segue o fluxo inteiro sem checar horário")
    else:
        cenario.append("Fluxo triagem NÃO ATIVO → mensagem cai direto no bot_core / IA livre")

    if not fluxo_ativo or (fluxo_ativo and fluxo_is_open_agora is False and not business_hours_node):
        # bot_core vai ser chamado
        if ia_dentro_horario:
            cenario.append("bot_core checa horário da IA → DENTRO → IA responde normalmente")
        else:
            cenario.append("bot_core checa horário da IA → FORA → IA fica CALADA (silêncio total)")

    # ── 4. Deteccao de gap ou sobreposicao ──
    conflitos = []
    if horario_ia and fluxo_horarios_visiveis:
        # Check simples pro momento atual: se AMBOS dizem "fora", tem gap
        if ia_dentro_horario is False and fluxo_is_open_agora is False:
            conflitos.append(f"🚨 GAP: neste momento ({hora_atual_str}) nem IA nem fluxo atendem. Cliente fica sem resposta.")
        # Se AMBOS dizem "dentro", tem sobreposicao (nao e erro fatal, mas inesperado)
        if ia_dentro_horario is True and fluxo_is_open_agora is True:
            conflitos.append(f"⚠️ SOBREPOSIÇÃO: agora ({hora_atual_str}) fluxo E IA estão ativos. O fluxo tem prioridade, mas confira se é intencional.")

    return {
        "empresa_id": empresa_id,
        "agora_brt": agora_brt.strftime("%Y-%m-%d %H:%M:%S %a"),
        "ia_personalidade": {
            "horario_configurado": horario_ia,
            "dentro_horario_agora": ia_dentro_horario,
            "fonte_decisao": "banco (fn_ia_esta_no_horario_v2)" if db_result is not None else "python fallback",
            "db_check": db_result,
            "python_check": py_result,
        },
        "fluxo_triagem": {
            "ativo": fluxo_ativo,
            "tem_no_business_hours": bool(business_hours_node),
            "modo": fluxo_modo,
            "dentro_horario_agora": fluxo_is_open_agora,
            "horarios_config": fluxo_horarios_visiveis,
        },
        "simulacao_mensagem_agora": cenario,
        "conflitos": conflitos,
        "solucao_se_gap": (
            "Garanta que os 2 horários (Fluxo BusinessHours + IA horario_atendimento_ia) "
            "cubram 24h sem deixar buraco. Ex: Fluxo 8h-17h / IA 17h-8h."
        ) if conflitos else None,
    }
