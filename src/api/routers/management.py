from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, model_validator
import src.core.database as _database
from src.core.security import get_current_user_token
from src.core.config import logger
from src.core.redis_client import redis_client
import json
import asyncio
from src.services.db_queries import listar_unidades_ativas, buscar_planos_ativos, formatar_planos_para_prompt
from src.services.evo_client import (
    listar_branches_evo, listar_services_evo, listar_activities_evo,
    listar_horarios_disponiveis_evo, agendar_aula_experimental_evo, criar_prospect_evo,
)
from src.services.agendamento_tools import (
    construir_bloco_prompt_agendamento as _agend_bloco_prompt,
    detectar_tool_call as _agend_detectar_tool,
    executar_tool as _agend_executar_tool,
)
from src.utils.rate_limit import rate_limit_empresa

# [CACHE-01] Invalidacao centralizada — toda mutacao (PUT/POST/DELETE) deve chamar
# a funcao correspondente para garantir que a proxima mensagem do cliente use o
# conteudo atualizado imediatamente, sem esperar TTL de 5 minutos.
from src.services.cache_invalidation import (
    invalidate_personalidade,
    invalidate_faq,
    invalidate_kb,
    invalidate_menu_triagem,
    invalidate_fluxo_triagem,
    invalidate_integracao,
    invalidate_unidades,
    invalidate_planos,
    invalidate_global,
    flush_empresa,
)

router = APIRouter(prefix="/management", tags=["management"])

# --- Schemas ---

class PersonalityUpdate(BaseModel):
    nome_ia: Optional[str] = None
    personalidade: Optional[str] = None
    instrucoes_base: Optional[str] = None
    tom_voz: Optional[str] = None
    model_name: Optional[str] = "openai/gpt-4o"
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1000
    ativo: Optional[bool] = None
    usar_emoji: Optional[bool] = None
    horario_atendimento_ia: Optional[dict] = None
    horario_comercial: Optional[dict] = None
    menu_triagem: Optional[dict] = None
    idioma: Optional[str] = None
    objetivos_venda: Optional[str] = None
    metas_comerciais: Optional[str] = None
    script_vendas: Optional[str] = None
    scripts_objecoes: Optional[str] = None
    frases_fechamento: Optional[str] = None
    diferenciais: Optional[str] = None
    posicionamento: Optional[str] = None
    publico_alvo: Optional[str] = None
    restricoes: Optional[str] = None
    linguagem_proibida: Optional[str] = None
    contexto_empresa: Optional[str] = None
    contexto_extra: Optional[str] = None
    abordagem_proativa: Optional[str] = None
    exemplos: Optional[str] = None
    palavras_proibidas: Optional[str] = None
    despedida_personalizada: Optional[str] = None
    regras_formatacao: Optional[str] = None
    regras_seguranca: Optional[str] = None
    emoji_tipo: Optional[str] = None
    emoji_cor: Optional[str] = None
    estilo_comunicacao: Optional[str] = None
    saudacao_personalizada: Optional[str] = None
    regras_atendimento: Optional[str] = None
    tts_ativo: Optional[bool] = None
    tts_voz: Optional[str] = None
    oferecer_tour: Optional[bool] = None
    estrategia_tour: Optional[str] = None
    tour_perguntar_primeira_visita: Optional[bool] = None
    tour_mensagem_custom: Optional[str] = None
    comprimento_resposta: Optional[str] = "normal"  # 'concisa' | 'normal' | 'detalhada'
    mensagem_fora_horario: Optional[str] = None  # [HORA-01] mensagem custom fora do horario
    # [AGEND-01] Agendamento de aula experimental (Fase 1)
    agendamento_experimental_ativo: Optional[bool] = False
    agendamento_provider: Optional[str] = "evo"
    agendamento_dias_a_frente: Optional[int] = 5
    agendamento_id_branch: Optional[int] = None
    agendamento_id_activities: Optional[Any] = None
    agendamento_id_service: Optional[int] = None
    agendamento_texto_oferta: Optional[str] = ""
    agendamento_coletar_email: Optional[bool] = False

# Campos string do PersonalityCreate — definido fora da classe para evitar
# conflito com atributos privados do Pydantic V2 (prefixo _)
_PERSONALITY_STR_FIELDS = [
    "nome_ia", "personalidade", "instrucoes_base", "tom_voz", "model_name",
    "idioma", "objetivos_venda", "metas_comerciais", "script_vendas",
    "scripts_objecoes", "frases_fechamento", "diferenciais", "posicionamento",
    "publico_alvo", "restricoes", "linguagem_proibida", "contexto_empresa",
    "contexto_extra", "abordagem_proativa", "exemplos", "palavras_proibidas",
    "despedida_personalizada", "regras_formatacao", "regras_seguranca",
    "emoji_tipo", "emoji_cor",
    "estilo_comunicacao", "saudacao_personalizada", "regras_atendimento",
    "tts_voz",
]


class PersonalityCreate(BaseModel):
    id: Optional[int] = None
    nome_ia: Optional[str] = "Assistente"
    personalidade: Optional[str] = ""
    instrucoes_base: Optional[str] = ""
    tom_voz: Optional[str] = "Profissional"
    model_name: Optional[str] = "openai/gpt-4o"
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1000
    ativo: Optional[bool] = False
    usar_emoji: Optional[bool] = True
    horario_atendimento_ia: Optional[Any] = None
    horario_comercial: Optional[Any] = None
    menu_triagem: Optional[Any] = None
    idioma: Optional[str] = "Português do Brasil"
    objetivos_venda: Optional[str] = ""
    metas_comerciais: Optional[str] = ""
    script_vendas: Optional[str] = ""
    scripts_objecoes: Optional[str] = ""
    frases_fechamento: Optional[str] = ""
    diferenciais: Optional[str] = ""
    posicionamento: Optional[str] = ""
    publico_alvo: Optional[str] = ""
    restricoes: Optional[str] = ""
    linguagem_proibida: Optional[str] = ""
    contexto_empresa: Optional[str] = ""
    contexto_extra: Optional[str] = ""
    abordagem_proativa: Optional[str] = ""
    exemplos: Optional[str] = ""
    palavras_proibidas: Optional[str] = ""
    despedida_personalizada: Optional[str] = ""
    regras_formatacao: Optional[str] = ""
    regras_seguranca: Optional[str] = ""
    emoji_tipo: Optional[str] = "✨"
    emoji_cor: Optional[str] = "#00d2ff"
    estilo_comunicacao: Optional[str] = ""
    saudacao_personalizada: Optional[str] = ""
    regras_atendimento: Optional[str] = ""
    tts_ativo: Optional[bool] = True
    tts_voz: Optional[str] = "Kore"
    oferecer_tour: Optional[bool] = True
    estrategia_tour: Optional[str] = "smart"
    tour_perguntar_primeira_visita: Optional[bool] = True
    tour_mensagem_custom: Optional[str] = None
    comprimento_resposta: Optional[str] = "normal"  # 'concisa' | 'normal' | 'detalhada'
    mensagem_fora_horario: Optional[str] = None  # [HORA-01] mensagem custom fora do horario

    model_config = {"extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def coerce_types(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        for field in _PERSONALITY_STR_FIELDS:
            v = values.get(field)
            if v is not None and not isinstance(v, str):
                values[field] = str(v)
        # Garante tipos numéricos corretos
        if "temperature" in values and values["temperature"] is not None:
            try:
                values["temperature"] = float(values["temperature"])
            except (TypeError, ValueError):
                values["temperature"] = 0.7
        if "max_tokens" in values and values["max_tokens"] is not None:
            try:
                values["max_tokens"] = int(float(values["max_tokens"]))
            except (TypeError, ValueError):
                values["max_tokens"] = 1000
        return values

class FAQCreate(BaseModel):
    pergunta: str
    resposta: str
    unidade_id: Optional[int] = None
    todas_unidades: bool = False
    prioridade: int = 0



async def _resolve_empresa_id(token_payload: dict) -> Optional[int]:
    """
    Resolve empresa_id do JWT.
    - Primeiro tenta o claim empresa_id direto no token (caminho rápido).
    - Fallback: busca pelo e-mail do usuário na tabela usuarios (tokens legados).
    - Garante retorno int() para consistência de tipo.
    """
    empresa_id = token_payload.get("empresa_id")
    if empresa_id:
        return int(empresa_id)

    email = token_payload.get("sub")
    if not email:
        return None

    try:
        row = await _database.db_pool.fetchval(
            "SELECT empresa_id FROM usuarios WHERE email = $1 AND ativo = true",
            email
        )
        return int(row) if row else None
    except Exception as e:
        logger.warning(f"Não foi possível resolver empresa_id para {email}: {e}")
        return None

class IntegrationUpdate(BaseModel):
    config: Dict[str, Any]
    ativo: bool = True

class FollowupTemplateCreate(BaseModel):
    nome: str
    mensagem: str
    delay_minutos: int
    ordem: int = 1
    tipo: str = "texto"
    ativo: bool = True
    unidade_id: Optional[int] = None
    # Filtros inteligentes CSAT + sentimento
    filtro_rating_min: int = 0          # 0 = sem filtro; 1–5 = nota mínima exigida
    filtro_sentimentos_excluir: List[str] = []   # sentimentos que bloqueiam o envio
    bloquear_cancelamento: bool = False  # TRUE = não envia se detectou intenção de cancelar

class FollowupTemplateUpdate(BaseModel):
    nome: Optional[str] = None
    mensagem: Optional[str] = None
    delay_minutos: Optional[int] = None
    ordem: Optional[int] = None
    tipo: Optional[str] = None
    ativo: Optional[bool] = None
    unidade_id: Optional[int] = None
    # Filtros inteligentes CSAT + sentimento
    filtro_rating_min: Optional[int] = None
    filtro_sentimentos_excluir: Optional[List[str]] = None
    bloquear_cancelamento: Optional[bool] = None

# --- Personality Endpoints ---

@router.get("/personality")
async def get_personality(token_payload: dict = Depends(get_current_user_token)):
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    
    row = await _database.db_pool.fetchrow(
        """SELECT id, nome_ia, personalidade, instrucoes_base, tom_voz,
                  modelo_preferido as model_name, temperatura as temperature, max_tokens,
                  ativo, usar_emoji, horario_atendimento_ia, horario_comercial, menu_triagem,
                  idioma, objetivos_venda, metas_comerciais, script_vendas,
                  scripts_objecoes, frases_fechamento, diferenciais,
                  posicionamento, publico_alvo, restricoes, linguagem_proibida,
                  contexto_empresa, contexto_extra, abordagem_proativa,
                  exemplos, palavras_proibidas, despedida_personalizada,
                  regras_formatacao, regras_seguranca,
                  emoji_tipo, emoji_cor,
                  tts_ativo, tts_voz,
                  agendamento_experimental_ativo, agendamento_provider,
                  agendamento_dias_a_frente, agendamento_id_branch,
                  agendamento_id_activities, agendamento_id_service,
                  agendamento_texto_oferta, agendamento_coletar_email
           FROM personalidade_ia
           WHERE empresa_id = $1
           LIMIT 1""",
        empresa_id
    )
    if not row:
        # Retorna um objeto vazio mas estruturado se não existir
        return {
            "nome_ia": "",
            "personalidade": "",
            "instrucoes_base": "",
            "tom_voz": "Profissional",
            "model_name": "gpt-4o-mini",
            "temperature": 0.7,
            "max_tokens": 1000,
            "ativo": False,
            "usar_emoji": True,
            "horario_atendimento_ia": None,
            "horario_comercial": None,
            "menu_triagem": None,
            "tts_ativo": True,
            "tts_voz": "Kore"
        }
    result = dict(row)
    # Deserializar campos JSONB que asyncpg pode retornar como string
    for json_field in ("horario_atendimento_ia", "horario_comercial", "menu_triagem"):
        if isinstance(result.get(json_field), str):
            try:
                result[json_field] = json.loads(result[json_field])
            except (json.JSONDecodeError, ValueError):
                result[json_field] = None
    return result

@router.post("/personality")
async def update_personality(
    data: PersonalityUpdate,
    token_payload: dict = Depends(get_current_user_token)
):
    empresa_id = token_payload.get("empresa_id")

    # Mapeamento para nomes de colunas reais no banco
    update_data = data.model_dump(exclude_unset=True)
    if "model_name" in update_data:
        update_data["modelo_preferido"] = update_data.pop("model_name")
    if "temperature" in update_data:
        update_data["temperatura"] = update_data.pop("temperature")
    if "horario_atendimento_ia" in update_data and update_data["horario_atendimento_ia"] is not None:
        update_data["horario_atendimento_ia"] = json.dumps(update_data["horario_atendimento_ia"])
    if "horario_comercial" in update_data and update_data["horario_comercial"] is not None:
        update_data["horario_comercial"] = json.dumps(update_data["horario_comercial"])
    if "menu_triagem" in update_data and update_data["menu_triagem"] is not None:
        update_data["menu_triagem"] = json.dumps(update_data["menu_triagem"])

    if not update_data:
        return {"status": "no_changes"}

    existing = await _database.db_pool.fetchval(
        "SELECT id FROM personalidade_ia WHERE empresa_id = $1 LIMIT 1", empresa_id
    )

    keys = list(update_data.keys())
    fields = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(keys))
    values = [empresa_id] + [update_data[k] for k in keys]

    if existing:
        await _database.db_pool.execute(
            f"UPDATE personalidade_ia SET {fields}, updated_at = NOW() WHERE empresa_id = $1",
            *values
        )
    else:
        update_data["empresa_id"] = empresa_id
        cols = ", ".join(update_data.keys())
        vals = ", ".join(f"${i+1}" for i in range(len(update_data)))
        await _database.db_pool.execute(
            f"INSERT INTO personalidade_ia ({cols}) VALUES ({vals})",
            *list(update_data.values())
        )

    # Se esta foi marcada como ativa, desativa todas as outras da mesma empresa
    if update_data.get("ativo"):
        await _database.db_pool.execute(
            "UPDATE personalidade_ia SET ativo = false WHERE empresa_id = $1 AND id != (SELECT id FROM personalidade_ia WHERE empresa_id = $1 ORDER BY updated_at DESC LIMIT 1)",
            empresa_id
        )

    # [CACHE-FIX] invalidate_personalidade cobre TUDO: pers + menu_triagem
    # com wildcard :u:* (per-unit) + fluxo_triagem + global + reset de fluxos
    # em andamento. Antes faltavam wildcards e fluxo_triagem ficava stale.
    await invalidate_personalidade(empresa_id)

    # Sincroniza flag Redis de pausa com o campo ativo da personalidade
    if "ativo" in update_data:
        paused_key = f"ia:chatwoot:paused:{empresa_id}"
        if not update_data["ativo"]:
            await redis_client.set(paused_key, "1")
            logger.info(f"⏸️ IA pausada via personalidade para empresa {empresa_id}")
        else:
            await redis_client.delete(paused_key)
            logger.info(f"▶️ IA reativada via personalidade para empresa {empresa_id}")

    return {"status": "success", "message": "Personalidade atualizada"}


# --- Personality CRUD (multi-personality por empresa) ---

@router.get("/personalities")
async def list_personalities(token_payload: dict = Depends(get_current_user_token)):
    """Lista todas as personalidades da empresa."""
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    try:
        rows = await _database.db_pool.fetch(
            """SELECT id, nome_ia, personalidade, instrucoes_base, tom_voz,
                      modelo_preferido AS model_name, temperatura AS temperature,
                      max_tokens, ativo, usar_emoji, horario_atendimento_ia, horario_comercial, menu_triagem,
                      idioma, objetivos_venda, metas_comerciais, script_vendas,
                      scripts_objecoes, frases_fechamento, diferenciais,
                      posicionamento, publico_alvo, restricoes, linguagem_proibida,
                      contexto_empresa, contexto_extra, abordagem_proativa,
                      exemplos, palavras_proibidas, despedida_personalizada,
                      regras_formatacao, regras_seguranca,
                      emoji_tipo, emoji_cor,
                      tts_ativo, tts_voz,
                      oferecer_tour, estrategia_tour,
                      tour_perguntar_primeira_visita, tour_mensagem_custom,
                      agendamento_experimental_ativo, agendamento_provider,
                      agendamento_dias_a_frente, agendamento_id_branch,
                      agendamento_id_activities, agendamento_id_service,
                      agendamento_texto_oferta, agendamento_coletar_email
               FROM personalidade_ia
               WHERE empresa_id = $1
               ORDER BY ativo DESC, id DESC""",
            empresa_id
        )
    except Exception:
        # Fallback enquanto a migration não foi aplicada
        rows = await _database.db_pool.fetch(
            """SELECT id, nome_ia, personalidade, instrucoes_base, tom_voz,
                      modelo_preferido AS model_name, temperatura AS temperature,
                      max_tokens, ativo, true AS usar_emoji,
                      NULL AS horario_atendimento_ia, NULL AS menu_triagem,
                      true AS oferecer_tour, 'smart' AS estrategia_tour,
                      true AS tour_perguntar_primeira_visita, NULL AS tour_mensagem_custom
               FROM personalidade_ia
               WHERE empresa_id = $1
               ORDER BY ativo DESC, id DESC""",
            empresa_id
        )
    result = []
    for r in rows:
        d = dict(r)
        for json_field in ("horario_atendimento_ia", "horario_comercial", "menu_triagem", "agendamento_id_activities"):
            if isinstance(d.get(json_field), str):
                try:
                    d[json_field] = json.loads(d[json_field])
                except (json.JSONDecodeError, ValueError):
                    d[json_field] = None
        result.append(d)
    return result


def _exemplos_para_jsonb(valor):
    """Converte 'exemplos' do payload em JSON valido pro asyncpg mandar como jsonb.
    A coluna no BD e jsonb e nao aceita string crua (string vazia da
    'invalid input syntax for type json'). Aceita None/'', dict/list, ou
    string livre (que vira ['texto'])."""
    if valor is None:
        return None
    if isinstance(valor, str):
        v = valor.strip()
        if not v:
            return None
        try:
            json.loads(v)
            return v
        except (json.JSONDecodeError, ValueError):
            return json.dumps([valor])
    if isinstance(valor, (list, dict)):
        return json.dumps(valor)
    return json.dumps(str(valor))



def _agend_id_acts_to_json(valor):
    """Converte agendamento_id_activities (lista, csv string, ou JSON string) em JSON valido."""
    import json as _j
    if isinstance(valor, list):
        return _j.dumps(valor)
    if isinstance(valor, str) and valor.strip():
        try:
            _j.loads(valor)
            return valor
        except Exception:
            return _j.dumps([int(x.strip()) for x in valor.split(",") if x.strip().isdigit()])
    return "[]"


def _save_agendamento_personalidade_sync_helper():
    pass


@router.post("/personalities", status_code=201)
async def create_personality(
    data: PersonalityCreate,
    token_payload: dict = Depends(get_current_user_token)
):
    """Cria uma nova personalidade para a empresa.

    Como existe constraint UNIQUE(empresa_id), so pode haver UMA personalidade
    por empresa. Se ja existir, este POST redireciona para UPDATE da existente
    (semantica de UPSERT) - o frontend nao precisa saber se e o primeiro save
    ou edicao.
    """
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")

    # UPSERT: se ja existe personalidade pra empresa, faz UPDATE
    existing_id = await _database.db_pool.fetchval(
        "SELECT id FROM personalidade_ia WHERE empresa_id = $1 LIMIT 1",
        empresa_id
    )
    if existing_id:
        logger.info(f"[UPSERT] Personalidade ja existe para empresa {empresa_id}, redirecionando para UPDATE id={existing_id}")
        return await update_personality_by_id(existing_id, data, token_payload)

    try:
        horario_json = json.dumps(data.horario_atendimento_ia) if data.horario_atendimento_ia is not None else None
        horario_comercial_json = json.dumps(data.horario_comercial) if data.horario_comercial is not None else None
        menu_json = json.dumps(data.menu_triagem) if data.menu_triagem is not None else None
        exemplos_json = _exemplos_para_jsonb(data.exemplos)
        row = await _database.db_pool.fetchrow(
            """INSERT INTO personalidade_ia
               (empresa_id, nome_ia, personalidade, instrucoes_base, tom_voz,
                modelo_preferido, temperatura, max_tokens, ativo, usar_emoji,
                horario_atendimento_ia, horario_comercial, menu_triagem,
                idioma, objetivos_venda, metas_comerciais, script_vendas,
                scripts_objecoes, frases_fechamento, diferenciais,
                posicionamento, publico_alvo, restricoes, linguagem_proibida,
                contexto_empresa, contexto_extra, abordagem_proativa,
                exemplos, palavras_proibidas, despedida_personalizada,
                regras_formatacao, regras_seguranca,
                emoji_tipo, emoji_cor,
                tts_ativo, tts_voz,
                oferecer_tour,
                created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12::jsonb,$13::jsonb,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28::jsonb,$29,$30,$31,$32,$33,$34,$35,$36,$37,NOW(),NOW())
               RETURNING id""",
            empresa_id, data.nome_ia, data.personalidade, data.instrucoes_base,
            data.tom_voz, data.model_name, data.temperature, data.max_tokens, data.ativo, data.usar_emoji,
            horario_json, horario_comercial_json, menu_json,
            data.idioma, data.objetivos_venda, data.metas_comerciais, data.script_vendas,
            data.scripts_objecoes, data.frases_fechamento, data.diferenciais,
            data.posicionamento, data.publico_alvo, data.restricoes, data.linguagem_proibida,
            data.contexto_empresa, data.contexto_extra, data.abordagem_proativa,
            exemplos_json, data.palavras_proibidas, data.despedida_personalizada,
            data.regras_formatacao, data.regras_seguranca,
            data.emoji_tipo, data.emoji_cor,
            data.tts_ativo if data.tts_ativo is not None else True, data.tts_voz or "Kore",
            data.oferecer_tour if data.oferecer_tour is not None else True
        )
        new_id = row["id"]

        # Salva comprimento_resposta separadamente (resiliência se migration pendente)
        try:
            comprimento = data.comprimento_resposta or "normal"
            if comprimento not in ("concisa", "normal", "detalhada"):
                comprimento = "normal"
            # [SEC] defense-in-depth: bloqueia IDOR cross-tenant
            await _database.db_pool.execute(
                "UPDATE personalidade_ia SET comprimento_resposta=$1 WHERE id=$2 AND empresa_id=$3",
                comprimento, new_id, empresa_id
            )
        except Exception:
            pass  # Campo pode não existir antes da migration s2t3u4v5w6x7

        # [AGEND-01] Salva campos de agendamento experimental (POST)
        try:
            await _database.db_pool.execute(
                """UPDATE personalidade_ia SET
                    agendamento_experimental_ativo=$1, agendamento_provider=$2,
                    agendamento_dias_a_frente=$3, agendamento_id_branch=$4,
                    agendamento_id_activities=$5::jsonb, agendamento_id_service=$6,
                    agendamento_texto_oferta=$7, agendamento_coletar_email=$8
                   WHERE id=$9 AND empresa_id=$10""",
                bool(data.agendamento_experimental_ativo),
                data.agendamento_provider or "evo",
                int(data.agendamento_dias_a_frente or 5),
                data.agendamento_id_branch,
                _agend_id_acts_to_json(data.agendamento_id_activities),
                data.agendamento_id_service,
                data.agendamento_texto_oferta or "",
                bool(data.agendamento_coletar_email),
                new_id, empresa_id
            )
        except Exception as _ae:
            logger.warning(f"[AGEND-01] save POST falhou: {_ae}")

        # Se esta foi marcada como ativa, desativa todas as outras da mesma empresa
        if data.ativo:
            await _database.db_pool.execute(
                "UPDATE personalidade_ia SET ativo = false WHERE empresa_id = $1 AND id != $2",
                empresa_id, new_id
            )

        # [CACHE-01] Nova personalidade criada — limpa cache
        await invalidate_personalidade(empresa_id)
        return {"id": new_id, "status": "success"}
    except Exception as e:
        logger.error(f"Erro ao criar personalidade: {e}")
        raise HTTPException(status_code=500, detail="Erro ao criar personalidade")


@router.put("/personalities/{pid}")
async def update_personality_by_id(
    pid: int,
    data: PersonalityCreate,
    token_payload: dict = Depends(get_current_user_token)
):
    """[MERGE-safe] Atualiza uma personalidade pelo ID.
    SO atualiza campos enviados explicitamente no payload (exclude_unset).
    Isso evita o bug onde PUT incompleto resetava campos nao enviados pra default."""
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    existing = await _database.db_pool.fetchval(
        "SELECT id FROM personalidade_ia WHERE id = $1 AND empresa_id = $2", pid, empresa_id
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Personalidade não encontrada")

    # [MERGE-SAFE] Pega so campos que vieram explicitamente no PUT
    try:
        enviados = data.model_dump(exclude_unset=True)  # Pydantic v2
    except AttributeError:
        enviados = data.dict(exclude_unset=True)  # Pydantic v1

    # Mapeia nome do field do Pydantic -> nome da coluna no BD
    field_to_col = {
        "nome_ia": "nome_ia", "personalidade": "personalidade",
        "instrucoes_base": "instrucoes_base", "tom_voz": "tom_voz",
        "model_name": "modelo_preferido", "temperature": "temperatura",
        "max_tokens": "max_tokens", "ativo": "ativo", "usar_emoji": "usar_emoji",
        "idioma": "idioma", "objetivos_venda": "objetivos_venda",
        "metas_comerciais": "metas_comerciais", "script_vendas": "script_vendas",
        "scripts_objecoes": "scripts_objecoes", "frases_fechamento": "frases_fechamento",
        "diferenciais": "diferenciais", "posicionamento": "posicionamento",
        "publico_alvo": "publico_alvo", "restricoes": "restricoes",
        "linguagem_proibida": "linguagem_proibida",
        "contexto_empresa": "contexto_empresa", "contexto_extra": "contexto_extra",
        "abordagem_proativa": "abordagem_proativa",
        "palavras_proibidas": "palavras_proibidas",
        "despedida_personalizada": "despedida_personalizada",
        "regras_formatacao": "regras_formatacao",
        "regras_seguranca": "regras_seguranca",
        "emoji_tipo": "emoji_tipo", "emoji_cor": "emoji_cor",
        "estilo_comunicacao": "estilo_comunicacao",
        "saudacao_personalizada": "saudacao_personalizada",
        "regras_atendimento": "regras_atendimento",
        "tts_ativo": "tts_ativo", "tts_voz": "tts_voz",
        "oferecer_tour": "oferecer_tour", "estrategia_tour": "estrategia_tour",
        "tour_perguntar_primeira_visita": "tour_perguntar_primeira_visita",
        "tour_mensagem_custom": "tour_mensagem_custom",
        "comprimento_resposta": "comprimento_resposta",
        "mensagem_fora_horario": "mensagem_fora_horario",
        "agendamento_experimental_ativo": "agendamento_experimental_ativo",
        "agendamento_provider": "agendamento_provider",
        "agendamento_dias_a_frente": "agendamento_dias_a_frente",
        "agendamento_id_branch": "agendamento_id_branch",
        "agendamento_id_service": "agendamento_id_service",
        "agendamento_texto_oferta": "agendamento_texto_oferta",
        "agendamento_coletar_email": "agendamento_coletar_email",
    }

    # Campos JSONB que precisam serializacao especial
    json_fields = {
        "horario_atendimento_ia": "horario_atendimento_ia::jsonb",
        "horario_comercial": "horario_comercial::jsonb",
        "menu_triagem": "menu_triagem::jsonb",
        "exemplos": "exemplos::jsonb",
        "agendamento_id_activities": "agendamento_id_activities::jsonb",
    }

    sets = []
    params = []
    n = 1
    for field, val in enviados.items():
        if field == "id":
            continue
        if field in field_to_col:
            sets.append(f"{field_to_col[field]} = ${n}")
            params.append(val)
            n += 1
        elif field in ("horario_atendimento_ia", "horario_comercial", "menu_triagem"):
            sets.append(f"{field} = ${n}::jsonb")
            params.append(json.dumps(val) if val is not None else None)
            n += 1
        elif field == "exemplos":
            sets.append(f"exemplos = ${n}::jsonb")
            params.append(_exemplos_para_jsonb(val))
            n += 1
        elif field == "agendamento_id_activities":
            sets.append(f"agendamento_id_activities = ${n}::jsonb")
            if isinstance(val, list):
                params.append(json.dumps(val))
            elif isinstance(val, str) and val.strip():
                try:
                    json.loads(val)
                    params.append(val)
                except Exception:
                    params.append(json.dumps([int(x.strip()) for x in val.split(",") if x.strip().isdigit()]))
            else:
                params.append("[]")
            n += 1

    if not sets:
        # Nada pra atualizar (PUT vazio)
        return {"status": "success", "message": "Nenhum campo enviado pra atualizar"}

    sets.append("updated_at = NOW()")
    params.extend([pid, empresa_id])
    sql = f"UPDATE personalidade_ia SET {', '.join(sets)} WHERE id = ${n} AND empresa_id = ${n+1}"

    logger.info(f"💾 [Save Personalidade MERGE] pid={pid} empresa={empresa_id} | {len(enviados)} campos enviados")

    try:
        await _database.db_pool.execute(sql, *params)
    except Exception as e:
        logger.error(f"Erro PUT personalidade pid={pid}: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar: {str(e)[:200]}")

    # Se ativou, desativa as outras da empresa
    if enviados.get("ativo") is True:
        await _database.db_pool.execute(
            "UPDATE personalidade_ia SET ativo = false WHERE empresa_id = $1 AND id != $2",
            empresa_id, pid
        )

    # Sincroniza pause flag se ativo veio
    if "ativo" in enviados:
        paused_key = f"ia:chatwoot:paused:{empresa_id}"
        if not enviados["ativo"]:
            await redis_client.set(paused_key, "1")
        else:
            await redis_client.delete(paused_key)
            logger.info(f"▶️ IA reativada via personalidade (id={pid}) para empresa {empresa_id}")

    await invalidate_personalidade(empresa_id)
    return {"status": "success"}


@router.delete("/personalities/{pid}")
async def delete_personality(
    pid: int,
    token_payload: dict = Depends(get_current_user_token)
):
    """Remove uma personalidade pelo ID."""
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    await _database.db_pool.execute(
        "DELETE FROM personalidade_ia WHERE id = $1 AND empresa_id = $2", pid, empresa_id
    )
    # [CACHE-01] Invalida cache da personalidade (e menu/fluxo que vivem nela)
    await invalidate_personalidade(empresa_id)
    return {"status": "success"}


# --- Preview de Prompt e Templates ---

@router.post("/personalities/{pid}/preview-prompt")
@rate_limit_empresa(max_calls=20, window=60, tag="preview_prompt")
async def preview_personality_prompt(
    pid: int,
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Retorna o system prompt completo que seria enviado ao LLM para esta personalidade.
    Inclui contagem de caracteres e estimativa de tokens.
    Útil para o cliente entender exatamente como a IA está configurada.
    """
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")

    p, _model, _temp, _max_tokens, faq_text, unidades, planos = await _load_playground_context(pid, empresa_id)
    prompt = _build_playground_prompt(p, faq_text=faq_text, unidades=unidades, planos=planos)

    # Extrai os títulos das seções para exibição na UI
    sections = [line.strip("[]") for line in prompt.splitlines() if line.startswith("[") and line.endswith("]")]

    char_count = len(prompt)
    # Estimativa de tokens: ~4 chars por token (regra geral para português)
    estimated_tokens = max(1, char_count // 4)

    return {
        "system_prompt": prompt,
        "char_count": char_count,
        "estimated_tokens": estimated_tokens,
        "sections": sections,
        "model": _model,
        "nome_ia": p.get("nome_ia") or "Assistente",
    }


@router.get("/personality-templates")
async def list_personality_templates(
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Lista templates pré-prontos de personalidade.
    Permitem ao cliente começar com uma configuração de qualidade ao invés de campos em branco.
    """
    templates = [
        {
            "id": "academia_vendas_ativa",
            "nome": "Academia — Vendas Ativas 💪",
            "descricao": "Consultora de vendas animada, proativa, foca em converter leads em alunos.",
            "tom_voz": "Entusiasta",
            "fields": {
                "nome_ia": "Ana",
                "personalidade": "Sou Ana, consultora de vendas da academia. Sou animada, proativa e apaixonada por ajudar pessoas a transformarem suas vidas através do exercício. Celebro cada decisão de começar a treinar!",
                "instrucoes_base": "Seu objetivo principal é converter cada contato em uma matrícula. Identifique o objetivo do cliente (emagrecer, ganhar músculo, saúde, etc.), mostre o plano ideal e crie urgência para fechar.",
                "tom_voz": "Entusiasta",
                "objetivos_venda": "Converter leads em alunos matriculados. Meta: 1 matrícula por cada 3 atendimentos.",
                "script_vendas": "1. Pergunte o objetivo (emagrecer, ganhar músculo, saúde)\n2. Mostre como a academia ajuda nesse objetivo\n3. Apresente o plano mais adequado\n4. Crie urgência (promoção, vaga, etc.)\n5. Direcione para matrícula",
                "frases_fechamento": "Que tal começar hoje mesmo? • Temos uma condição especial para novos alunos! • Sua transformação começa agora!",
                "comprimento_resposta": "concisa",
                "restricoes": "Não falar mal de outras academias. Não prometer resultados físicos específicos.",
            }
        },
        {
            "id": "academia_receptiva",
            "nome": "Academia — Atendente Receptivo 😊",
            "descricao": "Atendente simpático e prestativo, foca em esclarecer dúvidas com clareza.",
            "tom_voz": "Amigável",
            "fields": {
                "nome_ia": "Carol",
                "personalidade": "Sou Carol, atendente virtual da academia. Sou simpática, paciente e sempre disposta a ajudar. Me preocupo em entender o que cada pessoa precisa e oferecer a melhor solução.",
                "instrucoes_base": "Priorize clareza e simpatia. Responda as dúvidas completamente, sugira a melhor opção para o perfil do cliente e sempre convide para uma visita ou agende uma conversa.",
                "tom_voz": "Amigável",
                "objetivos_venda": "Gerar visitas presenciais e conversas com a equipe comercial.",
                "script_vendas": "1. Cumprimente e pergunte como pode ajudar\n2. Esclareça todas as dúvidas com detalhes\n3. Pergunte o objetivo e perfil\n4. Sugira visita ou agendamento",
                "comprimento_resposta": "normal",
                "restricoes": "Não pressionar para matrícula imediata. Sempre dar espaço para o cliente decidir.",
            }
        },
        {
            "id": "academia_premium",
            "nome": "Academia Premium 💎",
            "descricao": "Atendimento exclusivo para academias premium. Tom refinado, foco em experiência.",
            "tom_voz": "Profissional",
            "fields": {
                "nome_ia": "Sofia",
                "personalidade": "Sou Sofia, consultora de bem-estar. Ofereço um atendimento personalizado e exclusivo, focado na experiência completa do membro. Valorizo cada detalhe da jornada de saúde dos nossos clientes.",
                "instrucoes_base": "Tom refinado e profissional. Destaque os diferenciais exclusivos da academia (equipamentos, metodologia, personalização). Foque na experiência e não apenas no preço.",
                "tom_voz": "Profissional",
                "posicionamento": "Academia premium com foco em resultados personalizados e experiência de alto padrão.",
                "diferenciais": "Equipamentos importados, personal trainers certificados internacionalmente, aulas exclusivas, ambiente climatizado.",
                "comprimento_resposta": "normal",
                "restricoes": "Não mencionar preços sem antes apresentar os diferenciais. Nunca comparar com academias populares.",
            }
        },
        {
            "id": "consultora_vendas_generica",
            "nome": "Consultora de Vendas Genérica 📈",
            "descricao": "Template universal para qualquer negócio focado em vendas e conversão.",
            "tom_voz": "Profissional",
            "fields": {
                "nome_ia": "Lia",
                "personalidade": "Sou Lia, consultora especializada em entender as necessidades dos clientes e encontrar a solução ideal para cada um. Sou objetiva, confiante e focada em resultados.",
                "instrucoes_base": "Identifique o problema ou necessidade do cliente, apresente a solução mais adequada, destaque os benefícios e direcione para a conversão.",
                "tom_voz": "Profissional",
                "objetivos_venda": "Converter contatos em clientes através de atendimento consultivo.",
                "script_vendas": "1. Entenda o problema\n2. Apresente a solução\n3. Destaque benefícios\n4. Trate objeções\n5. Direcione para conversão",
                "comprimento_resposta": "concisa",
            }
        },
    ]
    return templates


# --- Fluxo de Triagem Visual (n8n-style) ---

@router.get("/fluxo-triagem")
async def get_fluxo_triagem(token_payload: dict = Depends(get_current_user_token)):
    """Carrega o fluxo visual de triagem da empresa."""
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    try:
        row = await _database.db_pool.fetchrow(
            "SELECT fluxo_triagem FROM personalidade_ia WHERE empresa_id = $1 LIMIT 1",
            empresa_id
        )
        if row and row["fluxo_triagem"]:
            val = row["fluxo_triagem"]
            return json.loads(val) if isinstance(val, str) else val
    except Exception as e:
        logger.warning(f"Erro ao carregar fluxo_triagem empresa {empresa_id}: {e}")
    return {"ativo": False, "nodes": [], "edges": []}


@router.post("/fluxo-triagem")
async def save_fluxo_triagem(
    data: dict,
    token_payload: dict = Depends(get_current_user_token)
):
    """Salva o fluxo visual de triagem da empresa."""
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    try:
        payload = json.dumps(data)
        existing = await _database.db_pool.fetchval(
            "SELECT id FROM personalidade_ia WHERE empresa_id = $1 LIMIT 1", empresa_id
        )
        if existing:
            await _database.db_pool.execute(
                "UPDATE personalidade_ia SET fluxo_triagem = $1::jsonb, updated_at = NOW() WHERE empresa_id = $2",
                payload, empresa_id
            )
        else:
            await _database.db_pool.execute(
                "INSERT INTO personalidade_ia (empresa_id, fluxo_triagem, created_at, updated_at) VALUES ($1, $2::jsonb, NOW(), NOW())",
                empresa_id, payload
            )
        # [CACHE-01] Invalida todas as variantes (global + por unidade) + personalidade/menu
        await invalidate_fluxo_triagem(empresa_id)
        await invalidate_personalidade(empresa_id)
        logger.info(f"✅ Fluxo triagem salvo para empresa {empresa_id} | nodes={len(data.get('nodes', []))} edges={len(data.get('edges', []))}")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Erro ao salvar fluxo_triagem empresa {empresa_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao salvar fluxo: {str(e)}")


# ─────────────────────────────────────────────────────────────
# Flow Templates
# ─────────────────────────────────────────────────────────────

class FlowTemplateCreate(BaseModel):
    nome: str
    categoria: str = "geral"
    descricao: Optional[str] = None
    flow_data: dict
    publico: bool = False


@router.get("/flow-templates")
async def list_flow_templates(
    categoria: Optional[str] = Query(None),
    token_payload: dict = Depends(get_current_user_token)
):
    """Lista templates de fluxo (públicos + da própria empresa)."""
    empresa_id = token_payload.get("empresa_id")
    query = """
        SELECT id, nome, categoria, descricao, publico, empresa_id,
               created_at,
               CASE WHEN empresa_id = $1 THEN true ELSE false END AS proprio
        FROM flow_templates
        WHERE publico = true OR empresa_id = $1
    """
    params = [empresa_id]
    if categoria:
        query += " AND categoria = $2"
        params.append(categoria)
    query += " ORDER BY publico DESC, created_at DESC"
    rows = await _database.db_pool.fetch(query, *params)
    return [dict(r) for r in rows]


@router.post("/flow-templates")
async def create_flow_template(
    payload: FlowTemplateCreate,
    token_payload: dict = Depends(get_current_user_token)
):
    """Salva o fluxo atual como template."""
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    try:
        row = await _database.db_pool.fetchrow(
            """INSERT INTO flow_templates (nome, categoria, descricao, flow_data, empresa_id, publico)
               VALUES ($1, $2, $3, $4::jsonb, $5, $6) RETURNING id""",
            payload.nome, payload.categoria, payload.descricao,
            json.dumps(payload.flow_data), empresa_id, payload.publico
        )
        logger.info(f"✅ Template '{payload.nome}' criado por empresa {empresa_id}")
        return {"status": "ok", "id": row["id"]}
    except Exception as e:
        logger.error(f"Erro ao criar template empresa {empresa_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flow-templates/{template_id}")
async def get_flow_template(
    template_id: int,
    token_payload: dict = Depends(get_current_user_token)
):
    """Carrega um template específico pelo ID."""
    empresa_id = token_payload.get("empresa_id")
    row = await _database.db_pool.fetchrow(
        "SELECT * FROM flow_templates WHERE id = $1 AND (publico = true OR empresa_id = $2)",
        template_id, empresa_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    return dict(row)


@router.delete("/flow-templates/{template_id}")
async def delete_flow_template(
    template_id: int,
    token_payload: dict = Depends(get_current_user_token)
):
    """Remove um template da própria empresa."""
    empresa_id = token_payload.get("empresa_id")
    result = await _database.db_pool.execute(
        "DELETE FROM flow_templates WHERE id = $1 AND empresa_id = $2",
        template_id, empresa_id
    )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Template não encontrado ou sem permissão")
    return {"status": "ok"}


class PlaygroundMessage(BaseModel):
    role: str   # "user" | "assistant"
    content: str

class PlaygroundRequest(BaseModel):
    personality_id: Optional[int] = None   # Se None, usa a personalidade ativa da empresa
    messages: List[PlaygroundMessage] = []
    conversation_summary: Optional[str] = None  # Resumo acumulado para memória de longo prazo

class PlaygroundSummarizeRequest(BaseModel):
    personality_id: Optional[int] = None
    messages: List[PlaygroundMessage] = []


# Campos dinâmicos de "diretrizes de negócio" (mesma lógica do bot_core.py _LABEL_MAP)
_PG_LABEL_MAP = {
    "objetivos_venda":       "OBJETIVOS DE VENDA",
    "metas_comerciais":      "METAS COMERCIAIS",
    "script_vendas":         "SCRIPT DE VENDAS",
    "scripts_objecoes":      "RESPOSTAS A OBJEÇÕES",
    "frases_fechamento":     "FRASES DE FECHAMENTO",
    "diferenciais":          "DIFERENCIAIS DA EMPRESA",
    "posicionamento":        "POSICIONAMENTO DE MERCADO",
    "publico_alvo":          "PÚBLICO-ALVO",
    "linguagem_proibida":    "LINGUAGEM PROIBIDA",
    "contexto_empresa":      "CONTEXTO DA EMPRESA",
    "contexto_extra":        "CONTEXTO EXTRA",
    "abordagem_proativa":    "ABORDAGEM PROATIVA",
}

# Campos que possuem blocos dedicados — NÃO incluir no loop dinâmico
_PG_SKIP_IN_LOOP = {
    "restricoes", "palavras_proibidas", "despedida_personalizada",
    "regras_formatacao", "regras_seguranca", "exemplos", "idioma",
    "estilo_comunicacao", "saudacao_personalizada", "regras_atendimento",
}


def _resumo_unidade_playground(u: dict) -> str:
    """Formata resumo de uma unidade para o prompt do playground (sem tags WhatsApp)."""
    partes = [f"• {u.get('nome', '?')}"]
    cidade = u.get('cidade') or u.get('bairro') or ''
    estado = u.get('estado') or ''
    if cidade or estado:
        partes.append(f"  Localização: {cidade}{', ' + estado if estado else ''}")
    end = u.get('endereco_completo') or u.get('endereco') or ''
    if end:
        partes.append(f"  Endereço: {end}")
    tel = u.get('telefone') or u.get('whatsapp') or ''
    if tel:
        partes.append(f"  Telefone: {tel}")
    hor = u.get('horarios')
    if hor:
        hor_str = hor if isinstance(hor, str) else json.dumps(hor, ensure_ascii=False)
        partes.append(f"  Horários: {hor_str}")
    infra = u.get('infraestrutura')
    if infra:
        if isinstance(infra, dict):
            itens = [k for k, v in infra.items() if v]
            infra_str = ", ".join(itens) if itens else json.dumps(infra, ensure_ascii=False)
        else:
            infra_str = str(infra)
        if infra_str:
            partes.append(f"  Infraestrutura: {infra_str}")
    mods = u.get('modalidades')
    if mods:
        if isinstance(mods, list):
            mods_str = ", ".join(str(m) for m in mods if m)
        elif isinstance(mods, dict):
            mods_str = ", ".join(k for k, v in mods.items() if v)
        else:
            mods_str = str(mods)
        if mods_str:
            partes.append(f"  Modalidades: {mods_str}")
    return "\n".join(partes)


def _build_playground_prompt(p: dict, faq_text: str = "", unidades: list = None, planos: list = None) -> str:
    """
    Constrói o system prompt completo a partir dos campos da personalidade salva.
    Espelha fielmente a estrutura de blocos do bot_core.py para garantir que o
    Playground se comporte identicamente à IA em produção.
    """
    nome   = p.get("nome_ia") or "Assistente"
    idioma = p.get("idioma") or "Português do Brasil"
    blocos: List[str] = []

    # [FIX-K] CONTEXTO TEMPORAL — espelha bot_core. LLM e pessimo em calendar.
    try:
        from datetime import datetime as _dt_pg, timedelta as _td_pg
        from zoneinfo import ZoneInfo as _ZI_pg
        _DIAS_PT_PG = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
                       "sexta-feira", "sábado", "domingo"]
        _MESES_PT_PG = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
                        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
        _agora_pg = _dt_pg.now(_ZI_pg("America/Sao_Paulo"))
        _prox_pg = []
        for _ip in range(7):
            _dp = _agora_pg + _td_pg(days=_ip)
            _lbp = "HOJE" if _ip == 0 else ("AMANHA" if _ip == 1 else f"+{_ip}d")
            _prox_pg.append(
                f"  {_lbp:6s} = {_DIAS_PT_PG[_dp.weekday()]}, {_dp.day:02d}/{_dp.month:02d}/{_dp.year}"
            )
        blocos.append(
            "[CONTEXTO TEMPORAL — DADOS REAIS DO SERVIDOR]\n"
            f"- Agora: {_DIAS_PT_PG[_agora_pg.weekday()]}, {_agora_pg.day} de {_MESES_PT_PG[_agora_pg.month-1]} de {_agora_pg.year}, "
            f"{_agora_pg.hour:02d}h{_agora_pg.minute:02d} (horário de São Paulo).\n"
            "- Próximos 7 dias (use SEMPRE estes valores, NUNCA calcule sozinho):\n"
            + "\n".join(_prox_pg) + "\n"
            "- Quando o cliente disser 'amanhã', 'segunda', 'sexta que vem' etc, "
            "use a data REAL desta tabela. NUNCA invente dia da semana — você sempre erra. "
            "Quando mostrar uma data ao cliente, use o formato 'sexta-feira, 1 de maio às 09h00'."
        )
    except Exception:
        pass

    # 1. Regras gerais (linguagem + comportamento base)
    blocos.append(
        f"[REGRAS GERAIS]\n"
        f"- Idioma obrigatório: {idioma}.\n"
        f"- NUNCA use inglês ou outros idiomas a menos que o cliente use.\n"
        f"- NUNCA mostre tags internas, avisos de sistema ou colunas técnicas.\n"
        f"- NUNCA se apresente como IA ou robô.\n"
        f"- DATA/HORA: use SEMPRE o bloco [CONTEXTO TEMPORAL] acima. NUNCA chute weekday."
    )

    # 2. Identidade
    blocos.append(f"[IDENTIDADE]\nVocê é {nome}, assistente virtual desta empresa.")

    # 3. Personalidade
    if p.get("personalidade"):
        blocos.append(f"[PERSONALIDADE]\n{p['personalidade']}")

    # 4. Tom de voz
    if p.get("tom_voz"):
        blocos.append(f"[TOM DE VOZ]\n{p['tom_voz']}")

    # 5. Estilo de comunicação
    estilo = p.get("estilo_comunicacao") or ""
    if estilo.strip():
        blocos.append(f"[ESTILO DE COMUNICAÇÃO]\n{estilo}")

    # 6. Saudação padrão
    saudacao = p.get("saudacao_personalizada") or ""
    if saudacao.strip():
        blocos.append(f"[SAUDAÇÃO PADRÃO]\n{saudacao}")

    # 7. Instruções base
    if p.get("instrucoes_base"):
        blocos.append(f"[INSTRUÇÕES BASE]\n{p['instrucoes_base']}")

    # 8. Diretrizes de negócio (campos dinâmicos — sem duplicar blocos dedicados)
    extras = ""
    for campo, titulo in _PG_LABEL_MAP.items():
        if campo in _PG_SKIP_IN_LOOP:
            continue
        valor = p.get(campo)
        if valor and str(valor).strip():
            extras += f"\n\n[{titulo}]\n{valor}"
    if extras:
        blocos.append(f"[DIRETRIZES DE NEGÓCIO]{extras}")

    # 9. Regras de atendimento
    regras_atend = p.get("regras_atendimento") or ""
    if regras_atend.strip():
        blocos.append(f"[REGRAS DE ATENDIMENTO]\n{regras_atend}")

    # [AGEND-02 Playground] Bloco de agendamento — espelha o bot_core
    _bloco_agend = _agend_bloco_prompt(p)
    if _bloco_agend:
        blocos.append(_bloco_agend)

    # 9.5 Fluxo de Vendedor Real (proatividade) — exemplos SEM valores hardcoded
    blocos.append("""[FLUXO DE VENDEDOR — OBRIGATÓRIO]
Você é um VENDEDOR, não um robô de FAQ. Siga este fluxo SEMPRE:
1. Responda a pergunta do cliente de forma direta e curta.
2. Depois da resposta, faça UMA pergunta de descoberta que avance a conversa.

Padrão de resposta (use SEMPRE os DADOS REAIS configurados — nunca invente valores):
• "Tem diária?" → consulte o campo diaria_disponivel da unidade.
   Se sim: informe o valor REAL da diária (campo diaria_valor) e pergunte se quer só treinar hoje ou começar.
   Se não: explique que essa unidade não trabalha com diária e pergunte o objetivo do cliente.
• "Qual o horário?" → use os horários REAIS da unidade selecionada.
• "Quanto custa?" → use os planos REAIS configurados.
• "Quero começar" → pergunte qual unidade fica mais perto.

REGRAS:
- Resposta + pergunta de descoberta na MESMA mensagem.
- A pergunta deve descobrir algo sobre o cliente (objetivo, frequência, localização, urgência).
- NUNCA invente valores, horários, serviços ou ofertas — use APENAS os dados configurados.
- Se o cliente já respondeu uma descoberta, avance pro próximo passo (mostrar plano, agendar visita).
- NUNCA peça dados pessoais para cadastro (CPF, endereço completo). Você é um vendedor, não um formulário. Se o cliente quiser se matricular, direcione à unidade ou recepção.
- Use emojis SOMENTE se a configuração [CONTROLES DE RESPOSTA] permitir. Caso contrário, texto puro.""")

    # 10. Unidades da rede
    if unidades:
        nomes_unidades = ", ".join(u.get("nome", "?") for u in unidades)
        resumos = "\n\n".join(_resumo_unidade_playground(u) for u in unidades)
        nome_empresa = unidades[0].get("nome_empresa") or "Nossa Empresa"
        qtd = len(unidades)
        contexto_rede = (
            f"A rede {nome_empresa} possui {qtd} unidades ativas."
            if qtd > 1 else
            f"A rede {nome_empresa} está operando com 1 unidade ativa."
        )
        blocos.append(
            f"[UNIDADES DA REDE]\n"
            f"{contexto_rede}\n"
            f"Unidades: {nomes_unidades}\n\n"
            f"{resumos}"
        )

    # 11. Planos e preços
    if planos:
        planos_texto = formatar_planos_para_prompt(planos)
        blocos.append(
            f"[PLANOS E PREÇOS]\n"
            f"Planos disponíveis (com links de matrícula):\n"
            f"{planos_texto}"
        )

    # 12. FAQ (respostas prontas)
    if faq_text.strip():
        blocos.append(f"[FAQ — RESPOSTAS PRONTAS]\n{faq_text}")

    # 13. Exemplos de interações
    if p.get("exemplos"):
        blocos.append(f"[EXEMPLOS DE INTERAÇÕES]\n{p['exemplos']}")

    # 14. Regras de sistema
    regras_seg = p.get("regras_seguranca") or ""
    bloco_sistema = (
        "[REGRAS DE SISTEMA]\n"
        "- Responda diretamente se tiver os dados disponíveis.\n"
        "- Se o cliente enviar apenas saudação social, responda somente saudação e pergunte como ajudar.\n"
        "- Seja honesto: se não souber algo, diga que vai verificar."
    )
    if regras_seg.strip():
        bloco_sistema += f"\n{regras_seg}"
    blocos.append(bloco_sistema)

    # 15. Anti-alucinação
    restricoes       = p.get("restricoes") or ""
    palavras_proib   = p.get("palavras_proibidas") or ""
    bloco_anti = (
        "[REGRAS CRÍTICAS — ANTI-ALUCINAÇÃO]\n"
        "- Use EXCLUSIVAMENTE os dados fornecidos neste prompt.\n"
        "- Se não souber, diga que não tem a informação.\n"
        "- Nunca invente endereços, telefones, horários ou valores."
    )
    if restricoes.strip():
        bloco_anti += f"\n- RESTRIÇÕES: {restricoes}"
    if palavras_proib.strip():
        bloco_anti += f"\n- NUNCA USE ESTAS PALAVRAS/TERMOS: {palavras_proib}"
    blocos.append(bloco_anti)

    # 16. Formatação WhatsApp
    usar_emoji = p.get("usar_emoji", True)
    emoji_tipo = p.get("emoji_tipo") or "✨"
    emoji_cor  = p.get("emoji_cor") or ""
    r_format   = p.get("regras_formatacao") or ""
    bloco_fmt = (
        "[FORMATAÇÃO WHATSAPP]\n"
        "- Use *bold* para destaque. Listas com •.\n"
        "- Separe blocos com linha em branco.\n"
        "- NUNCA use markdown (**, ##, ```).\n"
        "- Tamanho ideal: 2-4 parágrafos curtos.\n"
        "- TERMINAR sempre com frases completas."
    )
    if usar_emoji and emoji_tipo:
        bloco_fmt += f"\n- EMOJI PRINCIPAL DA IA: {emoji_tipo}. Use-o com frequência."
    if emoji_cor:
        bloco_fmt += f"\n- PALETA DE CORES/VIBE: {emoji_cor}. Priorize emojis que combinem com esta cor."
    if not usar_emoji:
        bloco_fmt += "\n- NÃO use emojis nas respostas."
    if r_format.strip():
        bloco_fmt += f"\n{r_format}"
    blocos.append(bloco_fmt)

    # 17. Despedida padrão
    despedida = p.get("despedida_personalizada") or ""
    if despedida.strip():
        blocos.append(f"[DESPEDIDA PADRÃO]\n{despedida}")

    # 18. Controle de verbosidade (comprimento das respostas)
    _VERBOSIDADE_MAP = {
        "concisa":   (
            "[TAMANHO DE RESPOSTA — OBRIGATÓRIO]\n"
            "- Responda em no máximo 2–3 frases por mensagem.\n"
            "- Seja direto e objetivo. Elimine qualquer texto desnecessário.\n"
            "- NUNCA use listas, enumerações ou parágrafos longos.\n"
            "- Uma ideia por mensagem. Se precisar de mais, faça em mensagens separadas."
        ),
        "normal":    (
            "[TAMANHO DE RESPOSTA]\n"
            "- Respostas entre 3–5 frases. Balance completude e concisão.\n"
            "- Use listas apenas quando a comparação de opções for essencial."
        ),
        "detalhada": (
            "[TAMANHO DE RESPOSTA]\n"
            "- Pode detalhar quando o cliente demonstrar interesse ou pedir mais informações.\n"
            "- Use listas e estrutura quando ajudar a clareza da resposta."
        ),
    }
    verbosidade = p.get("comprimento_resposta") or "normal"
    if verbosidade in _VERBOSIDADE_MAP:
        blocos.append(_VERBOSIDADE_MAP[verbosidade])

    return "\n\n".join(blocos)


@router.post("/personalities/playground")
@rate_limit_empresa(max_calls=10, window=60, tag="playground")
async def personality_playground(
    body: PlaygroundRequest,
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Executa o Playground usando 100% os dados da personalidade salva no banco.
    Carrega modelo, temperatura, max_tokens, personalidade, FAQ, unidades e planos do DB.
    """
    from src.services.llm_service import cliente_ia

    if not cliente_ia:
        raise HTTPException(status_code=503, detail="Serviço de IA não configurado (OPENROUTER_API_KEY ausente)")

    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada ao token")

    p, model, temperature, max_tokens, faq_text, unidades, planos = await _load_playground_context(
        body.personality_id, empresa_id
    )

    system_prompt = _build_playground_prompt(p, faq_text=faq_text, unidades=unidades, planos=planos)
    if body.conversation_summary and body.conversation_summary.strip():
        system_prompt += (
            f"\n\n[CONTEXTO DA CONVERSA ANTERIOR]\n"
            f"Resumo do que foi discutido até agora (use para manter continuidade):\n"
            f"{body.conversation_summary}"
        )

    # Monta histórico — janela deslizante (últimas 20 mensagens) para não estourar tokens
    msgs: List[dict] = [{"role": "system", "content": system_prompt}]
    recent_messages = body.messages[-20:] if len(body.messages) > 20 else body.messages
    for m in recent_messages:
        if m.role in ("user", "assistant"):
            msgs.append({"role": m.role, "content": m.content})

    try:
        response = await asyncio.wait_for(
            cliente_ia.chat.completions.create(
                model=model,
                messages=msgs,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            timeout=30
        )
        reply = response.choices[0].message.content or ""

        # [AGEND-02 Playground] Loop de TOOL CALL — executa <TOOL>...</TOOL>
        # e re-chama o LLM com o resultado. Max 3 iteracoes.
        if p.get("agendamento_experimental_ativo"):
            _pg_conv_id = -(int(p.get("id") or 0))  # id sintetico estavel
            _tool_iters = 0
            while _tool_iters < 3:
                _tool_call = _agend_detectar_tool(reply or "")
                if not _tool_call:
                    break
                _tool_iters += 1
                logger.info(f"🛠️ [PG-AGEND] tool_call iter={_tool_iters}: {_tool_call.get('name')}")
                _resultado = await _agend_executar_tool(
                    name=_tool_call.get("name", ""),
                    args=_tool_call.get("args") or {},
                    empresa_id=empresa_id,
                    conversation_id=_pg_conv_id,
                    contato_fone=None,
                    pers=p,
                    unidade_id=None,
                )
                msgs.append({"role": "assistant", "content": reply})
                # [FIX-Gemini] usar role='user' em vez de 'system' — Gemini retorna
                # content=None se receber 'system' no meio da conversa apos um
                # 'assistant'. Formato conversacional funciona melhor.
                msgs.append({
                    "role": "user",
                    "content": (
                        f"[Sistema retornou da ferramenta '{_tool_call.get('name')}']\n"
                        f"{json.dumps(_resultado, ensure_ascii=False, default=str)}\n\n"
                        "Agora gere uma resposta em portugues natural pro cliente "
                        "(sem usar <TOOL>, sem mencionar 'sistema' ou 'ferramenta'). "
                        "Se ha 'instrucao_ia' no resultado, siga ela."
                    ),
                })
                try:
                    response = await asyncio.wait_for(
                        cliente_ia.chat.completions.create(
                            model=model, messages=msgs,
                            temperature=temperature, max_tokens=max_tokens,
                        ),
                        timeout=30,
                    )
                    reply = response.choices[0].message.content or ""
                except Exception as _et:
                    logger.warning(f"[PG-AGEND] re-chamada apos tool falhou: {_et}")
                    break

        return {
            "reply": reply,
            "model": model,
            "nome_ia": p.get("nome_ia") or "Assistente",
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="IA demorou demais para responder. Tente novamente.")
    except Exception as e:
        logger.error(f"Playground LLM error: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao chamar a IA: {str(e)[:200]}")


# ─── Playground helpers ──────────────────────────────────────────────────────

async def _load_playground_context(personality_id: Optional[int], empresa_id: int):
    """Carrega personalidade + FAQ + unidades + planos + configs LLM. Reutilizado por todos os endpoints de playground."""
    if personality_id:
        row = await _database.db_pool.fetchrow(
            "SELECT * FROM personalidade_ia WHERE id = $1 AND empresa_id = $2",
            personality_id, empresa_id
        )
    else:
        row = await _database.db_pool.fetchrow(
            "SELECT * FROM personalidade_ia WHERE empresa_id = $1 AND ativo = true ORDER BY updated_at DESC LIMIT 1",
            empresa_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Personalidade não encontrada. Salve antes de testar.")

    p = dict(row)
    model       = p.get("modelo_preferido") or "openai/gpt-4o-mini"
    temperature = float(p.get("temperatura") or 0.7)
    max_tokens  = int(p.get("max_tokens") or 1000)

    faq_text = ""
    try:
        faq_rows = await _database.db_pool.fetch(
            "SELECT pergunta, resposta FROM faq WHERE empresa_id = $1 AND ativo = true ORDER BY prioridade DESC NULLS LAST LIMIT 30",
            empresa_id
        )
        if faq_rows:
            faq_text = "\n\n".join(f"P: {r['pergunta']}\nR: {r['resposta']}" for r in faq_rows)
    except Exception:
        pass

    # Carregar unidades ativas da empresa
    try:
        todas_unidades = await listar_unidades_ativas(empresa_id)
    except Exception:
        todas_unidades = []

    # Carregar todos os planos ativos da empresa
    try:
        planos_ativos = await buscar_planos_ativos(empresa_id)
    except Exception:
        planos_ativos = []

    return p, model, temperature, max_tokens, faq_text, todas_unidades, planos_ativos


@router.post("/personalities/playground/stream")
@rate_limit_empresa(max_calls=5, window=60, tag="playground_stream")
async def personality_playground_stream(
    body: PlaygroundRequest,
    token_payload: dict = Depends(get_current_user_token)
):
    """Playground com streaming SSE — resposta token a token."""
    from src.services.llm_service import cliente_ia

    if not cliente_ia:
        raise HTTPException(status_code=503, detail="Serviço de IA não configurado")

    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada ao token")

    p, model, temperature, max_tokens, faq_text, unidades, planos = await _load_playground_context(
        body.personality_id, empresa_id
    )

    system_prompt = _build_playground_prompt(p, faq_text=faq_text, unidades=unidades, planos=planos)
    if body.conversation_summary and body.conversation_summary.strip():
        system_prompt += (
            f"\n\n[CONTEXTO DA CONVERSA ANTERIOR]\n"
            f"Resumo do que foi discutido até agora (use para manter continuidade):\n"
            f"{body.conversation_summary}"
        )

    msgs: List[dict] = [{"role": "system", "content": system_prompt}]
    recent_messages = body.messages[-20:] if len(body.messages) > 20 else body.messages
    for m in recent_messages:
        if m.role in ("user", "assistant"):
            msgs.append({"role": m.role, "content": m.content})

    nome_ia = p.get("nome_ia") or "Assistente"

    # [AGEND-02 PG-Stream] Quando agendamento ativo, primeiro buffer pra detectar
    # tool call. Se houver, executa e refaz o stream com resultado. Caso contrario,
    # stream normal token a token.
    _agend_ativo = bool(p.get("agendamento_experimental_ativo"))

    async def event_generator():
        try:
            if _agend_ativo:
                # Buffer primeira resposta inteira pra detectar <TOOL>
                resp1 = await asyncio.wait_for(
                    cliente_ia.chat.completions.create(
                        model=model, messages=msgs,
                        temperature=temperature, max_tokens=max_tokens,
                    ),
                    timeout=30,
                )
                reply_buf = resp1.choices[0].message.content or ""

                # Se tem tool call, executa e re-chama LLM em modo stream
                _tool_call = _agend_detectar_tool(reply_buf)
                if _tool_call:
                    _pg_conv_id = -(int(p.get("id") or 0))
                    logger.info(f"🛠️ [PG-Stream-AGEND] tool: {_tool_call.get('name')}")
                    _resultado = await _agend_executar_tool(
                        name=_tool_call.get("name", ""),
                        args=_tool_call.get("args") or {},
                        empresa_id=empresa_id,
                        conversation_id=_pg_conv_id,
                        contato_fone=None,
                        pers=p,
                        unidade_id=None,
                    )
                    msgs.append({"role": "assistant", "content": reply_buf})
                    msgs.append({
                        "role": "user",
                        "content": (
                            f"[Sistema retornou da ferramenta '{_tool_call.get('name')}']\n"
                            f"{json.dumps(_resultado, ensure_ascii=False, default=str)}\n\n"
                            "Agora gere uma resposta em portugues natural pro cliente "
                            "(sem usar <TOOL>, sem mencionar 'sistema' ou 'ferramenta'). "
                            "Se ha 'instrucao_ia' no resultado, siga ela."
                        ),
                    })
                    # Stream da resposta final apos tool
                    stream2 = await asyncio.wait_for(
                        cliente_ia.chat.completions.create(
                            model=model, messages=msgs,
                            temperature=temperature, max_tokens=max_tokens,
                            stream=True,
                        ),
                        timeout=30,
                    )
                    async for chunk in stream2:
                        delta = chunk.choices[0].delta if chunk.choices else None
                        if delta and delta.content:
                            payload = json.dumps({"token": delta.content}, ensure_ascii=False)
                            yield f"data: {payload}\n\n"
                else:
                    # Sem tool — stream do buffer em chunks pra simular streaming
                    for i in range(0, len(reply_buf), 20):
                        payload = json.dumps({"token": reply_buf[i:i+20]}, ensure_ascii=False)
                        yield f"data: {payload}\n\n"
                        await asyncio.sleep(0.02)
            else:
                # Sem agendamento — stream normal direto do LLM
                stream = await asyncio.wait_for(
                    cliente_ia.chat.completions.create(
                        model=model,
                        messages=msgs,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=True,
                    ),
                    timeout=30
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        payload = json.dumps({"token": delta.content}, ensure_ascii=False)
                        yield f"data: {payload}\n\n"

            # Evento final (comum aos 3 caminhos)
            done_payload = json.dumps({"done": True, "model": model, "nome_ia": nome_ia}, ensure_ascii=False)
            yield f"data: {done_payload}\n\n"
        except asyncio.TimeoutError:
            err = json.dumps({"error": "IA demorou demais para responder."}, ensure_ascii=False)
            yield f"data: {err}\n\n"
        except Exception as e:
            logger.error(f"Playground stream error: {e}")
            err = json.dumps({"error": str(e)[:200]}, ensure_ascii=False)
            yield f"data: {err}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/personalities/playground/summarize")
async def personality_playground_summarize(
    body: PlaygroundSummarizeRequest,
    token_payload: dict = Depends(get_current_user_token)
):
    """Gera resumo da conversa para memória de longo prazo do playground."""
    from src.services.llm_service import cliente_ia

    if not cliente_ia:
        raise HTTPException(status_code=503, detail="Serviço de IA não configurado")

    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada ao token")

    if len(body.messages) < 4:
        return {"summary": ""}

    p, model, _, _, _, _, _ = await _load_playground_context(body.personality_id, empresa_id)
    nome_ia = p.get("nome_ia") or "Assistente"

    # Monta conversa formatada para o sumarizador
    convo_lines = []
    for m in body.messages:
        speaker = "Usuário" if m.role == "user" else nome_ia
        convo_lines.append(f"{speaker}: {m.content}")
    convo_text = "\n".join(convo_lines)

    summary_prompt = (
        "Você é um assistente que cria resumos concisos de conversas.\n"
        "Analise a conversa abaixo e crie um resumo em 3-5 bullet points.\n"
        "Capture: preferências do usuário, decisões tomadas, contexto importante e tom da conversa.\n"
        "Responda APENAS com os bullet points, sem introdução.\n\n"
        f"--- CONVERSA ---\n{convo_text}\n--- FIM ---"
    )

    try:
        response = await asyncio.wait_for(
            cliente_ia.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": summary_prompt}],
                temperature=0.3,
                max_tokens=300,
            ),
            timeout=20
        )
        summary = response.choices[0].message.content or ""
        return {"summary": summary.strip()}
    except Exception as e:
        logger.error(f"Playground summarize error: {e}")
        return {"summary": ""}


# --- TTS (Vozes) Endpoints ---

@router.get("/tts/voices")
async def list_tts_voices(token_payload: dict = Depends(get_current_user_token)):
    """Lista todas as vozes TTS disponíveis (Gemini)."""
    from src.services.tts_service import listar_vozes
    return {"voices": listar_vozes()}


@router.post("/tts/preview")
@rate_limit_empresa(max_calls=15, window=60, tag="tts_preview")
async def preview_tts_voice(
    body: dict,
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Gera preview de áudio para uma voz TTS.
    Body: {"voz": "Kore", "texto": "opcional"}
    Retorna URL do áudio gerado (via ImageKit).
    """
    from src.services.tts_service import gerar_audio_resposta, gerar_preview_voz, VOZES
    from src.utils.imagekit import upload_to_imagekit
    import uuid

    voz = body.get("voz", "Kore")
    texto = body.get("texto")

    if voz not in VOZES:
        raise HTTPException(status_code=400, detail=f"Voz '{voz}' não encontrada")

    try:
        if texto:
            audio_bytes = await gerar_audio_resposta(texto, voz=voz)
        else:
            audio_bytes = await gerar_preview_voz(voz)

        if not audio_bytes:
            raise HTTPException(status_code=503, detail="Falha ao gerar áudio TTS")

        # Upload para ImageKit
        audio_url = await upload_to_imagekit(
            audio_bytes,
            f"preview_{voz}_{uuid.uuid4().hex[:6]}.wav",
            folder="/tts/previews"
        )

        if not audio_url:
            raise HTTPException(status_code=503, detail="Falha no upload do áudio")

        return {"url": audio_url, "voz": voz}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro preview TTS: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao gerar preview")


# --- FAQ Endpoints ---

@router.get("/faq")
async def list_faq(token_payload: dict = Depends(get_current_user_token)):
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada ao usuário")

    rows = await _database.db_pool.fetch(
        "SELECT id, pergunta, resposta, unidade_id, todas_unidades, prioridade, ativo FROM faq WHERE empresa_id = $1 ORDER BY prioridade DESC, id DESC",
        empresa_id
    )

    # Compatibilidade com dados legados: alguns registros antigos podem estar sem empresa_id.
    # Nesses casos, expõe apenas FAQs vinculados a unidades da empresa atual.
    if not rows:
        rows = await _database.db_pool.fetch(
            """
            SELECT f.id, f.pergunta, f.resposta, f.unidade_id,
                   COALESCE(f.todas_unidades, false) AS todas_unidades,
                   COALESCE(f.prioridade, 0) AS prioridade,
                   COALESCE(f.ativo, true) AS ativo
            FROM faq f
            WHERE f.empresa_id IS NULL
              AND f.unidade_id IN (SELECT id FROM unidades WHERE empresa_id = $1)
            ORDER BY COALESCE(f.prioridade, 0) DESC, f.id DESC
            """,
            empresa_id
        )

    return [dict(r) for r in rows]

@router.post("/faq")
async def create_faq(body: FAQCreate, token_payload: dict = Depends(get_current_user_token)):
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada ao usuário")
    try:
        await _database.db_pool.execute(
            """INSERT INTO faq (empresa_id, pergunta, resposta, unidade_id, todas_unidades, prioridade, ativo, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, true, NOW())""",
            empresa_id, body.pergunta, body.resposta, body.unidade_id, body.todas_unidades, body.prioridade
        )
    except Exception as e:
        logger.error(f"Erro ao criar FAQ para empresa {empresa_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar pergunta. Tente novamente.")
    # [CACHE-01] Nova pergunta de FAQ — limpa cache de todas as unidades
    await invalidate_faq(empresa_id)
    return {"status": "success"}

@router.put("/faq/{faq_id}")
async def update_faq(faq_id: int, body: FAQCreate, token_payload: dict = Depends(get_current_user_token)):
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada ao usuário")
    try:
        result = await _database.db_pool.execute(
            """UPDATE faq SET pergunta=$1, resposta=$2, unidade_id=$3, todas_unidades=$4, prioridade=$5, updated_at=NOW()
               WHERE id=$6 AND empresa_id=$7""",
            body.pergunta, body.resposta, body.unidade_id, body.todas_unidades, body.prioridade, faq_id, empresa_id
        )
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Pergunta não encontrada.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao atualizar FAQ {faq_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro ao atualizar pergunta. Tente novamente.")
    # [CACHE-01] FAQ editado — limpa cache pra proxima resposta usar o novo conteudo
    await invalidate_faq(empresa_id)
    return {"status": "success"}

@router.delete("/faq/{faq_id}")
async def delete_faq(faq_id: int, token_payload: dict = Depends(get_current_user_token)):
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada ao usuário")
    try:
        await _database.db_pool.execute("DELETE FROM faq WHERE id=$1 AND empresa_id=$2", faq_id, empresa_id)
        # [CACHE-01] FAQ deletado — limpa cache
        await invalidate_faq(empresa_id)
    except Exception as e:
        logger.error(f"Erro ao excluir FAQ {faq_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro ao excluir pergunta. Tente novamente.")
    return {"status": "success"}

# --- Debug Endpoint (temporário) ---

@router.get("/debug/me")
async def debug_me(token_payload: dict = Depends(get_current_user_token)):
    """Diagnóstico: retorna o que o JWT contém e o que há no banco para esse usuário."""
    email = token_payload.get("sub")
    empresa_id = token_payload.get("empresa_id")
    perfil = token_payload.get("perfil")

    # Busca empresa_id direto do banco pelo email
    db_empresa_id = await _database.db_pool.fetchval(
        "SELECT empresa_id FROM usuarios WHERE email = $1", email
    )
    db_perfil = await _database.db_pool.fetchval(
        "SELECT perfil FROM usuarios WHERE email = $1", email
    )

    # Conta integrações para o empresa_id do banco
    count_int = await _database.db_pool.fetchval(
        "SELECT COUNT(*) FROM integracoes WHERE empresa_id = $1", db_empresa_id
    ) if db_empresa_id else 0

    # Conta unidades para o empresa_id do banco
    count_units = await _database.db_pool.fetchval(
        "SELECT COUNT(*) FROM unidades WHERE empresa_id = $1 AND ativa = true", db_empresa_id
    ) if db_empresa_id else 0

    # Lista tipos de integração
    tipos = await _database.db_pool.fetch(
        "SELECT tipo, unidade_id, ativo FROM integracoes WHERE empresa_id = $1", db_empresa_id
    ) if db_empresa_id else []

    return {
        "jwt": {"email": email, "empresa_id": empresa_id, "perfil": perfil},
        "db": {"empresa_id": db_empresa_id, "perfil": db_perfil},
        "integracoes_count": count_int,
        "unidades_ativas_count": count_units,
        "integracoes_tipos": [{"tipo": r["tipo"], "unidade_id": r["unidade_id"], "ativo": r["ativo"]} for r in tipos],
    }


# --- Integrations Endpoints ---
# _resolve_empresa_id está definida acima (linha ~158) — não duplicar aqui.




@router.get("/integrations/chatwoot/ai-status")
async def get_chatwoot_ai_status(token_payload: dict = Depends(get_current_user_token)):
    """Status global da IA para mensagens do Chatwoot (por empresa)."""
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")

    paused = await redis_client.get(f"ia:chatwoot:paused:{empresa_id}") == "1"
    return {"ai_active": not paused}


@router.put("/integrations/chatwoot/ai-status")
async def set_chatwoot_ai_status(body: dict, token_payload: dict = Depends(get_current_user_token)):
    """Ativa/pausa globalmente o atendimento da IA no canal Chatwoot."""
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")

    ai_active = bool(body.get("ai_active", True))
    key = f"ia:chatwoot:paused:{empresa_id}"
    if ai_active:
        await redis_client.delete(key)
    else:
        await redis_client.set(key, "1")

    return {"status": "success", "ai_active": ai_active}

@router.get("/integrations")
async def get_integrations(token_payload: dict = Depends(get_current_user_token)):
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        return []

    # Retorna a melhor config por tipo (prefere unidade_id NULL, mas aceita qualquer).
    # EVO é excluído — gerenciado pelo endpoint /evo/units.
    rows = await _database.db_pool.fetch(
        """
        SELECT DISTINCT ON (tipo) id, tipo, config, ativo, updated_at
        FROM integracoes
        WHERE empresa_id = $1 AND tipo != 'evo'
        ORDER BY tipo, (unidade_id IS NULL) DESC, id DESC
        """,
        empresa_id
    )
    result = []
    for r in rows:
        d = dict(r)
        if d.get("updated_at"):
            d["updated_at"] = d["updated_at"].isoformat()
        result.append(d)
    return result


@router.get("/integrations/evo/units")
async def get_evo_per_unit_list(token_payload: dict = Depends(get_current_user_token)):
    """Retorna a configuração EVO para cada unidade ativa da empresa."""
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")

    units = await _database.db_pool.fetch(
        "SELECT id, nome FROM unidades WHERE empresa_id = $1 AND ativa = true ORDER BY nome",
        empresa_id
    )
    configs = await _database.db_pool.fetch(
        "SELECT unidade_id, config, ativo FROM integracoes WHERE empresa_id = $1 AND tipo = 'evo' AND unidade_id IS NOT NULL",
        empresa_id
    )

    config_map = {}
    for r in configs:
        c = r["config"]
        if isinstance(c, str):
            try: c = json.loads(c)
            except Exception: c = {}
        # Ensure unidade_id is treated as string for the map key
        config_map[str(r["unidade_id"])] = {"config": c, "ativo": r["ativo"]}

    result = []
    for u in units:
        entry = config_map.get(str(u["id"]))
        result.append({
            "unidade_id": u["id"],
            "unidade_nome": u["nome"],
            "config": entry["config"] if entry else {"dns": "", "secret_key": ""},
            "ativo": entry["ativo"] if entry else False,
            "configurado": bool(entry and entry["config"].get("dns")),
        })
    return result


@router.put("/integrations/evo/unit/{unidade_id}")
async def update_evo_unit(
    unidade_id: int,
    body: IntegrationUpdate,
    token_payload: dict = Depends(get_current_user_token),
):
    """Salva a configuração EVO de uma unidade específica."""
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")

    existing = await _database.db_pool.fetchval(
        "SELECT id FROM integracoes WHERE empresa_id = $1 AND tipo = 'evo' AND unidade_id = $2",
        empresa_id, unidade_id
    )
    config_json = json.dumps(body.config)
    if existing:
        await _database.db_pool.execute(
            "UPDATE integracoes SET config = $1::jsonb, ativo = $2, updated_at = NOW() WHERE id = $3",
            config_json, body.ativo, existing
        )
    else:
        await _database.db_pool.execute(
            "INSERT INTO integracoes (empresa_id, tipo, config, ativo, unidade_id, created_at) VALUES ($1, 'evo', $2::jsonb, $3, $4, NOW())",
            empresa_id, config_json, body.ativo, unidade_id
        )

    # [CACHE-01] Invalida cache da integração EVO (todas as variantes da empresa)
    await invalidate_integracao(empresa_id, tipo="evo")

    return {"status": "success"}


# ────────── EVO FRANQUEADA (consulta de aluno por telefone — escopo restrito) ──────────

@router.get("/integrations/evo-franqueada/units")
async def get_evo_franqueada_per_unit_list(token_payload: dict = Depends(get_current_user_token)):
    """Lista todas as unidades + config 'evo_franqueada' (cred SOMENTE pra consulta de aluno)."""
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")

    units = await _database.db_pool.fetch(
        "SELECT id, nome FROM unidades WHERE empresa_id = $1 AND ativa = true ORDER BY nome",
        empresa_id
    )
    configs = await _database.db_pool.fetch(
        "SELECT unidade_id, config, ativo FROM integracoes WHERE empresa_id = $1 AND tipo = 'evo_franqueada' AND unidade_id IS NOT NULL",
        empresa_id
    )
    config_map = {}
    for r in configs:
        c = r["config"]
        if isinstance(c, str):
            try: c = json.loads(c)
            except Exception: c = {}
        config_map[str(r["unidade_id"])] = {"config": c, "ativo": r["ativo"]}

    result = []
    for u in units:
        entry = config_map.get(str(u["id"]))
        result.append({
            "unidade_id": u["id"],
            "unidade_nome": u["nome"],
            "config": entry["config"] if entry else {"dns": "", "secret_key": ""},
            "ativo": entry["ativo"] if entry else False,
            "configurado": bool(entry and entry["config"].get("dns") and entry["config"].get("secret_key")),
        })
    return result


@router.put("/integrations/evo-franqueada/unit/{unidade_id}")
async def update_evo_franqueada_unit(
    unidade_id: int,
    body: IntegrationUpdate,
    token_payload: dict = Depends(get_current_user_token),
):
    """Salva a credencial 'evo_franqueada' de uma unidade.
    Esta cred so e usada pra GET /members?phone=X — nao roda sync, agendar, discovery."""
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")

    # Garantia multi-tenant: unidade tem que pertencer a esta empresa
    own = await _database.db_pool.fetchval(
        "SELECT 1 FROM unidades WHERE id = $1 AND empresa_id = $2",
        unidade_id, empresa_id
    )
    if not own:
        raise HTTPException(status_code=403, detail="Unidade não pertence a esta empresa")

    # Sanitiza config — guarda apenas dns + secret_key (escopo restrito)
    safe_config = {
        "dns": (body.config.get("dns") or "").strip(),
        "secret_key": (body.config.get("secret_key") or "").strip(),
        "api_url": body.config.get("api_url") or "https://evo-integracao-api.w12app.com.br/api/v2",
    }
    config_json = json.dumps(safe_config)

    existing = await _database.db_pool.fetchval(
        "SELECT id FROM integracoes WHERE empresa_id = $1 AND tipo = 'evo_franqueada' AND unidade_id = $2",
        empresa_id, unidade_id
    )
    if existing:
        await _database.db_pool.execute(
            "UPDATE integracoes SET config = $1::jsonb, ativo = $2, updated_at = NOW() WHERE id = $3",
            config_json, body.ativo, existing
        )
    else:
        await _database.db_pool.execute(
            "INSERT INTO integracoes (empresa_id, tipo, config, ativo, unidade_id, created_at) VALUES ($1, 'evo_franqueada', $2::jsonb, $3, $4, NOW())",
            empresa_id, config_json, body.ativo, unidade_id
        )

    # Invalida cache de membro consulta
    try:
        for k in await redis_client.keys(f"evo:membro:{empresa_id}:{unidade_id}:*"):
            await redis_client.delete(k)
    except Exception:
        pass

    return {"status": "success"}


@router.get("/evo/verificar-membro")
async def evo_verificar_membro_endpoint(
    telefone: str,
    unidade_id: int,
    token_payload: dict = Depends(get_current_user_token),
):
    """Endpoint de TESTE — chama verificar_membro_evo e retorna o dict.
    Use pra validar a cred franqueada antes de plugar no fluxo do bot.
    Ex: GET /management/evo/verificar-membro?telefone=11976804555&unidade_id=24"""
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")

    # Garantia multi-tenant
    own = await _database.db_pool.fetchval(
        "SELECT 1 FROM unidades WHERE id = $1 AND empresa_id = $2",
        unidade_id, empresa_id
    )
    if not own:
        raise HTTPException(status_code=403, detail="Unidade não pertence a esta empresa")

    from src.services.evo_client import verificar_membro_evo
    return await verificar_membro_evo(empresa_id, telefone, unidade_id)


# ────────── CHATWOOT LABELS — visualizacao das etiquetas ──────────

@router.get("/chatwoot/labels")
async def list_chatwoot_labels(token_payload: dict = Depends(get_current_user_token)):
    """Lista todas as labels (etiquetas) configuradas na conta Chatwoot da empresa.
    Retorna: [{title, description, color, show_on_sidebar}].
    NAO faz contagem de contatos por label aqui (caro) — a UI mostra so as labels."""
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")

    from src.services.db_queries import carregar_integracao
    integ = await carregar_integracao(empresa_id, 'chatwoot')
    if not integ:
        return {"labels": [], "erro": "Integração Chatwoot não configurada"}

    # Reaproveita o helper que extrai url+token
    from src.services.chatwoot_client import _chatwoot_url_token
    url_base, token = _chatwoot_url_token(integ)
    account_id = integ.get("account_id") or integ.get("accountId")
    if not url_base or not token or not account_id:
        return {"labels": [], "erro": "Configuração Chatwoot incompleta (url/token/account_id)"}

    import httpx
    headers = {"api_access_token": str(token)}
    url = f"{url_base}/api/v1/accounts/{account_id}/labels"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=10.0)
        if resp.status_code != 200:
            return {"labels": [], "erro": f"Chatwoot HTTP {resp.status_code}"}
        data = resp.json() or {}
        payload = data.get("payload") if isinstance(data, dict) else None
        if payload is None and isinstance(data.get("data"), dict):
            payload = data["data"].get("payload")
        labels = payload if isinstance(payload, list) else []
        # Normaliza: garante chaves esperadas
        norm = []
        for l in labels:
            if not isinstance(l, dict):
                continue
            norm.append({
                "id": l.get("id"),
                "title": l.get("title") or "",
                "description": l.get("description") or "",
                "color": l.get("color") or "#10b981",
                "show_on_sidebar": bool(l.get("show_on_sidebar", True)),
            })
        return {"labels": norm, "total": len(norm), "account_id": account_id}
    except Exception as e:
        logger.warning(f"[CW labels list] erro: {e}")
        return {"labels": [], "erro": f"{type(e).__name__}: {str(e)[:200]}"}


@router.get("/chatwoot/labels/{label_title}/contacts")
async def list_contacts_by_label(label_title: str, token_payload: dict = Depends(get_current_user_token)):
    """Lista contatos que tem uma label especifica.
    Usa o endpoint /api/v2/accounts/{id}/reports/agents_filter ou
    /api/v1/accounts/{id}/labels/{title}/contacts (Chatwoot 3.x)."""
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")

    from src.services.db_queries import carregar_integracao
    integ = await carregar_integracao(empresa_id, 'chatwoot')
    if not integ:
        return {"contacts": [], "erro": "Integração Chatwoot não configurada"}

    from src.services.chatwoot_client import _chatwoot_url_token
    url_base, token = _chatwoot_url_token(integ)
    account_id = integ.get("account_id") or integ.get("accountId")
    if not url_base or not token or not account_id:
        return {"contacts": [], "erro": "Configuração Chatwoot incompleta"}

    import httpx
    headers = {"api_access_token": str(token)}
    # Chatwoot v3 — endpoint oficial pra listar contatos por label
    url = f"{url_base}/api/v1/accounts/{account_id}/labels/{label_title}/contacts"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=15.0)
        if resp.status_code != 200:
            return {"contacts": [], "total": 0, "erro": f"HTTP {resp.status_code}"}
        data = resp.json() or {}
        # Chatwoot retorna {payload: [...], meta: {count: N}} ou {data: {payload, meta}}
        payload = data.get("payload") if isinstance(data, dict) else None
        meta = data.get("meta") if isinstance(data, dict) else None
        if payload is None and isinstance(data.get("data"), dict):
            payload = data["data"].get("payload")
            meta = data["data"].get("meta")
        contatos = payload if isinstance(payload, list) else []
        total = (meta or {}).get("count") if isinstance(meta, dict) else len(contatos)
        norm = []
        for c in contatos:
            if not isinstance(c, dict):
                continue
            norm.append({
                "id": c.get("id"),
                "name": c.get("name") or "",
                "phone_number": c.get("phone_number") or "",
                "email": c.get("email") or "",
                "thumbnail": c.get("thumbnail") or "",
            })
        return {"contacts": norm, "total": total or len(norm)}
    except Exception as e:
        logger.warning(f"[CW labels contacts] erro: {e}")
        return {"contacts": [], "erro": f"{type(e).__name__}: {str(e)[:200]}"}


@router.put("/integrations/{tipo}")
async def update_integration(
    tipo: str,
    body: IntegrationUpdate,
    token_payload: dict = Depends(get_current_user_token),
):
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")

    # Busca o registro global (sem unidade_id), preferindo NULL
    existing = await _database.db_pool.fetchval(
        "SELECT id FROM integracoes WHERE empresa_id = $1 AND tipo = $2 AND unidade_id IS NULL ORDER BY id DESC LIMIT 1",
        empresa_id, tipo
    )

    config_json = json.dumps(body.config)

    if existing:
        await _database.db_pool.execute(
            "UPDATE integracoes SET config = $1::jsonb, ativo = $2, updated_at = NOW() WHERE id = $3",
            config_json, body.ativo, existing
        )
    else:
        await _database.db_pool.execute(
            "INSERT INTO integracoes (empresa_id, tipo, config, ativo, created_at) VALUES ($1, $2, $3::jsonb, $4, NOW())",
            empresa_id, tipo, config_json, body.ativo
        )

    # [CACHE-01] Invalida TODAS as variantes da integracao (global + por unidade)
    await invalidate_integracao(empresa_id, tipo=tipo)
    # Tambem invalida o cache de mapeamento account_id -> empresa (se account_id mudou)
    _account_id = body.config.get("account_id")
    if _account_id:
        await redis_client.delete(f"map:account:{_account_id}")

    return {"status": "success"}


@router.post("/integrations/{tipo}/test")
async def test_integration_connection(
    tipo: str,
    token_payload: dict = Depends(get_current_user_token),
):
    """Testa a conexão com a integração configurada (Chatwoot ou UazAPI)."""
    import httpx

    perfil = token_payload.get("perfil", "")
    if perfil == "admin_master":
        raise HTTPException(status_code=403, detail="admin_master não gerencia integrações")

    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")

    row = await _database.db_pool.fetchrow(
        "SELECT config, ativo FROM integracoes WHERE empresa_id = $1 AND tipo = $2 AND unidade_id IS NULL ORDER BY id DESC LIMIT 1",
        empresa_id, tipo
    )
    if not row:
        return {"ok": False, "message": "Integração não configurada"}

    config = row["config"]
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except Exception:
            return {"ok": False, "message": "Configuração inválida"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if tipo == "chatwoot":
                url = (config.get("url") or config.get("base_url") or "").rstrip("/")
                token = config.get("access_token") or config.get("token") or ""
                if not url or not token:
                    return {"ok": False, "message": "URL ou token não configurados"}
                resp = await client.get(
                    f"{url}/api/v1/profile",
                    headers={"api_access_token": token}
                )
                if resp.status_code == 200:
                    return {"ok": True, "message": "Conexão com Chatwoot OK"}
                return {"ok": False, "message": f"Chatwoot retornou status {resp.status_code}"}

            elif tipo == "uazapi":
                api_url = (config.get("url") or config.get("api_url") or "").rstrip("/")
                token = config.get("token") or ""
                if not api_url or not token:
                    return {"ok": False, "message": "URL ou token não configurados"}
                resp = await client.get(
                    f"{api_url}/status",
                    headers={"token": token}
                )
                if resp.status_code == 200:
                    return {"ok": True, "message": "Conexão com UazAPI OK"}
                return {"ok": False, "message": f"UazAPI retornou status {resp.status_code}"}

            else:
                return {"ok": False, "message": f"Tipo '{tipo}' não suporta teste de conexão"}
    except httpx.ConnectError:
        return {"ok": False, "message": "Não foi possível conectar ao servidor"}
    except httpx.TimeoutException:
        return {"ok": False, "message": "Timeout — servidor não respondeu em 10s"}
    except Exception as e:
        return {"ok": False, "message": f"Erro: {str(e)[:100]}"}


# --- Logs Endpoints ---

@router.get("/logs")
async def get_logs(
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    token_payload: dict = Depends(get_current_user_token)
):
    empresa_id = token_payload.get("empresa_id")
    rows = await _database.db_pool.fetch(
        """SELECT conversation_id, contato_nome, contato_fone, score_lead, intencao_de_compra, status, updated_at, resumo_ia
           FROM conversas WHERE empresa_id = $1 ORDER BY updated_at DESC LIMIT $2 OFFSET $3""",
        empresa_id, limit, offset
    )
    return [dict(r) for r in rows]

@router.get("/export-leads")
async def export_leads(
    unidade_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Retorna todos os leads da empresa em formato JSON para exportação completa.
    """
    empresa_id = token_payload.get("empresa_id")
    
    conditions = ["c.empresa_id = $1"]
    params = [empresa_id]
    
    if unidade_id:
        params.append(unidade_id)
        conditions.append(f"c.unidade_id = ${len(params)}")
    if status:
        params.append(status)
        conditions.append(f"c.status = ${len(params)}")
        
    where = " AND ".join(conditions)
    
    rows = await _database.db_pool.fetch(f"""
        SELECT c.contato_nome, c.contato_fone, c.contato_telefone, c.score_lead, 
               c.lead_qualificado, c.intencao_de_compra, c.status, u.nome as unidade_nome,
               c.total_mensagens_cliente, c.total_mensagens_ia, c.created_at
        FROM conversas c
        LEFT JOIN unidades u ON u.id = c.unidade_id
        WHERE {where}
        ORDER BY c.created_at DESC
    """, *params)

    return [dict(r) for r in rows]


# --- EVO Sync Endpoint (from origin) ---

@router.post("/integrations/evo/sync/{unidade_id}")
async def sync_evo_unit(
    unidade_id: int,
    token_payload: dict = Depends(get_current_user_token)
) -> dict:
    """Força a sincronização de planos da EVO para esta unidade específica."""
    from src.services.db_queries import sincronizar_planos_evo
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    try:
        count = await sincronizar_planos_evo(empresa_id, unidade_id=unidade_id, bypass_cache=True)
        return {"status": "success", "count": count}
    except Exception as e:
        logger.error(f"Erro ao sincronizar EVO para unidade {unidade_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Follow-up Endpoints ---

@router.get("/followup/templates")
async def list_followup_templates(token_payload: dict = Depends(get_current_user_token)):
    perfil = token_payload.get("perfil", "")
    if perfil == "admin_master":
        raise HTTPException(status_code=403, detail="Acesso restrito")
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    import json as _json
    # Tenta primeiro com colunas CSAT (migration b2c3d4e5f6g7).
    # Se a migration ainda não rodou (colunas inexistentes), usa query sem elas.
    try:
        rows = await _database.db_pool.fetch("""
            SELECT t.id, t.nome, t.mensagem, t.delay_minutos, t.ordem, t.tipo, t.ativo,
                   t.unidade_id, u.nome AS unidade_nome,
                   t.filtro_rating_min, t.filtro_sentimentos_excluir, t.bloquear_cancelamento
            FROM templates_followup t
            LEFT JOIN unidades u ON u.id = t.unidade_id
            WHERE t.empresa_id = $1
            ORDER BY t.unidade_id NULLS LAST, t.ordem
        """, empresa_id)
    except Exception:
        # Colunas de filtro CSAT ainda não existem — usa query base sem elas
        rows = await _database.db_pool.fetch("""
            SELECT t.id, t.nome, t.mensagem, t.delay_minutos, t.ordem, t.tipo, t.ativo,
                   t.unidade_id, u.nome AS unidade_nome
            FROM templates_followup t
            LEFT JOIN unidades u ON u.id = t.unidade_id
            WHERE t.empresa_id = $1
            ORDER BY t.unidade_id NULLS LAST, t.ordem
        """, empresa_id)
    result = []
    for r in rows:
        d = dict(r)
        # Garante que colunas CSAT existam mesmo quando vieram do fallback
        d.setdefault("filtro_rating_min", 0)
        d.setdefault("bloquear_cancelamento", False)
        try:
            d["filtro_sentimentos_excluir"] = _json.loads(d.get("filtro_sentimentos_excluir") or "[]")
        except Exception:
            d["filtro_sentimentos_excluir"] = []
        result.append(d)
    return result


@router.post("/followup/templates")
async def create_followup_template(body: FollowupTemplateCreate, token_payload: dict = Depends(get_current_user_token)):
    perfil = token_payload.get("perfil", "")
    if perfil == "admin_master":
        raise HTTPException(status_code=403, detail="Acesso restrito")
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    import json as _json
    sentimentos_json = _json.dumps(body.filtro_sentimentos_excluir or [])
    try:
        row = await _database.db_pool.fetchrow("""
            INSERT INTO templates_followup
                (empresa_id, nome, mensagem, delay_minutos, ordem, tipo, ativo, unidade_id,
                 filtro_rating_min, filtro_sentimentos_excluir, bloquear_cancelamento)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING id
        """, empresa_id, body.nome, body.mensagem, body.delay_minutos, body.ordem, body.tipo, body.ativo, body.unidade_id,
             body.filtro_rating_min, sentimentos_json, body.bloquear_cancelamento)
    except Exception:
        # Colunas CSAT ainda não existem — insere sem elas
        row = await _database.db_pool.fetchrow("""
            INSERT INTO templates_followup
                (empresa_id, nome, mensagem, delay_minutos, ordem, tipo, ativo, unidade_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
        """, empresa_id, body.nome, body.mensagem, body.delay_minutos, body.ordem, body.tipo, body.ativo, body.unidade_id)
    return {"id": row["id"], "status": "created"}


@router.put("/followup/templates/{template_id}")
async def update_followup_template(
    template_id: int,
    body: FollowupTemplateUpdate,
    token_payload: dict = Depends(get_current_user_token),
):
    perfil = token_payload.get("perfil", "")
    if perfil == "admin_master":
        raise HTTPException(status_code=403, detail="Acesso restrito")
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    exists = await _database.db_pool.fetchval(
        "SELECT id FROM templates_followup WHERE id = $1 AND empresa_id = $2", template_id, empresa_id
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    import json as _json
    raw = body.model_dump(exclude_none=True)
    # Serializa lista de sentimentos para JSON texto
    if "filtro_sentimentos_excluir" in raw:
        raw["filtro_sentimentos_excluir"] = _json.dumps(raw["filtro_sentimentos_excluir"])
    if not raw:
        return {"status": "no_changes"}
    # Remove colunas CSAT se a migration ainda não rodou
    CSAT_COLS = {"filtro_rating_min", "filtro_sentimentos_excluir", "bloquear_cancelamento"}
    try:
        set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(raw))
        params = [template_id] + list(raw.values())
        await _database.db_pool.execute(
            f"UPDATE templates_followup SET {set_clause} WHERE id = $1", *params
        )
    except Exception:
        # Tenta novamente sem as colunas CSAT
        raw_safe = {k: v for k, v in raw.items() if k not in CSAT_COLS}
        if raw_safe:
            set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(raw_safe))
            params = [template_id] + list(raw_safe.values())
            await _database.db_pool.execute(
                f"UPDATE templates_followup SET {set_clause} WHERE id = $1", *params
            )
    return {"status": "updated"}


@router.delete("/followup/templates/{template_id}")
async def delete_followup_template(template_id: int, token_payload: dict = Depends(get_current_user_token)):
    perfil = token_payload.get("perfil", "")
    if perfil == "admin_master":
        raise HTTPException(status_code=403, detail="Acesso restrito")
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    exists = await _database.db_pool.fetchval(
        "SELECT id FROM templates_followup WHERE id = $1 AND empresa_id = $2", template_id, empresa_id
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    # [SEC] defense-in-depth: filtrar empresa_id na escrita evita
    # cross-tenant DELETE/UPDATE caso o SELECT tenha bug ou race.
    await _database.db_pool.execute(
        "UPDATE followups SET status = 'cancelado', updated_at = NOW() "
        "WHERE template_id = $1 AND empresa_id = $2 AND status = 'pendente'",
        template_id, empresa_id
    )
    await _database.db_pool.execute(
        "DELETE FROM templates_followup WHERE id = $1 AND empresa_id = $2",
        template_id, empresa_id
    )
    return {"status": "deleted"}


@router.get("/followup/history")
async def get_followup_history(
    status: Optional[str] = Query(None),
    unidade_id: Optional[int] = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    token_payload: dict = Depends(get_current_user_token),
):
    perfil = token_payload.get("perfil", "")
    if perfil == "admin_master":
        raise HTTPException(status_code=403, detail="Acesso restrito")
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    conditions = ["f.empresa_id = $1"]
    params: list = [empresa_id]
    if status:
        params.append(status)
        conditions.append(f"f.status = ${len(params)}")
    if unidade_id:
        params.append(unidade_id)
        conditions.append(f"f.unidade_id = ${len(params)}")
    where = " AND ".join(conditions)
    params += [limit, offset]
    rows = await _database.db_pool.fetch(f"""
        SELECT f.id, f.status, f.mensagem, f.agendado_para, f.enviado_em, f.erro_log, f.ordem,
               c.contato_nome, c.contato_fone, c.score_lead,
               u.nome AS unidade_nome,
               t.nome AS template_nome
        FROM followups f
        JOIN conversas c ON c.id = f.conversa_id
        LEFT JOIN unidades u ON u.id = f.unidade_id
        LEFT JOIN templates_followup t ON t.id = f.template_id
        WHERE {where}
        ORDER BY f.agendado_para DESC
        LIMIT ${len(params)-1} OFFSET ${len(params)}
    """, *params)
    return [dict(r) for r in rows]


@router.get("/followup/stats")
async def get_followup_stats(token_payload: dict = Depends(get_current_user_token)):
    perfil = token_payload.get("perfil", "")
    if perfil == "admin_master":
        raise HTTPException(status_code=403, detail="Acesso restrito")
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    row = await _database.db_pool.fetchrow("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'pendente')                                        AS pendentes,
            COUNT(*) FILTER (WHERE status = 'enviado' AND DATE(enviado_em) = CURRENT_DATE)     AS enviados_hoje,
            COUNT(*) FILTER (WHERE status = 'cancelado' AND DATE(updated_at) = CURRENT_DATE)   AS cancelados_hoje,
            COUNT(*) FILTER (WHERE status = 'erro')                                            AS erros
        FROM followups
        WHERE empresa_id = $1
    """, empresa_id)
    return dict(row)


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 5 — KNOWLEDGE BASE (RAG) + A/B TESTING
# ═══════════════════════════════════════════════════════════════════════════════

# ── Knowledge Base (RAG) ────────────────────────────────────────────

class KBDocumentCreate(BaseModel):
    titulo: str
    conteudo: str
    categoria: str = "geral"

@router.get("/knowledge-base")
async def listar_knowledge_base(
    categoria: Optional[str] = Query(None),
    token_payload: dict = Depends(get_current_user_token)
):
    """Lista documentos da base de conhecimento."""
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não identificada")
    from src.services.rag_service import listar_conhecimento
    return await listar_conhecimento(empresa_id, categoria)


@router.post("/knowledge-base", status_code=201)
async def criar_knowledge_base(
    body: KBDocumentCreate,
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Indexa um novo documento na base de conhecimento.
    O conteúdo é dividido em chunks e embeddings são gerados automaticamente.
    """
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não identificada")
    if not body.conteudo or len(body.conteudo.strip()) < 20:
        raise HTTPException(status_code=400, detail="Conteúdo muito curto (mín. 20 caracteres)")
    from src.services.rag_service import indexar_documento
    chunks = await indexar_documento(
        empresa_id=empresa_id,
        titulo=body.titulo,
        conteudo=body.conteudo,
        categoria=body.categoria
    )
    # [CACHE-01] Garante que RAG + FAQ sejam re-lidos (KB novo pode afetar respostas)
    await invalidate_kb(empresa_id)
    await invalidate_faq(empresa_id)
    return {"status": "success", "chunks_indexados": chunks, "titulo": body.titulo}


@router.delete("/knowledge-base/{kb_id}")
async def deletar_knowledge_base(
    kb_id: int,
    token_payload: dict = Depends(get_current_user_token)
):
    """Desativa um item da base de conhecimento."""
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não identificada")
    from src.services.rag_service import deletar_conhecimento
    ok = await deletar_conhecimento(empresa_id, kb_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Erro ao desativar documento")
    # [CACHE-01] Item removido — limpa cache RAG e FAQ
    await invalidate_kb(empresa_id)
    await invalidate_faq(empresa_id)
    return {"status": "success"}


@router.post("/knowledge-base/reindex")
async def reindexar_knowledge_base(
    token_payload: dict = Depends(get_current_user_token)
):
    """Regenera embeddings de documentos sem embedding."""
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não identificada")
    from src.services.rag_service import reindexar_embeddings
    updated = await reindexar_embeddings(empresa_id)
    return {"status": "success", "embeddings_atualizados": updated}


@router.post("/knowledge-base/search")
async def buscar_knowledge_base(
    query: str = Query(..., min_length=5),
    top_k: int = Query(3, le=10),
    categoria: Optional[str] = Query(None),
    token_payload: dict = Depends(get_current_user_token)
):
    """Busca semântica na base de conhecimento (para teste/debug)."""
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não identificada")
    from src.services.rag_service import buscar_conhecimento
    resultados = await buscar_conhecimento(query, empresa_id, top_k=top_k, categoria=categoria)
    return {"query": query, "resultados": resultados, "total": len(resultados)}


# ── A/B Testing ─────────────────────────────────────────────────────

class ABTesteCreate(BaseModel):
    nome: str
    campo_teste: str = "prompt_sistema"  # prompt_sistema, tom_de_voz, instrucoes_extra
    variante_a: str
    variante_b: str
    percentual_b: float = 50.0
    descricao: Optional[str] = None


@router.get("/ab-tests")
async def listar_ab_tests(
    token_payload: dict = Depends(get_current_user_token)
):
    """Lista todos os testes A/B da empresa."""
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não identificada")
    from src.services.ab_testing import listar_testes
    return await listar_testes(empresa_id)


@router.post("/ab-tests", status_code=201)
async def criar_ab_test(
    body: ABTesteCreate,
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Cria um novo teste A/B. Desativa qualquer teste ativo anterior.
    campo_teste: prompt_sistema, tom_de_voz, instrucoes_extra
    """
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não identificada")
    if body.campo_teste not in ("prompt_sistema", "tom_de_voz", "instrucoes_extra"):
        raise HTTPException(status_code=400, detail="campo_teste deve ser: prompt_sistema, tom_de_voz ou instrucoes_extra")
    from src.services.ab_testing import criar_teste
    teste_id = await criar_teste(
        empresa_id=empresa_id,
        nome=body.nome,
        campo_teste=body.campo_teste,
        variante_a=body.variante_a,
        variante_b=body.variante_b,
        percentual_b=body.percentual_b,
        descricao=body.descricao
    )
    if not teste_id:
        raise HTTPException(status_code=500, detail="Erro ao criar teste A/B")
    return {"status": "success", "teste_id": teste_id}


@router.get("/ab-tests/{teste_id}/results")
async def resultados_ab_test(
    teste_id: int,
    token_payload: dict = Depends(get_current_user_token)
):
    """Retorna resultados comparativos do teste A/B."""
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não identificada")
    from src.services.ab_testing import obter_resultados_ab
    return await obter_resultados_ab(teste_id)


@router.post("/ab-tests/{teste_id}/finalize")
async def finalizar_ab_test(
    teste_id: int,
    token_payload: dict = Depends(get_current_user_token)
):
    """Finaliza um teste A/B ativo."""
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não identificada")
    from src.services.ab_testing import finalizar_teste
    ok = await finalizar_teste(empresa_id, teste_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Erro ao finalizar teste")
    return {"status": "success", "message": "Teste A/B finalizado"}


# ─────────────────────────────────────────────────────────────────────────────
# PLANOS
# ─────────────────────────────────────────────────────────────────────────────

class PlanoCreate(BaseModel):
    nome: str
    valor: Optional[float] = None
    valor_promocional: Optional[float] = None
    meses_promocionais: Optional[int] = None
    descricao: Optional[str] = None
    diferenciais: Optional[str] = None  # texto livre separado por vírgula
    link_venda: Optional[str] = None
    unidade_id: Optional[int] = None
    ativo: bool = True
    ordem: int = 0


@router.get("/planos")
async def list_planos(token_payload: dict = Depends(get_current_user_token)):
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada ao usuário")
    try:
        rows = await _database.db_pool.fetch(
            """
            SELECT p.id, p.nome, p.valor, p.valor_promocional, p.meses_promocionais,
                   p.descricao, p.diferenciais, p.link_venda, p.unidade_id,
                   p.ativo, p.ordem, p.id_externo,
                   u.nome AS unidade_nome
            FROM planos p
            LEFT JOIN unidades u ON u.id = p.unidade_id
            WHERE p.empresa_id = $1
            ORDER BY p.ordem, p.nome
            LIMIT 500
            """,
            empresa_id
        )
    except Exception as e:
        logger.error(f"Erro ao listar planos para empresa {empresa_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro ao carregar planos.")
    return [dict(r) for r in rows]



def _diferenciais_para_array(valor):
    """[INTERNO] Converte 'diferenciais' em list[str] (pra envio quando coluna for TEXT[])."""
    if valor is None:
        return None
    if isinstance(valor, list):
        return [str(v).strip() for v in valor if str(v).strip()]
    if isinstance(valor, str):
        return [v.strip() for v in valor.split(",") if v.strip()]
    return [str(valor)]


_DIFER_COLTYPE_CACHE = {"tipo": None}


async def _diferenciais_coltype():
    """Detecta uma vez se a coluna planos.diferenciais é TEXT ou TEXT[].
    Cache em memoria pra nao consultar information_schema toda chamada."""
    if _DIFER_COLTYPE_CACHE["tipo"] is not None:
        return _DIFER_COLTYPE_CACHE["tipo"]
    try:
        row = await _database.db_pool.fetchrow(
            """SELECT data_type, udt_name FROM information_schema.columns
               WHERE table_name = 'planos' AND column_name = 'diferenciais'"""
        )
        if row:
            # data_type='ARRAY' ou udt_name='_text' indicam TEXT[]
            tipo = "array" if (row["data_type"] == "ARRAY" or str(row["udt_name"]).startswith("_")) else "text"
        else:
            tipo = "text"
    except Exception:
        tipo = "text"
    _DIFER_COLTYPE_CACHE["tipo"] = tipo
    logger.info(f"[planos.diferenciais] coluna detectada como tipo='{tipo}'")
    return tipo


async def _diferenciais_para_coluna(valor):
    """Retorna o valor no formato certo conforme a coluna seja TEXT (str) ou TEXT[] (list)."""
    arr = _diferenciais_para_array(valor)
    if arr is None:
        return None
    tipo = await _diferenciais_coltype()
    if tipo == "array":
        return arr
    # TEXT — junta com virgula
    return ", ".join(arr) if arr else None


@router.post("/planos", status_code=201)
async def create_plano(body: PlanoCreate, token_payload: dict = Depends(get_current_user_token)):
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada ao usuário")

    # Validacao multi-tenant: se passou unidade_id, ela tem que ser desta empresa
    if body.unidade_id is not None:
        own = await _database.db_pool.fetchval(
            "SELECT 1 FROM unidades WHERE id = $1 AND empresa_id = $2",
            body.unidade_id, empresa_id
        )
        if not own:
            raise HTTPException(status_code=400, detail=f"Unidade {body.unidade_id} não pertence a esta empresa")

    diferenciais_val = await _diferenciais_para_coluna(body.diferenciais)
    try:
        await _database.db_pool.execute(
            """
            INSERT INTO planos
                (empresa_id, unidade_id, nome, valor, valor_promocional, meses_promocionais,
                 descricao, diferenciais, link_venda, ativo, ordem, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW(), NOW())
            """,
            empresa_id, body.unidade_id, body.nome, body.valor, body.valor_promocional,
            body.meses_promocionais, body.descricao,
            diferenciais_val,
            body.link_venda, body.ativo, body.ordem
        )
    except asyncpg.UniqueViolationError as e:
        logger.warning(f"Plano duplicado empresa={empresa_id}: {e}")
        raise HTTPException(status_code=409, detail=f"Já existe um plano com esses dados ({e}).")
    except asyncpg.PostgresError as e:
        logger.error(f"Erro PG ao criar plano empresa={empresa_id}: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro PG: {type(e).__name__}: {str(e)[:200]}")
    except Exception as e:
        logger.error(f"Erro ao criar plano para empresa {empresa_id}: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)[:200]}")
    # [CACHE-01] Invalida cache de planos (proxima consulta vai re-ler do banco)
    await invalidate_planos(empresa_id)
    return {"status": "success"}


@router.put("/planos/{plano_id}")
async def update_plano(plano_id: int, body: PlanoCreate, token_payload: dict = Depends(get_current_user_token)):
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada ao usuário")

    if body.unidade_id is not None:
        own = await _database.db_pool.fetchval(
            "SELECT 1 FROM unidades WHERE id = $1 AND empresa_id = $2",
            body.unidade_id, empresa_id
        )
        if not own:
            raise HTTPException(status_code=400, detail=f"Unidade {body.unidade_id} não pertence a esta empresa")

    diferenciais_val = await _diferenciais_para_coluna(body.diferenciais)
    try:
        result = await _database.db_pool.execute(
            """
            UPDATE planos
            SET nome=$1, valor=$2, valor_promocional=$3, meses_promocionais=$4,
                descricao=$5, diferenciais=$6, link_venda=$7, unidade_id=$8,
                ativo=$9, ordem=$10, updated_at=NOW()
            WHERE id=$11 AND empresa_id=$12
            """,
            body.nome, body.valor, body.valor_promocional, body.meses_promocionais,
            body.descricao, diferenciais_val, body.link_venda, body.unidade_id,
            body.ativo, body.ordem, plano_id, empresa_id
        )
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Plano não encontrado")
    except HTTPException:
        raise
    except asyncpg.PostgresError as e:
        logger.error(f"Erro PG ao atualizar plano {plano_id}: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro PG: {type(e).__name__}: {str(e)[:200]}")
    except Exception as e:
        logger.error(f"Erro ao atualizar plano {plano_id}: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)[:200]}")
    # [CACHE-01] Invalida cache de planos (proxima consulta vai re-ler do banco)
    await invalidate_planos(empresa_id)
    return {"status": "success"}


@router.delete("/planos/{plano_id}")
async def delete_plano(plano_id: int, token_payload: dict = Depends(get_current_user_token)):
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada ao usuário")
    # Pega unidade_id antes de deletar para invalidar cache correto
    row = await _database.db_pool.fetchrow(
        "SELECT unidade_id FROM planos WHERE id=$1 AND empresa_id=$2", plano_id, empresa_id
    )
    await _database.db_pool.execute(
        "DELETE FROM planos WHERE id=$1 AND empresa_id=$2", plano_id, empresa_id
    )
    # [CACHE-01] Plano deletado — invalida cache
    await invalidate_planos(empresa_id)
    return {"status": "success"}


@router.post("/planos/sync")
async def sync_planos(token_payload: dict = Depends(get_current_user_token)):
    """Sincroniza planos do Evo API para o banco de dados."""
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada ao usuário")
    from src.services.db_queries import sincronizar_planos_evo
    count = await sincronizar_planos_evo(empresa_id, bypass_cache=True)
    # [CACHE-01] Apos sync — invalida todos os caches de planos da empresa
    await invalidate_planos(empresa_id)
    return {"status": "success", "sincronizados": count}


# ─── Chatwoot Teams ────────────────────────────────────────────────────────────

@router.get("/chatwoot/teams")
async def get_chatwoot_teams(token_payload: dict = Depends(get_current_user_token)):
    """
    Retorna a lista de times do Chatwoot para a empresa.
    Usado pelo nó 'Transferir para Time' no editor de fluxo.
    """
    import httpx as _httpx

    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")

    from src.services.db_queries import carregar_integracao as _carregar_integracao
    integracao = await _carregar_integracao(empresa_id, "chatwoot")
    if not integracao:
        raise HTTPException(status_code=404, detail="Integração Chatwoot não configurada")

    url_base = integracao.get("url") or integracao.get("base_url") or ""
    account_id = integracao.get("account_id") or integracao.get("accountId")

    # Extrai token — mesma lógica de extrair_token_chatwoot() de main.py
    _raw_token = integracao.get("token")
    if isinstance(_raw_token, dict):
        token = (
            _raw_token.get("api_access_token")
            or _raw_token.get("api_token")
            or _raw_token.get("access_token")
            or _raw_token.get("token")
            or ""
        )
    elif _raw_token:
        token = str(_raw_token).strip()
    else:
        token = (
            integracao.get("api_access_token")
            or integracao.get("api_token")
            or integracao.get("access_token")
            or ""
        )

    if not url_base or not token or not account_id:
        raise HTTPException(
            status_code=422,
            detail=f"Configuração Chatwoot incompleta — url={bool(url_base)} token={bool(token)} account_id={bool(account_id)}"
        )

    try:
        async with _httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{url_base.rstrip('/')}/api/v1/accounts/{account_id}/teams",
                headers={"api_access_token": str(token)},
            )
            r.raise_for_status()
            teams = r.json()
            # Normaliza para [{id, name}]
            if isinstance(teams, list):
                return [{"id": t.get("id"), "name": t.get("name", "")} for t in teams]
            # Chatwoot às vezes envolve em {"payload": [...]}
            payload = teams.get("payload") or teams.get("teams") or []
            return [{"id": t.get("id"), "name": t.get("name", "")} for t in payload]
    except _httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Chatwoot retornou {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar times: {e}")



# ════════════════════════════════════════════════════════════════════════════
# AGENDAMENTO DE AULA EXPERIMENTAL — Fase 1
# ════════════════════════════════════════════════════════════════════════════

class AgendarExperimentalRequest(BaseModel):
    unidade_id: Optional[int] = None
    nome: str
    sobrenome: Optional[str] = ""
    telefone: str
    email: Optional[str] = None
    id_activity_session: int
    id_activity: int
    activity_name: str
    activity_date: str  # yyyy-MM-dd HH:mm
    service_name: Optional[str] = "Aula Experimental"
    id_service: Optional[int] = None


@router.get("/agendamento/discovery")
async def agendamento_discovery(
    unidade_id: Optional[int] = None,
    token_payload: dict = Depends(get_current_user_token),
):
    """Descobre branches, services e activities da EVO para popular dropdowns."""
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa nao vinculada")
    try:
        import asyncio as _aio
        branches, services, activities = await _aio.gather(
            listar_branches_evo(empresa_id, unidade_id),
            listar_services_evo(empresa_id, unidade_id),
            listar_activities_evo(empresa_id, unidade_id),
        )
        return {
            "branches": branches, "services": services, "activities": activities,
            "ok": bool(branches or services or activities),
        }
    except Exception as e:
        logger.error(f"discovery EVO erro: {e}")
        return {"branches": [], "services": [], "activities": [], "ok": False, "error": str(e)[:200]}


@router.get("/agendamento/horarios")
async def agendamento_horarios(
    unidade_id: Optional[int] = None,
    dias: int = Query(5, ge=1, le=14),
    id_branch: Optional[int] = None,
    id_activities: Optional[str] = None,
    token_payload: dict = Depends(get_current_user_token),
):
    """Lista sessoes disponiveis pra agendamento (proximos N dias)."""
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa nao vinculada")
    filtro = None
    if id_activities:
        try:
            filtro = [int(x.strip()) for x in id_activities.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="id_activities deve ser CSV de inteiros")
    try:
        horarios = await listar_horarios_disponiveis_evo(
            empresa_id, unidade_id, dias_a_frente=dias,
            id_branch=id_branch, filtro_id_activities=filtro,
        )
        return {"total": len(horarios), "horarios": horarios}
    except Exception as e:
        logger.error(f"horarios EVO erro: {e}")
        raise HTTPException(status_code=502, detail=f"Erro ao consultar horarios: {e}")


@router.post("/agendamento/experimental")
async def agendamento_experimental(
    body: AgendarExperimentalRequest,
    token_payload: dict = Depends(get_current_user_token),
):
    """Cria prospect (se nao existe) e agenda aula experimental."""
    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa nao vinculada")
    lead_data = {
        "name": f"{body.nome} {body.sobrenome or ''}".strip(),
        "email": body.email,
        "cellphone": body.telefone,
        "notes": "Agendamento experimental via dashboard",
    }
    id_prospect = await criar_prospect_evo(empresa_id, body.unidade_id, lead_data)
    if not id_prospect or id_prospect is True:
        return {"ok": False, "etapa": "criar_prospect", "mensagens": ["Falha criar prospect na EVO"]}
    res = await agendar_aula_experimental_evo(
        empresa_id=empresa_id, unidade_id=body.unidade_id,
        id_prospect=int(id_prospect), activity_date=body.activity_date,
        activity_name=body.activity_name, service_name=body.service_name or "Aula Experimental",
        id_activity=body.id_activity, id_service=body.id_service,
    )
    return {
        "ok": res.get("ok", False), "etapa": "agendar",
        "id_prospect": id_prospect, "id_activity_session": body.id_activity_session,
        "status": res.get("status"), "mensagens": res.get("mensagens", []),
        "data": res.get("data"),
    }
