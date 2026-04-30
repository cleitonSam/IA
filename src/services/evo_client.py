
async def _aplicar_filtro_atividades(empresa_id: int, lista: list, filtro_ids: list) -> list:
    """Aplica filtro de atividades em lista de horarios.
    [FIX-CROSS-BRANCH] Varre TODAS as integracoes EVO da empresa pra encontrar
    onde os IDs do filtro existem (cada filial tem IDs diferentes pra mesma
    atividade). Extrai os NOMES e filtra a lista por nome (cross-filial).
    Se traducao falhar, fallback pro filtro por ID puro."""
    if not filtro_ids:
        return lista
    allow_ids = set(int(x) for x in filtro_ids if str(x).isdigit())
    nomes_permitidos: set = set()
    try:
        from src.utils.text_helpers import normalizar
        from src.services.db_queries import listar_unidades_ativas

        # [FIX] Tenta primeiro com a credencial padrao (cache hit normal)
        todas_atividades = await listar_activities_evo(empresa_id, unidade_id=None)
        achados = {a.get("id") for a in todas_atividades if a.get("id") in allow_ids}
        for a in todas_atividades:
            if a.get("id") in allow_ids and a.get("name"):
                nomes_permitidos.add(normalizar(a["name"]).strip(" ."))

        # [FIX] Se nao achou TODAS as IDs, varre as outras filiais
        if achados != allow_ids:
            unidades = await listar_unidades_ativas(empresa_id)
            for u in unidades or []:
                _uid = u.get("id") if isinstance(u, dict) else None
                if not _uid:
                    continue
                try:
                    acts_unid = await listar_activities_evo(empresa_id, unidade_id=_uid)
                    for a in acts_unid:
                        if a.get("id") in allow_ids and a.get("name"):
                            nomes_permitidos.add(normalizar(a["name"]).strip(" ."))
                            achados.add(a.get("id"))
                    if achados == allow_ids:
                        break  # ja achou todos
                except Exception:
                    continue
    except Exception as _e:
        logger.debug(f"[_aplicar_filtro_atividades] discovery falhou: {_e}")

    if nomes_permitidos:
        from src.utils.text_helpers import normalizar
        filtrado = []
        for s in lista:
            nome_norm = normalizar(s.get("name") or "").strip(" .")
            if nome_norm in nomes_permitidos or any(n in nome_norm for n in nomes_permitidos):
                filtrado.append(s)
        if filtrado:
            return filtrado
    return [s for s in lista if int(s.get("idActivity") or 0) in allow_ids]


import asyncio
import base64
import json as _json
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from src.core.config import logger
from src.core.redis_client import redis_client
from src.services.db_queries import carregar_integracao

# Cache TTLs (segundos)
_CACHE_DISCOVERY = 600    # branches/services/activities raramente mudam — 10min
_CACHE_HORARIOS = 120     # horarios mudam por concorrencia — 2min

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



# ════════════════════════════════════════════════════════════════════════════
# AGENDAMENTO DE AULA EXPERIMENTAL — Fase 1
# ════════════════════════════════════════════════════════════════════════════


def _calc_janela_booking(s):
    """Retorna (booking_start_dt, booking_end_dt) combinando hora+data corretamente.
    bookingStartTime/EndTime vem como hora pura (ex: '15:00:00') e precisa combinar
    com activityDate considerando que se start > startTime da aula, abre dia ANTERIOR."""
    from datetime import datetime as _dt2, timedelta as _td2
    _adate = str(s.get("activityDate") or "")[:10].replace("T", "").strip()
    _stime = str(s.get("startTime") or "")[:5].strip()
    if not _adate or len(_adate) < 10 or not _stime:
        return None, None
    try:
        _aula_dt = _dt2.fromisoformat(f"{_adate} {_stime}:00")
    except Exception:
        return None, None

    _bstart = str(s.get("bookingStartTime") or "").strip()
    _bend = str(s.get("bookingEndTime") or "").strip()
    bstart_dt = bend_dt = None

    if _bstart and ":" in _bstart and len(_bstart) <= 8:
        try:
            _bs_t = _dt2.fromisoformat(f"{_adate} {_bstart[:8]}").time()
            if _bs_t > _aula_dt.time():
                # janela abre no dia ANTERIOR
                bstart_dt = _dt2.combine((_aula_dt - _td2(days=1)).date(), _bs_t)
            else:
                bstart_dt = _dt2.fromisoformat(f"{_adate} {_bstart[:8]}")
        except Exception:
            pass

    if _bend and ":" in _bend and len(_bend) <= 8:
        try:
            _be_t = _dt2.fromisoformat(f"{_adate} {_bend[:8]}").time()
            # bookingEnd geralmente é antes do startTime ou logo apos meia-noite
            if _be_t > _aula_dt.time():
                # fim depois da hora da aula? combina com dia anterior
                bend_dt = _dt2.combine((_aula_dt - _td2(days=1)).date(), _be_t)
            else:
                bend_dt = _dt2.fromisoformat(f"{_adate} {_bend[:8]}")
        except Exception:
            pass

    return bstart_dt, bend_dt


def _evo_api_base(integracao: Dict[str, Any]) -> str:
    """URL base v1 da EVO (compatibilidade com integracoes antigas v2)."""
    api = integracao.get("api_url", "https://evo-integracao-api.w12app.com.br/api/v2")
    return api.replace("/v2", "/v1")


async def _cache_get_json(key: str) -> Any:
    try:
        raw = await redis_client.get(key)
        if raw:
            return _json.loads(raw)
    except Exception:
        pass
    return None


async def _cache_set_json(key: str, value: Any, ttl: int) -> None:
    try:
        await redis_client.setex(key, ttl, _json.dumps(value, default=str))
    except Exception:
        pass


async def _carregar_integracao_franqueada(empresa_id: int, unidade_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """[FRANQUEADA] Carrega credencial EVO escopada SOMENTE pra consulta de membros.
    Ordem de preferencia:
      1) GLOBAL da empresa (tipo='evo_franqueada', unidade_id IS NULL) — caso de 1 cred unica que serve todas
      2) Da unidade especifica (tipo='evo_franqueada', unidade_id=X) — legado/per-unit
      3) Fallback: cred geral 'evo' da unidade (matriz)
    Esta cred NAO e usada por workers/agendamento — so por verificar_membro_evo.
    """
    try:
        import src.core.database as _database
        if not _database.db_pool:
            return None

        # 1) Cred GLOBAL da empresa (1 cred pra todas unidades — modelo preferido)
        row_global = await _database.db_pool.fetchrow(
            """SELECT config FROM integracoes
               WHERE empresa_id = $1 AND tipo = 'evo_franqueada' AND unidade_id IS NULL AND ativo = true
               ORDER BY id DESC LIMIT 1""",
            empresa_id,
        )
        if row_global and row_global["config"]:
            cfg = row_global["config"]
            if isinstance(cfg, str):
                cfg = _json.loads(cfg)
            return cfg

        # 2) Cred per-unit (legado, se ainda existir)
        if unidade_id:
            row_unit = await _database.db_pool.fetchrow(
                """SELECT config FROM integracoes
                   WHERE empresa_id = $1 AND tipo = 'evo_franqueada' AND unidade_id = $2 AND ativo = true
                   ORDER BY id DESC LIMIT 1""",
                empresa_id, unidade_id,
            )
            if row_unit and row_unit["config"]:
                cfg = row_unit["config"]
                if isinstance(cfg, str):
                    cfg = _json.loads(cfg)
                return cfg

        # 3) Fallback: cred 'evo' da unidade (matriz multilocation)
        if unidade_id:
            row_evo = await _database.db_pool.fetchrow(
                """SELECT config FROM integracoes
                   WHERE empresa_id = $1 AND tipo = 'evo' AND unidade_id = $2 AND ativo = true
                   ORDER BY id DESC LIMIT 1""",
                empresa_id, unidade_id,
            )
            if row_evo and row_evo["config"]:
                cfg = row_evo["config"]
                if isinstance(cfg, str):
                    cfg = _json.loads(cfg)
                return cfg
    except Exception as e:
        logger.warning(f"[FRANQUEADA] erro carregar cred empresa={empresa_id} unidade={unidade_id}: {e}")
    return None


def _normalizar_telefone(t: str) -> str:
    """Tira tudo que nao e digito. EVO aceita com ou sem DDI; mantem so digitos.
    Ex: '+55 (11) 97680-4555' -> '5511976804555'."""
    import re as _re
    return _re.sub(r"\D", "", str(t or ""))


async def verificar_membro_evo(
    empresa_id: int,
    telefone: str,
    unidade_id: Optional[int] = None,
) -> Dict[str, Any]:
    """[FRANQUEADA] Consulta GET /members?phone=X na credencial da unidade.
    Retorna dict estruturado:
      {
        "encontrado": bool,
        "id_membro": int|None,
        "nome": str|None,
        "ativo": bool|None,         # situacao do aluno (True = ativo, False = bloqueado/cancelado)
        "telefone_normalizado": str,
        "raw_status": int,           # http status da EVO
        "erro": str|None,            # mensagem se algo falhou
      }
    Cache curto (5min) em Redis pra evitar martelar a EVO em rajada de webhooks.
    """
    fone_norm = _normalizar_telefone(telefone)
    if not fone_norm or len(fone_norm) < 8:
        return {"encontrado": False, "erro": "telefone_invalido", "telefone_normalizado": fone_norm}

    # Tira DDI Brasil pra busca (EVO costuma cadastrar so DDD+numero)
    fone_busca = fone_norm
    if fone_busca.startswith("55") and len(fone_busca) > 11:
        fone_busca = fone_busca[2:]

    # Cache global por empresa+telefone (1 cred unica serve todas unidades)
    cache_key = f"evo:membro:{empresa_id}:{unidade_id or 'global'}:{fone_busca}"
    cached = await _cache_get_json(cache_key)
    if cached is not None:
        return cached

    integracao = await _carregar_integracao_franqueada(empresa_id, unidade_id)
    if not integracao:
        out = {
            "encontrado": False,
            "erro": "integracao_franqueada_nao_configurada",
            "telefone_normalizado": fone_norm,
        }
        await _cache_set_json(cache_key, out, 60)
        return out

    headers = await _get_evo_headers(integracao)
    if not headers:
        return {
            "encontrado": False,
            "erro": "credenciais_incompletas",
            "telefone_normalizado": fone_norm,
        }

    url = (
        f"{_evo_api_base(integracao)}/members?phone={fone_busca}"
        "&take=10&skip=0&onlyPersonal=false"
        "&showActivityData=false&showMemberships=true&showsResponsibles=false"
    )
    resp = await _evo_request("GET", url, headers, log_tag=f"EVO:membro:{empresa_id}:u{unidade_id or 'global'}")
    if resp is None:
        return {
            "encontrado": False,
            "erro": "evo_sem_resposta",
            "telefone_normalizado": fone_norm,
        }

    if resp.status_code == 401:
        return {
            "encontrado": False,
            "erro": "credencial_invalida",
            "raw_status": 401,
            "telefone_normalizado": fone_norm,
        }
    if resp.status_code != 200:
        return {
            "encontrado": False,
            "erro": f"http_{resp.status_code}",
            "raw_status": resp.status_code,
            "telefone_normalizado": fone_norm,
        }

    try:
        data = resp.json() or []
    except Exception:
        data = []

    items = data if isinstance(data, list) else (data.get("data") if isinstance(data, dict) else []) or []
    if not items:
        out = {
            "encontrado": False,
            "raw_status": 200,
            "telefone_normalizado": fone_norm,
        }
        await _cache_set_json(cache_key, out, 300)  # nao-encontrado: cache 5min
        return out

    # Pega o primeiro membro (telefone unico na maioria dos casos)
    m = items[0] if isinstance(items[0], dict) else {}
    # Campos comuns na resposta da EVO v2
    id_membro = m.get("idMember") or m.get("id") or m.get("idClient")
    first_name = m.get("firstName") or m.get("registerName") or m.get("nameMember") or ""
    last_name = m.get("lastName") or m.get("registerLastName") or ""
    if isinstance(first_name, str): first_name = first_name.strip()
    if isinstance(last_name, str): last_name = last_name.strip()
    # Nome completo capitalizado (EVO geralmente devolve em UPPERCASE)
    nome_completo = f"{first_name} {last_name}".strip().title() if (first_name or last_name) else None
    nome = first_name.title() if first_name else nome_completo

    # Branch (qual unidade ele e aluno)
    id_branch = m.get("idBranch")
    branch_name = m.get("branchName") or ""
    if isinstance(branch_name, str): branch_name = branch_name.strip()

    # ── Situacao do aluno ──
    # Ordem de prioridade: status (string EVO) -> active (bool) -> memberships -> accessBlocked
    # EVO retorna "status": "Active" pra alunos com cadastro ativo.
    status_str = str(m.get("status") or "").strip().lower()
    membership_status_str = str(m.get("membershipStatus") or "").strip().lower()
    access_blocked = m.get("accessBlocked")
    ativo_raw = None

    if status_str:
        ativo_raw = status_str in ("active", "ativo", "true", "1")
    elif m.get("active") is not None:
        ativo_raw = bool(m.get("active"))
    elif membership_status_str:
        ativo_raw = membership_status_str in ("active", "ativo", "true", "1")
    elif access_blocked is not None:
        ativo_raw = not bool(access_blocked)
    else:
        memberships = m.get("memberships") or []
        if isinstance(memberships, list) and memberships:
            ativo_raw = any(
                str(mb.get("status") or mb.get("active") or "").lower() in ("active", "true", "ativo", "1")
                for mb in memberships if isinstance(mb, dict)
            )
        else:
            ativo_raw = True  # cadastrado mas sem dado de status -> assume ativo

    # Campos extras pra nota interna / atributos
    register_date = m.get("registerDate") or m.get("conversionDate")
    last_access = m.get("lastAccessDate")
    employee_consultant = m.get("nameEmployeeConsultant") or ""
    if isinstance(employee_consultant, str): employee_consultant = employee_consultant.strip()
    instructor = m.get("nameEmployeeInstructor") or ""
    personal = m.get("nameEmployeePersonalTrainer") or ""
    # Email do contato
    _email = None
    for _c in (m.get("contacts") or []):
        if isinstance(_c, dict) and (_c.get("contactType") or "").lower() in ("email", "e-mail"):
            _email = _c.get("description")
            break
    # Plano (do primeiro membership)
    _plano = None
    _memberships = m.get("memberships") or []
    if isinstance(_memberships, list) and _memberships:
        _mb = _memberships[0]
        if isinstance(_mb, dict):
            _plano = _mb.get("name") or _mb.get("nameMembership") or _mb.get("displayName")

    out = {
        "encontrado": True,
        "id_branch": id_branch,
        "branch_name": branch_name,
        "first_name": first_name,
        "last_name": last_name,
        "nome_completo": nome_completo,
        "register_date": register_date,
        "last_access_date": last_access,
        "consultor": employee_consultant or None,
        "instrutor": instructor or None,
        "personal": personal or None,
        "email": _email,
        "plano": _plano,
        "status_raw": status_str or None,
        "id_membro": id_membro,
        "nome": nome,
        "ativo": bool(ativo_raw),
        "raw_status": 200,
        "telefone_normalizado": fone_norm,
    }
    await _cache_set_json(cache_key, out, 86400)  # encontrado: cache 24h
    return out


# ────────── VOUCHERS (cred franqueada global) ──────────

async def listar_vouchers_evo(
    empresa_id: int,
    only_valid: bool = True,
    take: int = 50,
) -> list:
    """Lista vouchers da EVO usando cred franqueada GLOBAL.
    Retorna lista normalizada com campos uteis pra IA decidir.
    only_valid=True passa filtro valid=true na query (so vouchers ativos).
    Cache 10min em Redis (vouchers raramente mudam).
    """
    cache_key = f"evo:vouchers:{empresa_id}:{int(only_valid)}:{take}"
    cached = await _cache_get_json(cache_key)
    if cached is not None:
        return cached

    integracao = await _carregar_integracao_franqueada(empresa_id)
    if not integracao:
        return []
    headers = await _get_evo_headers(integracao)
    if not headers:
        return []

    params = {"take": str(take), "skip": "0"}
    if only_valid:
        params["valid"] = "true"

    url = f"{_evo_api_base(integracao)}/voucher"
    resp = await _evo_request("GET", url, headers, params=params, log_tag=f"EVO:vouchers:{empresa_id}")
    if resp is None or resp.status_code != 200:
        logger.warning(f"[EVO vouchers] empresa={empresa_id} HTTP={resp.status_code if resp else 'None'}")
        return []
    try:
        data = resp.json() or []
    except Exception:
        data = []
    if not isinstance(data, list):
        data = data.get("data", []) if isinstance(data, dict) else []

    from datetime import datetime as _dt
    _agora = _dt.now()
    normalizado = []
    for v in data:
        if not isinstance(v, dict):
            continue
        # Filtros de qualidade: valid, nao vencido, com vagas (se limited)
        if v.get("overdue") is True:
            continue
        if v.get("limited") and (v.get("available") or 0) <= 0:
            continue
        # Parse expiration
        _exp = v.get("expirationDate")
        if _exp:
            try:
                _exp_dt = _dt.fromisoformat(str(_exp).replace("Z", ""))
                if _exp_dt < _agora:
                    continue
            except Exception:
                pass

        # Desconto efetivo (mensal preferido)
        desc_mensal = v.get("monthyDiscount") or {}
        desc_anual = v.get("yearlyDiscount") or {}
        desc_servico = v.get("serviceDiscount") or {}
        _desc = None
        _tipo_desc = None
        for d_obj, label in [(desc_mensal, "mensal"), (desc_anual, "anual"), (desc_servico, "servico")]:
            if isinstance(d_obj, dict) and d_obj.get("value"):
                _desc = {
                    "tipo": d_obj.get("typeDiscountMembership") or d_obj.get("typeDiscountService") or "percentage",
                    "valor": d_obj.get("value"),
                    "meses": d_obj.get("numberMounths") or d_obj.get("numberMonths"),
                }
                _tipo_desc = label
                break

        normalizado.append({
            "id": v.get("idVoucher"),
            "nome": v.get("nameVoucher"),
            "tipo": v.get("typeVoucher"),  # Membership / Service
            "limited": v.get("limited"),
            "available": v.get("available"),
            "used": v.get("used"),
            "expira_em": str(v.get("expirationDate") or "")[:10] or None,
            "id_memberships": v.get("idMemberships") or [],  # planos vinculados (vazio = todos)
            "site_disponivel": v.get("siteAvailable"),
            "desconto": _desc,
            "tipo_desconto": _tipo_desc,
        })

    await _cache_set_json(cache_key, normalizado, 600)  # 10 min
    return normalizado


async def listar_memberships_evo(empresa_id: int) -> dict:
    """Lista TODOS os memberships (planos) da EVO via cred franqueada.
    Retorna dict {idMembership: {nome, valor, duracao, tipo_contrato}}.
    Cache 30min — planos raramente mudam.
    """
    cache_key = f"evo:memberships:{empresa_id}"
    cached = await _cache_get_json(cache_key)
    if cached is not None:
        return cached

    integracao = await _carregar_integracao_franqueada(empresa_id)
    if not integracao:
        return {}
    headers = await _get_evo_headers(integracao)
    if not headers:
        return {}

    url = f"{_evo_api_base(integracao)}/membership?take=200&skip=0&active=true"
    resp = await _evo_request("GET", url, headers, log_tag=f"EVO:memberships:{empresa_id}")
    if resp is None or resp.status_code != 200:
        logger.warning(f"[EVO memberships] HTTP={resp.status_code if resp else 'None'}")
        return {}
    try:
        data = resp.json() or []
    except Exception:
        data = []
    if not isinstance(data, list):
        data = data.get("data", []) if isinstance(data, dict) else []

    out = {}
    for m in data:
        if not isinstance(m, dict):
            continue
        _id = m.get("idMembership") or m.get("id")
        if not _id:
            continue
        out[int(_id)] = {
            "id": int(_id),
            "nome": m.get("displayName") or m.get("nameMembership") or m.get("name") or f"Plano {_id}",
            "valor": float(m.get("value") or 0),
            "valor_promocional": m.get("valuePromotionalPeriod"),
            "duracao": m.get("duration"),  # ex: 1, 12
            "duration_type": m.get("durationType"),  # ex: "Monthly", "Yearly"
            "tipo_contrato": m.get("salesType") or m.get("recurrenceType") or "",  # ex: "Monthly recurrence"
            "id_branch": m.get("idBranch"),
        }
    await _cache_set_json(cache_key, out, 1800)  # 30min
    return out


async def validar_voucher_evo(
    empresa_id: int,
    voucher_code: str,
    id_membership: int = 0,
    id_service: int = 0,
    id_branch: int = 0,
) -> dict:
    """Valida um voucher pra um plano especifico via POST /voucher/voucher-verify.
    Se 200: voucher aplicavel, retorna detalhes do desconto.
    Se 400: voucher invalido, errors[].value explica por que.
    """
    if not voucher_code:
        return {"ok": False, "erro": "voucher_vazio"}
    integracao = await _carregar_integracao_franqueada(empresa_id)
    if not integracao:
        return {"ok": False, "erro": "integracao_franqueada_nao_configurada"}
    headers = await _get_evo_headers(integracao)
    if not headers:
        return {"ok": False, "erro": "credenciais_incompletas"}

    url = f"{_evo_api_base(integracao)}/voucher/voucher-verify"
    payload = {
        "voucher": str(voucher_code),
        "idMembership": int(id_membership or 0),
        "idService": int(id_service or 0),
        "idBranch": int(id_branch or 0),
    }
    resp = await _evo_request("POST", url, headers, json=payload, log_tag=f"EVO:voucher-verify:{empresa_id}")
    if resp is None:
        return {"ok": False, "erro": "evo_sem_resposta"}
    try:
        body = resp.json()
    except Exception:
        body = None

    if 200 <= resp.status_code < 300:
        return {"ok": True, "dados": body, "status": resp.status_code}

    # Extrai erro especifico
    msg = "voucher_invalido"
    if isinstance(body, dict):
        errs = body.get("errors") or []
        if isinstance(errs, list) and errs:
            _e = errs[0] if isinstance(errs[0], dict) else {}
            msg = str(_e.get("value") or _e.get("description") or msg)
    return {"ok": False, "erro": msg, "status": resp.status_code}


async def _carregar_qualquer_integracao_evo(empresa_id: int, unidade_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Pra DISCOVERY (branches/services/activities): tenta unidade_id especifico,
    depois global, depois QUALQUER integracao EVO ativa da empresa.
    Discovery retorna meta-info da academia que e igual entre unidades, entao
    pegar credencial de qualquer unidade resolve quando nao ha integracao global."""
    integracao = await carregar_integracao(empresa_id, "evo", unidade_id=unidade_id)
    if integracao:
        return integracao

    # Fallback: pega a primeira integracao ativa da empresa, ignorando unidade_id
    try:
        import src.core.database as _database
        if not _database.db_pool:
            return None
        row = await _database.db_pool.fetchrow(
            """SELECT config FROM integracoes
               WHERE empresa_id = $1 AND tipo = 'evo' AND ativo = true
               ORDER BY id DESC LIMIT 1""",
            empresa_id,
        )
        if row and row["config"]:
            cfg = row["config"]
            if isinstance(cfg, str):
                cfg = _json.loads(cfg)
            logger.info(f"[EVO discovery] empresa={empresa_id} usando integracao fallback (qualquer unidade)")
            return cfg
    except Exception as e:
        logger.warning(f"[EVO discovery] fallback falhou: {e}")
    return None


# ────────── DISCOVERY (branches / services / activities) ──────────


async def _carregar_integracao_por_branch(empresa_id: int, id_branch: int) -> Optional[Dict[str, Any]]:
    """Pra HORARIOS/AGENDAR: busca a credencial EVO da filial especifica.
    Itera todas integracoes EVO da empresa, descobre qual filial cada uma serve
    (via /activities), e retorna a que bate com id_branch. Cache de 10min.

    Necessario porque cada credencial Goodbe = 1 filial; se passar credencial
    da filial 3 querendo agendar na filial 5, EVO retorna sessoes da filial errada."""
    cache_key = f"evo:cred_by_branch:{empresa_id}:{id_branch}"
    cached = await _cache_get_json(cache_key)
    if cached is not None:
        return cached if cached else None  # cache pode ter {} pra indicar nao-encontrado

    try:
        import src.core.database as _database
        if not _database.db_pool:
            return None
        rows = await _database.db_pool.fetch(
            """SELECT id, unidade_id, config FROM integracoes
               WHERE empresa_id = $1 AND tipo = 'evo' AND ativo = true
               ORDER BY id""",
            empresa_id,
        )
    except Exception as e:
        logger.warning(f"[EVO cred-by-branch] erro: {e}")
        return None

    if not rows:
        return None

    for row in rows:
        cfg = row["config"]
        if isinstance(cfg, str):
            try:
                cfg = _json.loads(cfg)
            except Exception:
                continue
        # Atalho: se cfg ja tem idBranch igual, usa direto
        cfg_bid = cfg.get("idBranch")
        if cfg_bid not in (None, "") and str(cfg_bid) == str(id_branch):
            await _cache_set_json(cache_key, cfg, _CACHE_DISCOVERY)
            return cfg

        # Fallback: descobre via /activities
        headers = await _get_evo_headers(cfg)
        if not headers:
            continue
        api_base = _evo_api_base(cfg)
        r = await _evo_request("GET", f"{api_base}/activities", headers, log_tag=f"EVO:byBr:{row['id']}")
        if r is None or r.status_code != 200:
            continue
        try:
            items = r.json() or []
            for it in items if isinstance(items, list) else []:
                if it.get("idBranch") and int(it["idBranch"]) == int(id_branch):
                    logger.info(f"[EVO cred-by-branch] empresa={empresa_id} branch={id_branch} -> integracao_id={row['id']}")
                    await _cache_set_json(cache_key, cfg, _CACHE_DISCOVERY)
                    return cfg
        except Exception:
            continue

    # Marca como nao-encontrado pra evitar re-iterar (cache curto)
    await _cache_set_json(cache_key, {}, 60)
    logger.warning(f"[EVO cred-by-branch] empresa={empresa_id} branch={id_branch} NAO encontrado")
    return None


async def listar_branches_evo(empresa_id: int, unidade_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Lista TODAS as filiais EVO da empresa.
    Cada credencial EVO geralmente representa UMA filial (multi-instance).
    Itera por todas integracoes EVO ativas da empresa, deriva o idBranch
    de cada uma via /activities (que sempre tem idBranch).
    Retorna lista [{id, name, unidade_id}] — unidade_id ajuda a mapear no dashboard.
    Cache 10min."""
    cache_key = f"evo:branches:{empresa_id}:all"
    cached = await _cache_get_json(cache_key)
    if cached is not None:
        return cached

    # Busca TODAS integracoes EVO ativas da empresa
    try:
        import src.core.database as _database
        if not _database.db_pool:
            return []
        rows = await _database.db_pool.fetch(
            """SELECT id, unidade_id, config FROM integracoes
               WHERE empresa_id = $1 AND tipo = 'evo' AND ativo = true
               ORDER BY id""",
            empresa_id,
        )
    except Exception as e:
        logger.warning(f"[EVO branches] erro ao listar integracoes: {e}")
        return []

    if not rows:
        return []

    # Coleta nomes das unidades (fallback de nome quando EVO nao expoe nome)
    unidade_names: Dict[int, str] = {}
    try:
        urows = await _database.db_pool.fetch(
            "SELECT id, nome FROM unidades WHERE empresa_id = $1",
            empresa_id,
        )
        unidade_names = {u["id"]: u["nome"] for u in urows}
    except Exception:
        pass

    normalizado: List[Dict[str, Any]] = []
    seen_ids: set = set()

    for row in rows:
        cfg = row["config"]
        if isinstance(cfg, str):
            try:
                cfg = _json.loads(cfg)
            except Exception:
                continue

        unidade_id_db = row["unidade_id"]
        headers = await _get_evo_headers(cfg)
        if not headers:
            continue

        api_base = _evo_api_base(cfg)

        # 1. Tenta /branches direto
        bid: Optional[int] = None
        nome_branch: Optional[str] = None
        resp = await _evo_request("GET", f"{api_base}/branches", headers, log_tag=f"EVO:br:{row['id']}")
        if resp is not None and resp.status_code == 200:
            try:
                data = resp.json() or []
                if isinstance(data, list) and data:
                    bid = data[0].get("idBranch") or data[0].get("id")
                    nome_branch = data[0].get("name") or data[0].get("nameBranch")
            except Exception:
                pass

        # 2. Fallback: deriva do /activities
        if bid is None:
            r = await _evo_request("GET", f"{api_base}/activities", headers, log_tag=f"EVO:der:{row['id']}")
            if r is not None and r.status_code == 200:
                try:
                    items = r.json() or []
                    for it in items if isinstance(items, list) else []:
                        if it.get("idBranch") is not None:
                            bid = int(it["idBranch"])
                            nome_branch = it.get("nameBranch") or it.get("branchName")
                            break
                except Exception:
                    pass

        # 3. Fallback: usa idBranch do config se preenchido
        if bid is None:
            cfg_bid = cfg.get("idBranch")
            if cfg_bid not in (None, ""):
                try:
                    bid = int(cfg_bid)
                except Exception:
                    pass

        if bid is None or bid in seen_ids:
            continue
        seen_ids.add(bid)

        # Nome amigavel: prefere o do EVO, depois o nome da unidade do nosso BD
        nome_final = nome_branch or unidade_names.get(unidade_id_db) or f"Filial {bid}"

        normalizado.append({
            "id": bid,
            "name": nome_final,
            "unidade_id": unidade_id_db,  # ajuda a mapear unidade dashboard -> filial EVO
        })

    normalizado.sort(key=lambda x: x["id"])
    await _cache_set_json(cache_key, normalizado, _CACHE_DISCOVERY)
    logger.info(f"[EVO branches] empresa={empresa_id}: {len(normalizado)} filiais descobertas: {[b['id'] for b in normalizado]}")
    return normalizado

async def listar_services_evo(empresa_id: int, unidade_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Lista servicos (planos/aulas) da academia.
    Util pra descobrir o idService da 'Aula Experimental'. Cache 10min."""
    integracao = await _carregar_qualquer_integracao_evo(empresa_id, unidade_id)
    if not integracao:
        return []
    cache_key = f"evo:services:{empresa_id}:{unidade_id or 'def'}"
    cached = await _cache_get_json(cache_key)
    if cached is not None:
        return cached

    headers = await _get_evo_headers(integracao)
    if not headers:
        return []
    url = f"{_evo_api_base(integracao)}/service"
    resp = await _evo_request("GET", url, headers, log_tag=f"EVO:services:{empresa_id}")
    if resp is None or resp.status_code != 200:
        return []
    try:
        data = resp.json() or []
        normalizado = []
        for s in data if isinstance(data, list) else []:
            normalizado.append({
                "id": s.get("idService") or s.get("id"),
                "name": s.get("nameService") or s.get("name") or "Servico",
                "value": s.get("value"),
            })
        await _cache_set_json(cache_key, normalizado, _CACHE_DISCOVERY)
        return normalizado
    except Exception as e:
        logger.warning(f"⚠️ EVO services parse: {e}")
        return []


async def listar_activities_evo(empresa_id: int, unidade_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Lista atividades (modalidades) da academia.
    Pra whitelist de quais aulas a IA pode oferecer. Cache 10min."""
    integracao = await _carregar_qualquer_integracao_evo(empresa_id, unidade_id)
    if not integracao:
        return []
    cache_key = f"evo:activities:{empresa_id}:{unidade_id or 'def'}"
    cached = await _cache_get_json(cache_key)
    if cached is not None:
        return cached

    headers = await _get_evo_headers(integracao)
    if not headers:
        return []
    url = f"{_evo_api_base(integracao)}/activities"
    resp = await _evo_request("GET", url, headers, log_tag=f"EVO:activities:{empresa_id}")
    if resp is None or resp.status_code != 200:
        return []
    try:
        data = resp.json() or []
        normalizado = []
        for a in data if isinstance(data, list) else []:
            normalizado.append({
                "id": a.get("idActivity") or a.get("id"),
                "name": a.get("name") or a.get("nameActivity") or "Atividade",
            })
        await _cache_set_json(cache_key, normalizado, _CACHE_DISCOVERY)
        return normalizado
    except Exception as e:
        logger.warning(f"⚠️ EVO activities parse: {e}")
        return []


# ────────── AGENDAR / LISTAR HORARIOS ──────────

async def listar_horarios_disponiveis_evo(
    empresa_id: int,
    unidade_id: Optional[int] = None,
    dias_a_frente: int = 5,
    id_branch: Optional[int] = None,
    filtro_id_activities: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Lista sessoes com vagas pros proximos N dias.
    A EVO nao suporta range nativo — fazemos N requests em paralelo (1 por dia)
    e agregamos. Cache de 2min por (empresa, unidade, branch, dias).
    Filtra opcionalmente por whitelist de id_activities (vazio = todas).
    Retorna lista normalizada."""
    # [FIX] Se id_branch fornecido, busca credencial DA filial X.
    # Senao, fallback pra qualquer credencial EVO da empresa.
    integracao = None
    if id_branch:
        integracao = await _carregar_integracao_por_branch(empresa_id, int(id_branch))
    if not integracao:
        integracao = await _carregar_qualquer_integracao_evo(empresa_id, unidade_id)
    if not integracao:
        logger.warning(f"⚠️ EVO horarios: nenhuma credencial encontrada empresa={empresa_id} branch={id_branch}")
        return []
    branch = id_branch or integracao.get("idBranch")
    if not branch:
        # Ultima tentativa: descobrir branch via /activities
        try:
            _hdr = await _get_evo_headers(integracao)
            if _hdr:
                _r = await _evo_request("GET", f"{_evo_api_base(integracao)}/activities", _hdr, log_tag="EVO:detect-br")
                if _r is not None and _r.status_code == 200:
                    _items = _r.json() or []
                    for _it in _items if isinstance(_items, list) else []:
                        if _it.get("idBranch") is not None:
                            branch = int(_it["idBranch"])
                            break
        except Exception:
            pass
    if not branch:
        logger.warning(f"⚠️ EVO horarios: nao consegui determinar idBranch empresa={empresa_id}")
        return []

    cache_key = f"evo:horarios:{empresa_id}:{branch}:{dias_a_frente}"
    cached = await _cache_get_json(cache_key)
    if cached is not None:
        # [FIX cache-hit] usa filtro por NOME (cross-filial), nao so por ID
        return await _aplicar_filtro_atividades(empresa_id, cached, filtro_id_activities or [])

    headers = await _get_evo_headers(integracao)
    if not headers:
        return []
    url = f"{_evo_api_base(integracao)}/activities/schedule"

    hoje = datetime.now().date()
    datas = [(hoje + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(int(dias_a_frente))]

    async def _fetch_dia(data_str):
        resp = await _evo_request(
            "GET", url, headers,
            params={
                "date": data_str,
                "onlyAvailables": "true",
                "idBranch": str(branch),
                "take": "200",
            },
            log_tag=f"EVO:sched:{data_str}",
        )
        if resp is None or resp.status_code != 200:
            return []
        try:
            return resp.json() or []
        except Exception:
            return []

    resultados = await asyncio.gather(*[_fetch_dia(d) for d in datas], return_exceptions=True)

    todas = []
    for r in resultados:
        if isinstance(r, list):
            todas.extend(r)

    from datetime import datetime as _dt
    _agora = _dt.now()
    normalizado = []
    # [DEBUG] contador de descartes pra diagnosticar "nunca tem horario"
    _desc = {"sem_vaga": 0, "passado": 0, "janela_fechada": 0, "ok": 0}
    for s in todas:
        cap = int(s.get("capacity") or 0)
        ocu = int(s.get("ocupation") or 0)
        if cap <= 0 or (cap - ocu) <= 0:
            _desc["sem_vaga"] += 1
            continue
        # [FIX-D] descarta aulas no passado
        # [REGRA-1H] Bot oferece aulas que comecam em pelo menos 1h.
        # Substitui o filtro antigo "passado" e "janela_fechada" por uma regra unica:
        # - aula no futuro com >= 1h ate o inicio = OK (bot pode oferecer)
        # - aula em menos de 1h ou ja passou = descarta
        # - bookingEndTime da EVO eh ignorado (a regra de negocio e nossa, mais
        #   permissiva: cliente pode reservar ate 1h antes mesmo se a EVO fechou janela)
        _aula_dt = None
        try:
            from datetime import timedelta as _td_1h
            _adate = str(s.get("activityDate") or "")[:10].replace("T", "").strip()
            _stime = str(s.get("startTime") or "")[:5].strip()
            if _adate and len(_adate) >= 10 and _stime:
                _aula_dt = _dt.fromisoformat(f"{_adate} {_stime}:00")
                if _aula_dt < _agora + _td_1h(hours=1):
                    # Aula passada OU comecando em menos de 1h → descarta
                    if _aula_dt < _agora:
                        _desc["passado"] += 1
                    else:
                        _desc["janela_fechada"] += 1  # reusa bucket pra log
                    continue
        except Exception:
            pass
        _desc["ok"] += 1
        normalizado.append({
            "idActivitySession": s.get("idAtividadeSessao") or s.get("idActivitySession"),
            "idActivity": s.get("idActivity"),
            "name": s.get("name"),
            "instructor": s.get("instructor") or s.get("instructorName") or "",
            "area": s.get("area") or "",
            "activityDate": s.get("activityDate"),
            "startTime": s.get("startTime"),
            "endTime": s.get("endTime"),
            "capacity": cap,
            "ocupation": ocu,
            "vagas": cap - ocu,
            "bookingEndTime": s.get("bookingEndTime"),
        })

    # Ordena por activityDate + startTime
    normalizado.sort(key=lambda x: (x.get("activityDate") or "", x.get("startTime") or ""))

    # [DEBUG] log dos descartes pra debug "nunca tem horario"
    logger.info(
        f"[EVO horarios] empresa={empresa_id} branch={branch} dias={dias_a_frente} "
        f"total_evo={len(todas)} | OK={_desc['ok']} | sem_vaga={_desc['sem_vaga']} "
        f"passado={_desc['passado']} janela_fechada={_desc['janela_fechada']}"
    )

    await _cache_set_json(cache_key, normalizado, _CACHE_HORARIOS)

    # Aplica filtro pelo helper unificado (mesma logica do cache hit)
    if filtro_id_activities:
        _antes_filtro = len(normalizado)
        normalizado = await _aplicar_filtro_atividades(empresa_id, normalizado, list(filtro_id_activities))
        logger.info(
            f"[EVO horarios] filtro_id_activities={filtro_id_activities} "
            f"-> de {_antes_filtro} restaram {len(normalizado)}"
        )

    return normalizado


async def agendar_aula_experimental_evo(
    empresa_id: int,
    unidade_id: Optional[int],
    id_prospect: int,
    activity_date: str,         # "yyyy-MM-dd HH:mm"
    activity_name: str,         # nome da modalidade (ex: "Pilates Studio")
    service_name: str = "Aula Experimental",
    id_activity: Optional[int] = None,
    id_service: Optional[int] = None,
    id_branch: Optional[int] = None,
    id_activity_session: Optional[int] = None,   # [FIX-I] id da SESSAO especifica (usado no pre-check)
) -> Dict[str, Any]:
    """Agenda uma aula experimental para o prospect.
    Retorna {ok: bool, status: int, mensagens: [str], data: {...}}.
    Apos sucesso, invalida cache de horarios pra refletir nova ocupacao."""
    # [FIX] Quando agendando em filial X, busca credencial DA filial X
    integracao = None
    if id_branch:
        integracao = await _carregar_integracao_por_branch(empresa_id, int(id_branch))
    if not integracao:
        integracao = await _carregar_qualquer_integracao_evo(empresa_id, unidade_id)
    if not integracao:
        return {"ok": False, "status": 0, "mensagens": ["Integracao EVO nao configurada"]}

    branch = id_branch or integracao.get("idBranch")
    if not branch:
        return {"ok": False, "status": 0, "mensagens": ["idBranch nao definido"]}

    headers = await _get_evo_headers(integracao)
    if not headers:
        return {"ok": False, "status": 0, "mensagens": ["Credenciais EVO ausentes"]}

    # [FIX-H] Normaliza activity_date para "yyyy-MM-dd HH:mm" (EVO exige).
    # Aceita: "yyyy-MM-dd HH:mm", "yyyy-MM-ddTHH:mm:ss", "yyyy-MM-ddT00:00:00 + start_time?"
    if activity_date:
        _ad = str(activity_date).strip().replace("T", " ")
        # corta segundos se vier "yyyy-MM-dd HH:mm:ss"
        if len(_ad) >= 19 and _ad[16] == ":":
            _ad = _ad[:16]
        # se so veio data sem hora ("yyyy-MM-dd" ou "yyyy-MM-dd 00:00"), AVISA — EVO vai falhar
        if len(_ad) == 10 or _ad.endswith(" 00:00"):
            logger.warning(
                f"⚠️ [FIX-H] activity_date sem hora real ({activity_date!r}) — "
                f"EVO provavelmente vai retornar 'Atividade nao encontrada'. "
                f"Caller deve combinar data+startTime antes de chamar."
            )
        activity_date = _ad

    # [FIX-B+I] re-check de vaga ANTES de agendar (anti-race com outros agendamentos)
    # E [FIX-E] valida janela de booking — se ainda nao abriu OU ja fechou,
    # retorna mensagem clara pra IA explicar ao cliente.
    # [FIX-I] usa id_activity_session (id da SESSAO) — antes usavamos id_activity (modalidade) por engano
    _id_para_check = id_activity_session or id_activity
    if _id_para_check:
        try:
            _check_url = f"{_evo_api_base(integracao)}/activities/schedule/detail"
            _check = await _evo_request(
                "GET", _check_url, headers,
                params={"idActivitySession": str(_id_para_check)},
                log_tag=f"EVO:check:{empresa_id}",
            )
            if _check is not None and _check.status_code == 200:
                _det = _check.json() or {}
                _cap = int(_det.get("capacity") or 0)
                _ocu = int(_det.get("ocupation") or 0)
                if _cap > 0 and _ocu >= _cap:
                    logger.info(f"⚠️ EVO: sessao {id_activity} encheu antes do agendamento")
                    return {
                        "ok": False, "status": 409,
                        "mensagens": ["Esse horario acabou de encher (alguem reservou a ultima vaga). Escolha outro horario."],
                        "vaga_perdida": True,
                    }
                # [REGRA-1H] Aceita agendamento ate 1h antes do inicio da aula.
                # Ignora bookingStartTime/EndTime da EVO — nossa regra eh mais permissiva.
                from datetime import datetime as _dt2, timedelta as _td2
                _agora2 = _dt2.now()
                _aula_dt2 = None
                try:
                    _ad = str(_det.get("activityDate") or "")[:10].replace("T", "").strip()
                    _st = str(_det.get("startTime") or "")[:5].strip()
                    if _ad and len(_ad) >= 10 and _st:
                        _aula_dt2 = _dt2.fromisoformat(f"{_ad} {_st}:00")
                except Exception:
                    pass
                if _aula_dt2:
                    if _aula_dt2 < _agora2:
                        return {
                            "ok": False, "status": 410,
                            "mensagens": ["Essa aula ja comecou — nao da pra agendar."],
                            "ja_passou": True,
                            "instrucao_ia": "A aula escolhida ja comecou. Ofereca outro horario futuro.",
                        }
                    if _aula_dt2 < _agora2 + _td2(hours=1):
                        _quando = _aula_dt2.strftime("%H:%M")
                        return {
                            "ok": False, "status": 410,
                            "mensagens": [f"Essa aula comeca em menos de 1h ({_quando}). Pra reservar, escolha outro horario com mais antecedencia."],
                            "muito_proximo": True,
                            "instrucao_ia": (
                                "A aula que o cliente escolheu comeca em menos de 1 hora — "
                                "nossa regra exige no minimo 1h de antecedencia pra agendar. "
                                "Ofereca outro horario futuro pelo menos 1h a frente."
                            ),
                        }
        except Exception as _ec:
            logger.debug(f"[FIX-B] re-check vaga falhou (seguindo): {_ec}")

    # [FIX-G] Traduz id_activity por NOME no branch alvo.
    # Cada filial tem ids LOCAIS — id_activity vindo de outra filial nao serve.
    # Faz GET /activities com a credencial DESTA filial, acha pelo nome, usa id local.
    id_activity_local = None
    if activity_name:
        try:
            from src.utils.text_helpers import normalizar
            _act_url = f"{_evo_api_base(integracao)}/activities"
            _act_resp = await _evo_request(
                "GET", _act_url, headers,
                log_tag=f"EVO:act-translate:{empresa_id}:br:{branch}",
            )
            if _act_resp is not None and _act_resp.status_code == 200:
                _acts = _act_resp.json() or []
                _alvo = normalizar(str(activity_name)).strip(" .")
                for _a in (_acts if isinstance(_acts, list) else []):
                    _nome_a = normalizar(str(_a.get("name") or _a.get("nameActivity") or "")).strip(" .")
                    if _nome_a == _alvo or (_nome_a and _alvo and (_alvo in _nome_a or _nome_a in _alvo)):
                        id_activity_local = _a.get("idActivity") or _a.get("id")
                        if id_activity_local:
                            logger.info(
                                f"[FIX-G] traduzido id_activity '{activity_name}' "
                                f"→ {id_activity_local} (branch={branch}, era {id_activity})"
                            )
                            break
        except Exception as _et:
            logger.debug(f"[FIX-G] traducao falhou (seguindo): {_et}")

    url = f"{_evo_api_base(integracao)}/activities/schedule/experimental-class"
    params = {
        "idProspect": str(id_prospect),
        "activityDate": activity_date,
        "activity": activity_name,
        "service": service_name,
        "activityExist": "true",
        "idBranch": str(branch),
    }
    # Prefere id traduzido pra esta filial; só usa o original se traducao falhou
    _id_act_final = id_activity_local or id_activity
    if _id_act_final:
        params["idActivity"] = str(_id_act_final)
    if id_service:
        params["idService"] = str(id_service)

    resp = await _evo_request(
        "POST", url, headers,
        params=params,
        log_tag=f"EVO:agendar:{empresa_id}",
    )
    if resp is None:
        return {"ok": False, "status": 0, "mensagens": ["Sem resposta da EVO (timeout)"]}

    msgs = []
    data = None
    try:
        body = resp.json()
        if isinstance(body, dict):
            msgs = body.get("mensagens") or []
            data = body
        elif isinstance(body, list):
            # EVO pode retornar lista de erros direto
            data = {"errors": body}
    except Exception:
        msgs = [resp.text[:300]] if resp.text else []

    # [FIX-G] Defesa: se 400 "Atividade nao encontrada", tenta SEM idActivity
    # (deixa EVO resolver pelo nome via activityExist=true).
    _texto_erro = ""
    try:
        _texto_erro = (resp.text or "").lower()
    except Exception:
        pass
    if (
        resp.status_code == 400
        and ("atividade" in _texto_erro and ("nao encontrada" in _texto_erro or "não encontrada" in _texto_erro))
        and "idActivity" in params
    ):
        logger.info(f"[FIX-G] retry sem idActivity (EVO recusou {params.get('idActivity')} no branch {branch})")
        params.pop("idActivity", None)
        resp2 = await _evo_request(
            "POST", url, headers,
            params=params,
            log_tag=f"EVO:agendar-retry:{empresa_id}",
        )
        if resp2 is not None:
            resp = resp2
            msgs = []
            data = None
            try:
                body = resp.json()
                if isinstance(body, dict):
                    msgs = body.get("mensagens") or []
                    data = body
            except Exception:
                msgs = [resp.text[:300]] if resp.text else []

    if 200 <= resp.status_code < 300:
        # Invalida cache de horarios — vaga foi consumida
        try:
            for k in await redis_client.keys(f"evo:horarios:{empresa_id}:{branch}:*"):
                await redis_client.delete(k)
        except Exception:
            pass
        logger.info(f"✅ EVO agendamento OK empresa={empresa_id} prospect={id_prospect} sess={params.get('activity')} @ {activity_date}")
        return {"ok": True, "status": resp.status_code, "mensagens": msgs, "data": data}

    logger.warning(f"❌ EVO agendamento falhou {resp.status_code}: {msgs or resp.text[:200]}")

    # [FIX-I] Detecta "Horario da atividade excluido" — sessao removida/cancelada na EVO.
    # Invalida cache de horarios (a lista no cliente está stale) e retorna instrucao_ia clara.
    _texto_total = ""
    try:
        _texto_total = (resp.text or "").lower()
    except Exception:
        pass
    _excluido = (
        "horario da atividade exclu" in _texto_total
        or "horário da atividade exclu" in _texto_total
        or "atividade exclu" in _texto_total
    )
    if _excluido:
        try:
            for k in await redis_client.keys(f"evo:horarios:{empresa_id}:{branch}:*"):
                await redis_client.delete(k)
            logger.info(f"[FIX-I] cache horarios invalidado (sessao excluida) empresa={empresa_id} branch={branch}")
        except Exception:
            pass
        return {
            "ok": False,
            "status": resp.status_code,
            "mensagens": ["Esse horário foi removido da agenda."],
            "sessao_excluida": True,
            "instrucao_ia": (
                "A aula que o cliente escolheu foi REMOVIDA da agenda da EVO depois "
                "que voce mostrou as opcoes (pode ter sido cancelada pela academia, "
                "ou a janela de reserva fechou). Peca desculpas, e CHAME consultar_horarios "
                "DE NOVO pra pegar a lista atualizada — depois ofereca um novo horario."
            ),
        }

    return {"ok": False, "status": resp.status_code, "mensagens": msgs or [f"HTTP {resp.status_code}"], "data": data}
