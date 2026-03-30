import asyncio
import base64
import httpx
from typing import Optional, Dict, Any
from src.core.config import logger
from src.services.db_queries import carregar_integracao

# Número máximo de retentativas para chamadas à EVO API
_EVO_MAX_RETRIES = 3
# Timeout padrão por requisição (em segundos)
_EVO_TIMEOUT = 15


async def _get_evo_headers(integracao: Dict[str, Any]) -> Dict[str, str]:
    dns = integracao.get('dns')
    secret_key = integracao.get('secret_key')
    if not dns or not secret_key:
        return {}
    auth = base64.b64encode(f"{dns}:{secret_key}".encode()).decode()
    return {
        'Authorization': f'Basic {auth}',
        'accept': 'application/json',
        'Content-Type': 'application/json',
    }


async def _evo_request(
    method: str,
    url: str,
    headers: Dict[str, str],
    *,
    json: Any = None,
    params: Dict[str, str] = None,
    timeout: float = _EVO_TIMEOUT,
    retries: int = _EVO_MAX_RETRIES,
    log_tag: str = "EVO",
) -> Optional[httpx.Response]:
    """
    Wrapper centralizado para requisições à EVO API com retry automático.
    - Retry em falhas de rede e erros 5xx (serviço temporariamente indisponível)
    - Sem retry em erros 4xx (problema nos dados enviados)
    - Backoff exponencial: 1s, 2s, 4s
    """
    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.request(
                    method, url,
                    headers=headers,
                    json=json,
                    params=params,
                )
            # Erros 4xx = problema nos dados, não faz sentido tentar novamente
            if 400 <= resp.status_code < 500:
                logger.warning(f"⚠️ [{log_tag}] HTTP {resp.status_code} (sem retry): {resp.text[:300]}")
                return resp
            # Erros 5xx = servidor EVO com problema, vale tentar novamente
            if resp.status_code >= 500:
                logger.warning(f"⚠️ [{log_tag}] HTTP {resp.status_code} tentativa {attempt}/{retries}")
                if attempt < retries:
                    await asyncio.sleep(2 ** (attempt - 1))
                    continue
            return resp
        except httpx.TimeoutException:
            logger.warning(f"⚠️ [{log_tag}] Timeout tentativa {attempt}/{retries} — {url}")
        except httpx.ConnectError as e:
            logger.warning(f"⚠️ [{log_tag}] Falha de conexão tentativa {attempt}/{retries}: {e}")
        except Exception as e:
            logger.error(f"❌ [{log_tag}] Erro inesperado tentativa {attempt}/{retries}: {type(e).__name__}: {e}")

        if attempt < retries:
            await asyncio.sleep(2 ** (attempt - 1))  # backoff: 1s, 2s, 4s

    logger.error(f"❌ [{log_tag}] Todas as {retries} tentativas falharam — {url}")
    return None


async def verificar_status_membro_evo(
    phone: str,
    empresa_id: int,
    unidade_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Verifica se o telefone pertence a um membro (aluno) na EVO.
    Tenta priorizar a integração da unidade específica.
    Retorna dict com is_aluno, status, nome, id_member.
    """
    integracao = await carregar_integracao(empresa_id, 'evo', unidade_id=unidade_id)
    if not integracao:
        logger.debug(f"ℹ️ Sem integração EVO para Empresa {empresa_id} (Unid {unidade_id})")
        return {"status": "desconhecido", "is_aluno": False}

    headers = await _get_evo_headers(integracao)
    if not headers:
        logger.warning(f"⚠️ EVO: credenciais ausentes para Empresa {empresa_id} (Unid {unidade_id})")
        return {"status": "erro_config", "is_aluno": False}

    api_base = integracao.get('api_url', 'https://evo-integracao-api.w12app.com.br/api/v2')
    url = f"{api_base.replace('/v2', '/v1')}/members/basic"

    resp = await _evo_request(
        "GET", url, headers,
        params={"phone": phone},
        log_tag=f"EVO:membro:{empresa_id}",
    )
    if resp is None:
        return {"is_aluno": False, "status": "erro_timeout"}

    if resp.status_code == 200:
        try:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                aluno = data[0]
                nome = f"{aluno.get('firstName', '')} {aluno.get('lastName', '')}".strip()
                logger.info(f"✅ Aluno identificado na EVO: {nome} (Unid {unidade_id})")
                return {
                    "is_aluno": True,
                    "nome": nome,
                    "status": aluno.get("membershipStatus") or aluno.get("status", "Ativo"),
                    "id_member": aluno.get("idMember"),
                }
        except Exception as e:
            logger.error(f"❌ EVO: erro ao parsear resposta de membro: {e}")

    return {"is_aluno": False, "status": "lead"}


async def criar_prospect_evo(
    empresa_id: int,
    unidade_id: Optional[int],
    lead_data: Dict[str, Any],
) -> Any:
    """
    Cria um Prospect (Oportunidade) na EVO garantindo o isolamento da unidade.
    Retorna o ID do prospect criado ou True em sucesso, False em falha.
    """
    integracao = await carregar_integracao(empresa_id, 'evo', unidade_id=unidade_id)
    if not integracao:
        logger.warning(
            f"⚠️ EVO: Integração não encontrada — "
            f"Empresa {empresa_id} (Unid {unidade_id})"
        )
        return False

    id_branch = integracao.get('idBranch') or lead_data.get('idBranch')
    if not id_branch:
        logger.error(
            f"❌ EVO: tentativa de criar prospect sem idBranch — "
            f"Empresa {empresa_id} (Unid {unidade_id})"
        )
        return False

    headers = await _get_evo_headers(integracao)
    if not headers:
        logger.warning(f"⚠️ EVO: credenciais ausentes para Empresa {empresa_id}")
        return False

    api_base = integracao.get('api_url', 'https://evo-integracao-api.w12app.com.br/api/v2')
    url = f"{api_base.replace('/v2', '/v1')}/prospects"

    # Normaliza telefone
    phone_raw = lead_data.get('cellphone', '').replace('+', '').replace(' ', '').replace('-', '')
    if phone_raw.startswith('55') and len(phone_raw) >= 12:
        ddi, number = '55', phone_raw[2:]
    else:
        ddi, number = '55', phone_raw

    full_name = lead_data.get('name', 'Lead WhatsApp').strip()
    name_parts = full_name.split(' ', 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else first_name

    # E-mail é OBRIGATÓRIO na EVO v1 Prospects.
    # Se não houver, usa placeholder baseado no telefone (auditável nos logs).
    email = lead_data.get('email') or f"{number}@atendimento.com.br"
    if not lead_data.get('email'):
        logger.debug(f"📋 EVO: email placeholder gerado para {number}: {email}")

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
        "temperature": int(lead_data.get('temperature', 1)),
    }

    logger.debug(
        f"📤 [EVO] Enviando prospect: {full_name} | "
        f"Fone: {ddi}{number} | Temp: {payload['temperature']} | Unid: {unidade_id}"
    )

    resp = await _evo_request(
        "POST", url, headers,
        json=payload,
        log_tag=f"EVO:prospect:{empresa_id}",
    )
    if resp is None:
        return False

    if resp.status_code in (200, 201):
        try:
            data = resp.json()
            prospect_id = None
            if isinstance(data, dict):
                prospect_id = data.get('idProspect') or data.get('id')
            elif isinstance(data, list) and data:
                prospect_id = data[0].get('idProspect') or data[0].get('id')
            logger.info(
                f"🚀 [EVO] Prospect criado com sucesso — "
                f"Unid {unidade_id} (ID: {prospect_id})"
            )
            return prospect_id or True
        except Exception as e:
            logger.error(f"❌ EVO: erro ao parsear resposta de prospect criado: {e}")
            return True  # Criou mas não conseguiu ler o ID
    else:
        logger.error(f"❌ EVO API ({resp.status_code}): {resp.text[:400]}")
        return False
