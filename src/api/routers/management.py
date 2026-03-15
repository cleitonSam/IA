from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import src.core.database as _database
from src.core.security import get_current_user_token
from src.core.config import logger
import json

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
        "SELECT id, nome_ia, personalidade, instrucoes_base, tom_voz, model_name, temperature, max_tokens, ativo FROM personalidade_ia WHERE empresa_id = $1 LIMIT 1",
        empresa_id
    )
    if not row:
        # Retorna um objeto vazio mas estruturado se não existir
        return {
            "nome_ia": "", 
            "personalidade": "", 
            "instrucoes_base": "", 
            "tom_voz": "Profissional", 
            "model_name": "openai/gpt-4o",
            "temperature": 0.7,
            "max_tokens": 1000,
            "ativo": False
        }
    return dict(row)

@router.put("/personality")
async def update_personality(body: PersonalityUpdate, token_payload: dict = Depends(get_current_user_token)):
    empresa_id = token_payload.get("empresa_id")
    
    # Verifica se já existe
    existing = await _database.db_pool.fetchval("SELECT id FROM personalidade_ia WHERE empresa_id = $1", empresa_id)
    
    update_data = body.dict(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="Sem dados para atualizar")

    if existing:
        set_clause = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(update_data))
        values = list(update_data.values()) + [empresa_id]
        await _database.db_pool.execute(
            f"UPDATE personalidade_ia SET {set_clause}, updated_at = NOW() WHERE empresa_id = ${len(values)}",
            *values
        )
    else:
        columns = ["empresa_id", "created_at"] + list(update_data.keys())
        placeholders = [f"${i+1}" for i in range(len(columns))]
        values = [empresa_id, datetime.now()] + list(update_data.values())
        await _database.db_pool.execute(
            f"INSERT INTO personalidade_ia ({', '.join(columns)}) VALUES ({', '.join(placeholders)})",
            *values
        )
    
    return {"status": "success", "message": "Personalidade atualizada"}

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

# --- Integrations Endpoints ---

@router.get("/integrations")
async def get_integrations(token_payload: dict = Depends(get_current_user_token)):
    empresa_id = token_payload.get("empresa_id")
    rows = await _database.db_pool.fetch(
        "SELECT id, tipo, config, ativo FROM integracoes WHERE empresa_id = $1",
        empresa_id
    )
    return [dict(r) for r in rows]

@router.put("/integrations/{tipo}")
async def update_integration(tipo: str, body: IntegrationUpdate, token_payload: dict = Depends(get_current_user_token)):
    empresa_id = token_payload.get("empresa_id")
    
    existing = await _database.db_pool.fetchval(
        "SELECT id FROM integracoes WHERE empresa_id = $1 AND tipo = $2",
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
