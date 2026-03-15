from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import src.core.database as _database
from src.core.security import get_current_user_token
from src.core.config import logger
import json
import asyncio

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

class PersonalityCreate(BaseModel):
    nome_ia: str
    personalidade: str = ""
    instrucoes_base: str = ""
    tom_voz: str = "Profissional"
    model_name: str = "openai/gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 1000
    ativo: bool = False

class FAQCreate(BaseModel):
    pergunta: str
    resposta: str
    unidade_id: Optional[int] = None
    todas_unidades: bool = False
    prioridade: int = 0

class IntegrationUpdate(BaseModel):
    config: Dict[str, Any]
    ativo: bool = True

# --- Personality Endpoints ---

@router.get("/personality")
async def get_personality(token_payload: dict = Depends(get_current_user_token)):
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    
    row = await _database.db_pool.fetchrow(
        "SELECT id, nome_ia, personalidade, instrucoes_base, tom_voz, modelo_preferido as model_name, temperatura as temperature, max_tokens, ativo FROM personalidade_ia WHERE empresa_id = $1 LIMIT 1",
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
            "ativo": False
        }
    return dict(row)

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

    return {"status": "success", "message": "Personalidade atualizada"}


# --- Personality CRUD (multi-personality por empresa) ---

@router.get("/personalities")
async def list_personalities(token_payload: dict = Depends(get_current_user_token)):
    """Lista todas as personalidades da empresa."""
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    rows = await _database.db_pool.fetch(
        """SELECT id, nome_ia, personalidade, instrucoes_base, tom_voz,
                  modelo_preferido AS model_name, temperatura AS temperature,
                  max_tokens, ativo
           FROM personalidade_ia
           WHERE empresa_id = $1
           ORDER BY ativo DESC, id DESC""",
        empresa_id
    )
    return [dict(r) for r in rows]


@router.post("/personalities", status_code=201)
async def create_personality(
    data: PersonalityCreate,
    token_payload: dict = Depends(get_current_user_token)
):
    """Cria uma nova personalidade para a empresa."""
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    try:
        row = await _database.db_pool.fetchrow(
            """INSERT INTO personalidade_ia
               (empresa_id, nome_ia, personalidade, instrucoes_base, tom_voz,
                modelo_preferido, temperatura, max_tokens, ativo, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW(),NOW())
               RETURNING id""",
            empresa_id, data.nome_ia, data.personalidade, data.instrucoes_base,
            data.tom_voz, data.model_name, data.temperature, data.max_tokens, data.ativo
        )
        return {"id": row["id"], "status": "success"}
    except Exception as e:
        logger.error(f"Erro ao criar personalidade: {e}")
        raise HTTPException(status_code=500, detail="Erro ao criar personalidade")


@router.put("/personalities/{pid}")
async def update_personality_by_id(
    pid: int,
    data: PersonalityCreate,
    token_payload: dict = Depends(get_current_user_token)
):
    """Atualiza uma personalidade pelo ID."""
    empresa_id = token_payload.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="Empresa não vinculada")
    existing = await _database.db_pool.fetchval(
        "SELECT id FROM personalidade_ia WHERE id = $1 AND empresa_id = $2", pid, empresa_id
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Personalidade não encontrada")
    await _database.db_pool.execute(
        """UPDATE personalidade_ia
           SET nome_ia=$1, personalidade=$2, instrucoes_base=$3, tom_voz=$4,
               modelo_preferido=$5, temperatura=$6, max_tokens=$7, ativo=$8, updated_at=NOW()
           WHERE id=$9 AND empresa_id=$10""",
        data.nome_ia, data.personalidade, data.instrucoes_base, data.tom_voz,
        data.model_name, data.temperature, data.max_tokens, data.ativo,
        pid, empresa_id
    )
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
    return {"status": "success"}


class PlaygroundMessage(BaseModel):
    role: str   # "user" | "assistant"
    content: str

class PlaygroundRequest(BaseModel):
    model_name: str = "openai/gpt-4o"
    instrucoes_base: str = ""
    personalidade: str = ""
    tom_voz: str = "Profissional"
    temperature: float = 0.7
    max_tokens: int = 1000
    messages: List[PlaygroundMessage] = []


@router.post("/personalities/playground")
async def personality_playground(
    body: PlaygroundRequest,
    token_payload: dict = Depends(get_current_user_token)
):
    """
    Executa uma mensagem real no LLM com a configuração de personalidade fornecida.
    Usado pelo Playground no painel de Personalidade IA.
    """
    from src.services.llm_service import cliente_ia

    if not cliente_ia:
        raise HTTPException(status_code=503, detail="Serviço de IA não configurado (OPENROUTER_API_KEY ausente)")

    # Monta system prompt combinando personalidade + instruções + tom
    partes = []
    if body.personalidade:
        partes.append(f"Objetivo: {body.personalidade}")
    if body.instrucoes_base:
        partes.append(body.instrucoes_base)
    if body.tom_voz:
        partes.append(f"Tom de voz: {body.tom_voz}.")
    system_prompt = "\n\n".join(partes) if partes else "Você é um assistente prestativo."

    # Monta histórico de mensagens
    msgs = [{"role": "system", "content": system_prompt}]
    for m in body.messages:
        if m.role in ("user", "assistant"):
            msgs.append({"role": m.role, "content": m.content})

    try:
        response = await asyncio.wait_for(
            cliente_ia.chat.completions.create(
                model=body.model_name,
                messages=msgs,
                temperature=body.temperature,
                max_tokens=min(body.max_tokens, 500),  # limita resposta no playground
            ),
            timeout=30
        )
        reply = response.choices[0].message.content or ""
        return {"reply": reply, "model": body.model_name}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="IA demorou demais para responder. Tente novamente.")
    except Exception as e:
        logger.error(f"Playground LLM error: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao chamar a IA: {str(e)[:200]}")


# --- FAQ Endpoints ---

@router.get("/faq")
async def list_faq(token_payload: dict = Depends(get_current_user_token)):
    empresa_id = token_payload.get("empresa_id")
    rows = await _database.db_pool.fetch(
        "SELECT id, pergunta, resposta, unidade_id, todas_unidades, prioridade, ativo FROM faq WHERE empresa_id = $1 ORDER BY prioridade DESC, id DESC",
        empresa_id
    )
    return [dict(r) for r in rows]

@router.post("/faq")
async def create_faq(body: FAQCreate, token_payload: dict = Depends(get_current_user_token)):
    empresa_id = token_payload.get("empresa_id")
    await _database.db_pool.execute(
        """INSERT INTO faq (empresa_id, pergunta, resposta, unidade_id, todas_unidades, prioridade, ativo, created_at)
           VALUES ($1, $2, $3, $4, $5, $6, true, NOW())""",
        empresa_id, body.pergunta, body.resposta, body.unidade_id, body.todas_unidades, body.prioridade
    )
    return {"status": "success"}

@router.put("/faq/{faq_id}")
async def update_faq(faq_id: int, body: FAQCreate, token_payload: dict = Depends(get_current_user_token)):
    empresa_id = token_payload.get("empresa_id")
    await _database.db_pool.execute(
        """UPDATE faq SET pergunta=$1, resposta=$2, unidade_id=$3, todas_unidades=$4, prioridade=$5, updated_at=NOW()
           WHERE id=$6 AND empresa_id=$7""",
        body.pergunta, body.resposta, body.unidade_id, body.todas_unidades, body.prioridade, faq_id, empresa_id
    )
    return {"status": "success"}

@router.delete("/faq/{faq_id}")
async def delete_faq(faq_id: int, token_payload: dict = Depends(get_current_user_token)):
    empresa_id = token_payload.get("empresa_id")
    await _database.db_pool.execute("DELETE FROM faq WHERE id=$1 AND empresa_id=$2", faq_id, empresa_id)
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

async def _resolve_empresa_id(token_payload: dict) -> Optional[int]:
    """Resolve empresa_id do JWT; se nulo, busca no banco pelo email do usuário."""
    empresa_id = token_payload.get("empresa_id")
    if empresa_id:
        return int(empresa_id)
    email = token_payload.get("sub")
    if email:
        empresa_id = await _database.db_pool.fetchval(
            "SELECT empresa_id FROM usuarios WHERE email = $1 AND ativo = true", email
        )
        if empresa_id:
            return int(empresa_id)
    return None


@router.get("/integrations")
async def get_integrations(token_payload: dict = Depends(get_current_user_token)):
    perfil = token_payload.get("perfil", "")

    # admin_master não gerencia integrações de empresa específica
    if perfil == "admin_master":
        return []

    empresa_id = await _resolve_empresa_id(token_payload)
    if not empresa_id:
        return []

    # Retorna a melhor config por tipo (prefere unidade_id NULL, mas aceita qualquer).
    # EVO é excluído — gerenciado pelo endpoint /evo/units.
    rows = await _database.db_pool.fetch(
        """
        SELECT DISTINCT ON (tipo) id, tipo, config, ativo
        FROM integracoes
        WHERE empresa_id = $1 AND tipo != 'evo'
        ORDER BY tipo, (unidade_id IS NULL) DESC, id DESC
        """,
        empresa_id
    )
    return [dict(r) for r in rows]


@router.get("/integrations/evo/units")
async def get_evo_per_unit(token_payload: dict = Depends(get_current_user_token)):
    """Retorna a configuração EVO para cada unidade ativa da empresa."""
    perfil = token_payload.get("perfil", "")

    if perfil == "admin_master":
        return []  # admin_master não gerencia integrações de empresa

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
    perfil = token_payload.get("perfil", "")
    if perfil == "admin_master":
        raise HTTPException(status_code=403, detail="admin_master não gerencia integrações de empresa")

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
            "UPDATE integracoes SET config = $1, ativo = $2, updated_at = NOW() WHERE id = $3",
            config_json, body.ativo, existing
        )
    else:
        await _database.db_pool.execute(
            "INSERT INTO integracoes (empresa_id, tipo, config, ativo, unidade_id, created_at) VALUES ($1, 'evo', $2, $3, $4, NOW())",
            empresa_id, config_json, body.ativo, unidade_id
        )
    return {"status": "success"}


@router.put("/integrations/{tipo}")
async def update_integration(
    tipo: str,
    body: IntegrationUpdate,
    token_payload: dict = Depends(get_current_user_token),
):
    perfil = token_payload.get("perfil", "")
    if perfil == "admin_master":
        raise HTTPException(status_code=403, detail="admin_master não gerencia integrações de empresa")

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
            "UPDATE integracoes SET config = $1, ativo = $2, updated_at = NOW() WHERE id = $3",
            config_json, body.ativo, existing
        )
    else:
        await _database.db_pool.execute(
            "INSERT INTO integracoes (empresa_id, tipo, config, ativo, created_at) VALUES ($1, $2, $3, $4, NOW())",
            empresa_id, tipo, config_json, body.ativo
        )
    return {"status": "success"}

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
