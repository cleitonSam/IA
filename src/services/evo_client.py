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
    integracao = await carregar_integracao(empresa_id, "evo", unidade_id=unidade_id)
    if not integracao:
        return []
    branch = id_branch or integracao.get("idBranch")
    if not branch:
        logger.warning(f"⚠️ EVO horarios: idBranch ausente empresa={empresa_id}")
        return []

    cache_key = f"evo:horarios:{empresa_id}:{branch}:{dias_a_frente}"
    cached = await _cache_get_json(cache_key)
    if cached is not None:
        # Aplica filtro mesmo no cache
        if filtro_id_activities:
            allow = set(int(x) for x in filtro_id_activities)
            cached = [s for s in cached if int(s.get("idActivity") or 0) in allow]
        return cached

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
    for s in todas:
        cap = int(s.get("capacity") or 0)
        ocu = int(s.get("ocupation") or 0)
        if cap <= 0 or (cap - ocu) <= 0:
            continue
        # [FIX-C] filtra sessoes cuja janela de reserva ja fechou
        _bend = s.get("bookingEndTime")
        if _bend:
            try:
                # bookingEndTime pode vir como "yyyy-MM-dd HH:mm:ss" ou ISO
                _bdt = _dt.fromisoformat(str(_bend).replace("T", " ").split(".")[0])
                if _bdt < _agora:
                    continue  # janela ja fechou — descarta
            except Exception:
                pass  # se nao parseou, deixa passar
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

    await _cache_set_json(cache_key, normalizado, _CACHE_HORARIOS)

    # Aplica filtro depois de cachear (cache fica completo, filtro e por chamada)
    if filtro_id_activities:
        allow = set(int(x) for x in filtro_id_activities)
        normalizado = [s for s in normalizado if int(s.get("idActivity") or 0) in allow]

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
) -> Dict[str, Any]:
    """Agenda uma aula experimental para o prospect.
    Retorna {ok: bool, status: int, mensagens: [str], data: {...}}.
    Apos sucesso, invalida cache de horarios pra refletir nova ocupacao."""
    integracao = await carregar_integracao(empresa_id, "evo", unidade_id=unidade_id)
    if not integracao:
        return {"ok": False, "status": 0, "mensagens": ["Integracao EVO nao configurada"]}

    branch = id_branch or integracao.get("idBranch")
    if not branch:
        return {"ok": False, "status": 0, "mensagens": ["idBranch nao definido"]}

    headers = await _get_evo_headers(integracao)
    if not headers:
        return {"ok": False, "status": 0, "mensagens": ["Credenciais EVO ausentes"]}

    # [FIX-B] re-check de vaga ANTES de agendar (anti-race com outros agendamentos)
    # Se a sessao ja encheu desde que a IA listou, retorna erro especifico
    # pra IA poder dizer "esse horario acabou de encher, escolhe outro?".
    if id_activity:
        try:
            _check_url = f"{_evo_api_base(integracao)}/activities/schedule/detail"
            _check = await _evo_request(
                "GET", _check_url, headers,
                params={"idActivitySession": str(id_activity)},
                log_tag=f"EVO:check:{empresa_id}",
            )
            if _check is not None and _check.status_code == 200:
                _det = _check.json() or {}
                _cap = int(_det.get("capacity") or 0)
                _ocu = int(_det.get("ocupation") or 0)
                if _cap > 0 and _ocu >= _cap:
                    logger.info(f"⚠️ EVO: sessao {id_activity} encheu antes do agendamento (cap={_cap} ocu={_ocu})")
                    return {
                        "ok": False, "status": 409,
                        "mensagens": [
                            "Esse horario acabou de encher (alguem reservou a ultima vaga). Escolha outro horario."
                        ],
                        "vaga_perdida": True,
                    }
        except Exception as _ec:
            # Se o re-check falhar, segue tentando o agendamento mesmo assim
            logger.debug(f"[FIX-B] re-check vaga falhou (seguindo): {_ec}")

    url = f"{_evo_api_base(integracao)}/activities/schedule/experimental-class"
    params = {
        "idProspect": str(id_prospect),
        "activityDate": activity_date,
        "activity": activity_name,
        "service": service_name,
        "activityExist": "true",
        "idBranch": str(branch),
    }
    if id_activity:
        params["idActivity"] = str(id_activity)
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
    return {"ok": False, "status": resp.status_code, "mensagens": msgs or [f"HTTP {resp.status_code}"], "data": data}
