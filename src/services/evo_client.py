import base64
import httpx
import json
from typing import Optional, List, Dict, Any
from src.core.config import logger
from src.services.db_queries import carregar_integracao

async def _get_evo_headers(integracao: Dict[str, Any]) -> Dict[str, str]:
    dns = integracao.get('dns')
    secret_key = integracao.get('secret_key')
    if not dns or not secret_key:
        return {}
    
    auth = base64.b64encode(f"{dns}:{secret_key}".encode()).decode()
    return {
        'Authorization': f'Basic {auth}',
        'accept': 'application/json',
        'Content-Type': 'application/json'
    }

async def verificar_status_membro_evo(phone: str, empresa_id: int, unidade_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Verifica se o telefone pertence a um membro (aluno) na EVO.
    Tenta priorizar a integração da unidade específica.
    """
    integracao = await carregar_integracao(empresa_id, 'evo', unidade_id=unidade_id)
    if not integracao:
        logger.debug(f"ℹ️ Sem integração EVO para Empresa {empresa_id} (Unid {unidade_id})")
        return {"status": "desconhecido", "is_aluno": False}

    api_base = integracao.get('api_url', 'https://evo-integracao-api.w12app.com.br/api/v2')
    url = f"{api_base.replace('/v2', '/v1')}/members/basic?phone={phone}"
    
    headers = await _get_evo_headers(integracao)
    if not headers:
        return {"status": "erro_config", "is_aluno": False}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    aluno = data[0]
                    logger.info(f"✅ Aluno identificado na EVO: {aluno.get('firstName')} (Unid {unidade_id})")
                    return {
                        "is_aluno": True,
                        "nome": f"{aluno.get('firstName', '')} {aluno.get('lastName', '')}".strip(),
                        "status": aluno.get("membershipStatus") or aluno.get("status", "Ativo"),
                        "id_member": aluno.get("idMember")
                    }
        return {"is_aluno": False, "status": "lead"}
    except Exception as e:
        logger.error(f"Erro ao verificar membro na EVO (Unid {unidade_id}): {e}")
        return {"is_aluno": False, "status": "erro"}

async def criar_prospect_evo(empresa_id: int, unidade_id: Optional[int], lead_data: Dict[str, Any]) -> bool:
    """
    Cria um Prospect (Oportunidade) na EVO garantindo o isolamento da unidade.
    """
    integracao = await carregar_integracao(empresa_id, 'evo', unidade_id=unidade_id)
    if not integracao:
        logger.warning(f"⚠️ Não foi possível criar prospect: Integração EVO não encontrada para Empresa {empresa_id} (Unid {unidade_id})")
        return False

    id_branch = integracao.get('idBranch') or lead_data.get('idBranch')
    if not id_branch:
        logger.error(f"❌ Erro de Isolamento: Tentativa de criar prospect sem idBranch definido na Empresa {empresa_id} (Unid {unidade_id})")
        return False

    api_base = integracao.get('api_url', 'https://evo-integracao-api.w12app.com.br/api/v2')
    url = f"{api_base.replace('/v2', '/v1')}/prospects"
    
    headers = await _get_evo_headers(integracao)
    # Revertido para application/json (confirmado funcional via curl manual)
    headers['Content-Type'] = 'application/json'
    headers['accept'] = 'application/json'
    
    phone = lead_data.get('cellphone', '').replace('+', '').replace(' ', '')
    # Lógica simples de DDI para BR
    if len(phone) >= 10:
        ddi = '55'
        number = phone[-11:] if phone.startswith('55') else phone
    else:
        ddi = '55'
        number = phone

    full_name = lead_data.get('name', 'Lead WhatsApp').strip()
    name_parts = full_name.split(' ', 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else first_name

    # E-mail é OBRIGATÓRIO na EVO v1 Prospects (não aceita vazio/nulo).
    # Se não houver, geramos um placeholder baseado no telefone para destravar o CRM.
    email = lead_data.get('email')
    if not email:
        email = f"{number}@atendimento.com.br"

    payload = {
        "name": first_name,
        "lastName": last_name if last_name != first_name else "",
        "idBranch": int(id_branch),
        "email": email,
        "ddi": ddi,
        "cellphone": number,
        "notes": f"WhatsApp / IA - {lead_data.get('notes', 'Interesse detectado')}",
        "currentStep": "Contato Inicial (IA)",
        "marketingType": "WhatsApp / IA",
        "temperature": int(lead_data.get('temperature', 1))
    }

    logger.debug(f"📤 [CRM EVO] Enviando prospect: {full_name} | Fone: {ddi}{number} | Temp: {payload['temperature']}")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=15)
            if resp.status_code in (200, 201):
                data = resp.json()
                prospect_id = None
                if isinstance(data, dict):
                    prospect_id = data.get('idProspect') or data.get('id')
                elif isinstance(data, list) and len(data) > 0:
                    prospect_id = data[0].get('idProspect') or data[0].get('id')
                
                logger.info(f"🚀 [CRM EVO] Prospect CRIADO com SUCESSO na Unidade {unidade_id} (ID: {prospect_id})")
                return prospect_id or True
            else:
                logger.error(f"❌ Erro EVO API ({resp.status_code}): {resp.text}")
                return False
    except Exception as e:
        logger.error(f"Exceção ao criar prospect na EVO: {e}")
        return False
