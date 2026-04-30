"""
[AGEND-02 / Fase 2] Tools que a IA pode chamar via markup <TOOL>...</TOOL>
no fluxo conversacional de agendamento de aula experimental (EVO).

Como funciona:
- A IA recebe no prompt um bloco com instruções e a lista de tools disponíveis.
- Quando ela quer chamar uma tool, retorna APENAS um bloco:
    <TOOL>{"name": "consultar_horarios", "args": {...}}</TOOL>
- O bot_core detecta esse marker, chama executar_tool() aqui, e volta o resultado
  pra IA gerar a resposta final em texto natural.
- Estado da conversa é mantido em Redis: agend_state:{empresa_id}:{conv_id}

Tools disponíveis:
  consultar_horarios(dias?: int)
    Lista sessões disponíveis pros próximos N dias (default 5, respeitando config).
    Retorna lista normalizada com id_activity_session, name, instructor, etc.

  agendar_aula(id_activity_session: int, id_activity: int, activity_name: str,
               activity_date: str, nome: str, telefone: str, email?: str)
    Cria prospect na EVO (se não existir) e agenda a sessão escolhida.
    Retorna {ok, mensagens, id_prospect}.
"""

import json
import re
from typing import Any, Dict, Optional

from src.core.config import logger
from src.core.redis_client import redis_client
from src.services.evo_client import (
    listar_horarios_disponiveis_evo,
    agendar_aula_experimental_evo,
    criar_prospect_evo,
)


_TOOL_RE = re.compile(r"<TOOL>(.*?)</TOOL>", re.DOTALL)
_AGEND_STATE_TTL = 3600  # 1h


# ─── ESTADO (Redis) ────────────────────────────────────────────────────────

def _state_key(empresa_id: int, conversation_id: int) -> str:
    return f"agend_state:{empresa_id}:{conversation_id}"


async def carregar_estado_agendamento(empresa_id: int, conversation_id: int) -> Dict[str, Any]:
    try:
        raw = await redis_client.get(_state_key(empresa_id, conversation_id))
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.debug(f"[AGEND] state load falhou: {e}")
    return {}


async def salvar_estado_agendamento(empresa_id: int, conversation_id: int, estado: Dict[str, Any]) -> None:
    try:
        await redis_client.setex(
            _state_key(empresa_id, conversation_id),
            _AGEND_STATE_TTL,
            json.dumps(estado, default=str),
        )
    except Exception as e:
        logger.debug(f"[AGEND] state save falhou: {e}")


async def limpar_estado_agendamento(empresa_id: int, conversation_id: int) -> None:
    try:
        await redis_client.delete(_state_key(empresa_id, conversation_id))
    except Exception:
        pass


# ─── PARSE da resposta da IA (extrai tool call) ────────────────────────────

def detectar_tool_call(texto_resposta: str) -> Optional[Dict[str, Any]]:
    """Extrai a primeira tool call do texto da IA, ou None.
    Aceita formato: <TOOL>{"name": "x", "args": {...}}</TOOL>"""
    if not texto_resposta or "<TOOL>" not in texto_resposta:
        return None
    m = _TOOL_RE.search(texto_resposta)
    if not m:
        return None
    raw = m.group(1).strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "name" in parsed:
            parsed.setdefault("args", {})
            return parsed
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"[AGEND] tool_call JSON invalido: {e} | raw={raw[:200]!r}")
    return None


# ─── FORMATADORES de resultado pra IA digerir ──────────────────────────────

_DIAS_PT = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
_MESES_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
             "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _formatar_data_ptbr(activity_date: str, start_time: str = "") -> str:
    """Converte '2026-05-03T00:00:00' + '08:00' em 'domingo, 3 de maio às 08h00'.
    [FIX-J] Calcula dia-da-semana CORRETO (LLM erra calendar) — IA so copia."""
    try:
        from datetime import datetime as _dt
        _data_iso = str(activity_date or "")[:10]
        if not _data_iso or len(_data_iso) < 10:
            return ""
        dt = _dt.fromisoformat(_data_iso)
        dia_semana = _DIAS_PT[dt.weekday()]  # 0=segunda...6=domingo
        mes_nome = _MESES_PT[dt.month - 1]
        base = f"{dia_semana}, {dt.day} de {mes_nome}"
        if start_time:
            hh = str(start_time)[:5].replace(":", "h")
            base += f" às {hh}"
        return base
    except Exception:
        return ""


def _fmt_horarios_para_ia(horarios: list, max_itens: int = 8) -> Dict[str, Any]:
    """Reduz a lista de horarios pra um formato que a IA consome bem
    (max N itens, com numero pro cliente escolher).
    [FIX] Filtra fora itens sem idActivitySession (EVO as vezes retorna null)."""
    horarios_validos = [h for h in horarios if h.get("idActivitySession")]
    selecao = horarios_validos[:max_itens]
    return {
        "total_disponiveis": len(horarios),
        "mostrando": len(selecao),
        "horarios": [
            {
                "numero": i + 1,  # pro cliente escolher por numero
                "id_activity_session": h.get("idActivitySession"),
                "id_activity": h.get("idActivity"),
                "nome_aula": h.get("name"),
                # [PROFESSOR-OFF] instrutor REMOVIDO do payload — cliente nao precisa saber.
                # A IA nao tera o dado e nao mostrara na resposta.
                "data": h.get("activityDate"),  # ISO date (so YYYY-MM-DD)
                "start_time": h.get("startTime"),  # "HH:MM" — usado para montar datetime
                "end_time": h.get("endTime"),
                "horario": f"{h.get('startTime', '')}-{h.get('endTime', '')}",
                # [FIX-J] data ja formatada em PT-BR — IA usa ESTA, nao calcula sozinha
                "data_formatada_ptbr": _formatar_data_ptbr(h.get("activityDate"), h.get("startTime") or ""),
                "vagas_livres": h.get("vagas"),
                "area": h.get("area"),
            }
            for i, h in enumerate(selecao)
        ],
    }


# ─── RESOLVEDOR de unidade ─────────────────────────────────────────────────

async def _resolver_unidade(empresa_id: int, unidade_nome: Optional[str] = None,
                             unidade_id: Optional[int] = None) -> Optional[dict]:
    """Resolve unidade por id ou por nome (busca difusa).
    Retorna dict {id, nome, id_branch_evo} ou None."""
    try:
        import src.core.database as _database
        if not _database.db_pool:
            return None

        # Busca todas as unidades + idBranch da integracao EVO
        rows = await _database.db_pool.fetch(
            """SELECT u.id, u.nome, u.cidade, u.bairro,
                      i.config AS evo_config
               FROM unidades u
               LEFT JOIN integracoes i ON i.unidade_id = u.id
                                       AND i.tipo = 'evo' AND i.ativo = true
               WHERE u.empresa_id = $1 AND u.ativa = true
               ORDER BY u.id""",
            empresa_id,
        )

        unidades_lista = []
        for r in rows:
            cfg = r["evo_config"]
            if isinstance(cfg, str):
                try:
                    cfg = json.loads(cfg)
                except Exception:
                    cfg = {}
            cfg = cfg or {}
            unidades_lista.append({
                "id": r["id"],
                "nome": r["nome"],
                "cidade": r["cidade"],
                "bairro": r["bairro"],
                "id_branch_evo": cfg.get("idBranch"),
            })

        # 1. Match por id direto
        if unidade_id:
            for u in unidades_lista:
                if u["id"] == int(unidade_id):
                    return u

        # 2. Match por nome (difuso — substring case-insensitive normalizado)
        if unidade_nome:
            from src.utils.text_helpers import normalizar
            alvo = normalizar(unidade_nome).strip()
            # Match exato primeiro
            for u in unidades_lista:
                if normalizar(u["nome"]).strip() == alvo:
                    return u
            # Match contains
            for u in unidades_lista:
                nome_norm = normalizar(u["nome"])
                if alvo in nome_norm or any(part and part in nome_norm for part in alvo.split()):
                    return u
            # Match por bairro/cidade
            for u in unidades_lista:
                if alvo in normalizar(u.get("bairro") or "") or alvo in normalizar(u.get("cidade") or ""):
                    return u

        return None
    except Exception as e:
        logger.warning(f"[AGEND] _resolver_unidade erro: {e}")
        return None


async def listar_unidades_resumo(empresa_id: int) -> list:
    """Lista resumida das unidades da empresa pra IA referenciar pelo nome."""
    try:
        import src.core.database as _database
        if not _database.db_pool:
            return []
        rows = await _database.db_pool.fetch(
            "SELECT id, nome, cidade, bairro FROM unidades WHERE empresa_id=$1 AND ativa=true ORDER BY nome",
            empresa_id,
        )
        return [{"id": r["id"], "nome": r["nome"], "cidade": r["cidade"], "bairro": r["bairro"]} for r in rows]
    except Exception:
        return []


# ─── EXECUTOR de tool ──────────────────────────────────────────────────────

async def executar_tool(
    name: str,
    args: Dict[str, Any],
    empresa_id: int,
    conversation_id: int,
    contato_fone: Optional[str],
    pers: Dict[str, Any],
    unidade_id: Optional[int] = None,
    contact_id_chatwoot: Optional[int] = None,
    account_id_chatwoot: Optional[int] = None,
    integracao_chatwoot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Executa uma tool e retorna resultado estruturado.
    pers = dict da personalidade (pra ler config de agendamento).
    Retorna {ok: bool, ...} sempre — IA deve interpretar e responder ao cliente."""

    if not pers.get("agendamento_experimental_ativo"):
        return {"ok": False, "erro": "Agendamento experimental nao esta ativo nesta personalidade."}

    name = (name or "").strip().lower()

    # ── [GUARD ALUNO] Bloqueia consultar_horarios/agendar_aula se contato JA E ALUNO ──
    # Aula experimental e pra prospect — quem ja treina aqui nao precisa.
    if name in ("consultar_horarios", "listar_horarios", "ver_horarios", "agendar_aula", "agendar_experimental", "confirmar_agendamento"):
        if contact_id_chatwoot and account_id_chatwoot and integracao_chatwoot:
            try:
                from src.services.chatwoot_client import listar_labels_contato_chatwoot
                _lbls = await listar_labels_contato_chatwoot(
                    int(account_id_chatwoot), int(contact_id_chatwoot), integracao_chatwoot
                )
                _eh_aluno = any(str(l).lower().startswith("aluno-") for l in (_lbls or []))
                if _eh_aluno:
                    logger.info(f"[AGEND-GUARD] cliente ja e aluno — bloqueia {name}")
                    return {
                        "ok": False,
                        "erro": "ja_e_aluno",
                        "instrucao_ia": (
                            "Este cliente ja e ALUNO da academia — nao oferte aula experimental. "
                            "Responda ao cliente naturalmente que ele ja treina aqui e que aula experimental "
                            "e pra novos prospects. Se quiser experimentar uma modalidade nova ou trazer um amigo, "
                            "pode falar com a unidade. Senao, ofereca ajudar com outra coisa "
                            "(treino, falta, mudanca de plano, segunda via)."
                        ),
                    }
            except Exception as _eg:
                logger.debug(f"[AGEND-GUARD] erro verificar aluno: {_eg}")

    # ─── consultar_horarios ───
    if name in ("consultar_horarios", "listar_horarios", "ver_horarios"):
        dias = int(args.get("dias") or pers.get("agendamento_dias_a_frente") or 5)
        id_acts_raw = pers.get("agendamento_id_activities") or []
        if isinstance(id_acts_raw, str):
            try:
                id_acts_raw = json.loads(id_acts_raw)
            except Exception:
                id_acts_raw = []
        filtro = [int(x) for x in id_acts_raw if str(x).isdigit()] if id_acts_raw else None

        # ─── Resolve unidade (nome ou id) ───
        unidade_nome_arg = args.get("unidade") or args.get("unidade_nome")
        unidade_id_arg = args.get("unidade_id")
        unidade_resolvida = None
        # 1. Tenta args explicitos
        if unidade_nome_arg or unidade_id_arg:
            unidade_resolvida = await _resolver_unidade(
                empresa_id, unidade_nome=unidade_nome_arg, unidade_id=unidade_id_arg
            )
        # 2. Tenta unidade_id da conversa (cenario WhatsApp por unidade)
        if not unidade_resolvida and unidade_id:
            unidade_resolvida = await _resolver_unidade(empresa_id, unidade_id=unidade_id)
        # 3. Tenta unidade do estado da conversa (escolhida em msg anterior)
        if not unidade_resolvida:
            estado_atual = await carregar_estado_agendamento(empresa_id, conversation_id)
            uid_estado = estado_atual.get("unidade_id_escolhida")
            if uid_estado:
                unidade_resolvida = await _resolver_unidade(empresa_id, unidade_id=uid_estado)

        # Se nao tem unidade resolvida, pede pra IA perguntar ao cliente
        if not unidade_resolvida:
            unids = await listar_unidades_resumo(empresa_id)
            return {
                "ok": False,
                "precisa_escolher_unidade": True,
                "unidades_disponiveis": unids,
                "instrucao_ia": (
                    "Antes de consultar horarios, pergunte ao cliente em qual UNIDADE ele quer treinar. "
                    "Lista de opcoes:\n"
                    + "\n".join(f"  • {u['nome']}" + (f" ({u['bairro']})" if u.get('bairro') else "") for u in unids)
                    + "\nDepois que o cliente escolher, chame consultar_horarios de novo passando args.unidade='Nome da Unidade'."
                ),
            }

        # Salva unidade escolhida no estado pra proximas chamadas
        estado_pre = await carregar_estado_agendamento(empresa_id, conversation_id)
        estado_pre["unidade_id_escolhida"] = unidade_resolvida["id"]
        estado_pre["unidade_nome_escolhida"] = unidade_resolvida["nome"]
        estado_pre["id_branch_escolhido"] = unidade_resolvida.get("id_branch_evo")
        await salvar_estado_agendamento(empresa_id, conversation_id, estado_pre)

        # Usa idBranch da unidade resolvida (ou fallback pro da personalidade)
        id_branch = unidade_resolvida.get("id_branch_evo") or pers.get("agendamento_id_branch")

        logger.info(
            f"[AGEND-DEBUG] consultar_horarios empresa={empresa_id} "
            f"unidade={unidade_resolvida['nome']!r} (id={unidade_resolvida['id']}) "
            f"branch={id_branch} dias={dias} filtro_activities={filtro}"
        )
        horarios = await listar_horarios_disponiveis_evo(
            empresa_id=empresa_id,
            unidade_id=unidade_resolvida["id"],
            dias_a_frente=dias,
            id_branch=id_branch,
            filtro_id_activities=filtro,
        )
        logger.info(f"[AGEND-DEBUG] horarios retornados pos-filtros: {len(horarios)}")

        # Salva no estado pra IA poder referenciar por numero depois
        formatado = _fmt_horarios_para_ia(horarios)
        estado = await carregar_estado_agendamento(empresa_id, conversation_id)
        estado["horarios_oferecidos"] = formatado["horarios"]
        estado["etapa"] = "aguardando_escolha"
        await salvar_estado_agendamento(empresa_id, conversation_id, estado)

        if not horarios:
            return {
                "ok": True,
                "vazio": True,
                "mensagem_ia": "Nao ha horarios disponiveis nos proximos dias. Diga ao cliente que vai ver com o time e voltar.",
            }

        return {
            "ok": True,
            "instrucao_ia": (
                "Mostre as opcoes ao cliente de forma natural (max 5-7 horarios). "
                "[CRITICO] Use SEMPRE o campo 'data_formatada_ptbr' EXATAMENTE como veio "
                "(ex: 'domingo, 3 de maio às 08h00'). NUNCA calcule o dia da semana sozinho — "
                "voce sempre erra calendar. Junte: 'data_formatada_ptbr - nome_aula (instrutor)'. "
                "Pergunte qual o cliente prefere. Quando ele escolher (numero ou descricao), "
                "passe `numero` no proximo agendar_aula."
            ),
            **formatado,
        }

    # ─── agendar_aula ───
    if name in ("agendar_aula", "agendar_experimental", "confirmar_agendamento"):
        # 1. Tenta pegar id_activity_session — direto dos args ou do estado
        id_session = args.get("id_activity_session") or args.get("idActivitySession")
        id_activity = args.get("id_activity") or args.get("idActivity")
        activity_name = args.get("activity_name") or args.get("nome_aula")
        activity_date = args.get("activity_date") or args.get("data_hora")
        numero_escolha = args.get("numero")  # cliente escolheu pelo numero

        estado = await carregar_estado_agendamento(empresa_id, conversation_id)
        oferecidos = estado.get("horarios_oferecidos") or []

        # Se IA passou apenas o numero (1,2,3...), resolve via estado
        if numero_escolha and not id_session:
            try:
                idx = int(numero_escolha) - 1
                if 0 <= idx < len(oferecidos):
                    h = oferecidos[idx]
                    id_session = h.get("id_activity_session")
                    id_activity = h.get("id_activity")
                    activity_name = h.get("nome_aula")
                    # [FIX-H] EVO precisa de "yyyy-MM-dd HH:mm" — combina data+start_time.
                    # h["data"] vem como "2026-04-30T00:00:00"; h["start_time"] como "07:00".
                    _data_iso = str(h.get("data") or "")[:10]  # "yyyy-MM-dd"
                    _hora_aula = str(h.get("start_time") or "")[:5]  # "HH:MM"
                    if _data_iso and _hora_aula:
                        activity_date = f"{_data_iso} {_hora_aula}"
                    else:
                        activity_date = h.get("data")  # fallback (vai falhar mas log mostra)
                    # [FIX] Se item escolhido nao tem id_session valido, IA escolheu errado
                    if not id_session:
                        return {
                            "ok": False,
                            "erro": "item_sem_id_session",
                            "instrucao_ia": (
                                f"A opcao numero {numero_escolha} nao pode ser agendada "
                                "(sessao indisponivel na EVO). Sugira ao cliente uma das "
                                "opcoes anteriores que voce ja mostrou (numeros validos)."
                            ),
                        }
                else:
                    # [FIX-J] Se a lista esvaziou (state expirou ou foi limpo), instrucao diferente
                    if len(oferecidos) == 0:
                        return {
                            "ok": False,
                            "erro": "lista_expirou",
                            "instrucao_ia": (
                                "A lista de horarios anterior expirou ou foi invalidada. "
                                "NAO mostre numeros antigos ao cliente. Em vez disso, peca licenca "
                                "e CHAME consultar_horarios DE NOVO pra pegar opcoes atualizadas. "
                                "Depois mostre a nova lista e peca pro cliente escolher."
                            ),
                        }
                    return {
                        "ok": False,
                        "erro": "numero_fora_range",
                        "instrucao_ia": (
                            f"O numero {numero_escolha} nao corresponde a nenhuma das "
                            f"{len(oferecidos)} opcoes mostradas. Confirme com o cliente "
                            f"qual horario ele quer (1 a {len(oferecidos)})."
                        ),
                    }
            except (ValueError, TypeError):
                pass

        # Validacoes
        nome = (args.get("nome") or "").strip()
        telefone = (args.get("telefone") or contato_fone or "").strip()
        email = (args.get("email") or "").strip() or None

        faltando = []
        if not nome:
            faltando.append("nome do cliente")
        if not telefone:
            faltando.append("telefone")
        if pers.get("agendamento_coletar_email") and not email:
            faltando.append("email")
        if not id_session:
            faltando.append("id_activity_session (sessao escolhida)")
        if not activity_date:
            faltando.append("activity_date")
        if not activity_name:
            faltando.append("activity_name")

        if faltando:
            # Salva o que ja tem no estado
            estado["dados_coletados"] = {
                **(estado.get("dados_coletados") or {}),
                **{k: v for k, v in {"nome": nome, "telefone": telefone, "email": email}.items() if v},
            }
            estado["etapa"] = "aguardando_dados"
            await salvar_estado_agendamento(empresa_id, conversation_id, estado)
            return {
                "ok": False,
                "faltando": faltando,
                "instrucao_ia": (
                    f"Para agendar voce precisa pedir ao cliente: {', '.join(faltando)}. "
                    f"Pergunte de forma natural, sem listar tudo de uma vez."
                ),
            }

        # Pega unidade escolhida do estado da conversa (setada no consultar_horarios)
        _u_id_para_agend = unidade_id  # unidade da conversa (se tiver)
        _id_branch_para_agend = pers.get("agendamento_id_branch")  # fallback
        if not _u_id_para_agend:
            _u_id_para_agend = estado.get("unidade_id_escolhida")
            _id_branch_para_agend = estado.get("id_branch_escolhido") or _id_branch_para_agend

        # 2. Cria prospect na EVO (na unidade certa)
        lead_data = {
            "name": nome,
            "email": email,
            "cellphone": telefone,
            "notes": f"Aula experimental via IA — unidade {estado.get('unidade_nome_escolhida') or _u_id_para_agend}",
        }
        id_prospect = await criar_prospect_evo(empresa_id, _u_id_para_agend, lead_data)
        if not id_prospect or id_prospect is True:
            return {
                "ok": False,
                "erro": "Falha ao criar prospect na EVO",
                "instrucao_ia": "Diga ao cliente que houve um erro tecnico e que voce vai pedir pro time entrar em contato.",
            }

        # 3. Agenda a aula (na credencial DA unidade escolhida)
        res = await agendar_aula_experimental_evo(
            empresa_id=empresa_id,
            unidade_id=_u_id_para_agend,
            id_prospect=int(id_prospect),
            activity_date=str(activity_date),
            activity_name=str(activity_name),
            service_name="Aula Experimental",
            id_activity=int(id_activity) if id_activity else None,
            id_service=pers.get("agendamento_id_service"),
            id_branch=_id_branch_para_agend,
            id_activity_session=int(id_session) if id_session else None,  # [FIX-I] pre-check usa id da SESSAO
        )

        if res.get("ok"):
            # Limpa estado da conversa — fluxo completo
            estado["agendamento_concluido"] = {
                "id_prospect": id_prospect,
                "id_activity_session": id_session,
                "activity_date": activity_date,
                "activity_name": activity_name,
            }
            estado["etapa"] = "concluido"
            await salvar_estado_agendamento(empresa_id, conversation_id, estado)
            return {
                "ok": True,
                "id_prospect": id_prospect,
                "instrucao_ia": (
                    f"Confirme com entusiasmo o agendamento da aula '{activity_name}' em {activity_date}. "
                    f"Reforce o que o cliente precisa levar (roupa de treino, garrafa de agua, etc.) "
                    f"e diga que voce esta animado em ve-lo na aula. NAO mencione IDs ou termos tecnicos."
                ),
            }
        else:
            mensagens = res.get("mensagens") or []
            # [FIX-I] Sessao excluida -> limpa horarios oferecidos do estado pra forcar nova consulta
            if res.get("sessao_excluida"):
                estado["horarios_oferecidos"] = []
                estado["etapa"] = "lista_invalidada"
                await salvar_estado_agendamento(empresa_id, conversation_id, estado)
                return {
                    "ok": False,
                    "erro": "sessao_excluida",
                    "mensagens": mensagens,
                    "instrucao_ia": res.get("instrucao_ia") or (
                        "A aula escolhida foi removida da agenda. Peca desculpas e chame "
                        "consultar_horarios de novo pra mostrar a lista atualizada."
                    ),
                }
            return {
                "ok": False,
                "erro": "EVO recusou o agendamento",
                "mensagens": mensagens,
                "instrucao_ia": res.get("instrucao_ia") or (
                    f"O agendamento nao foi feito. Mensagens da EVO: {mensagens}. "
                    f"Peca desculpas ao cliente, sugira outro horario, ou diga que vai escalar pra equipe."
                ),
            }

    # Tool desconhecida
    logger.warning(f"[AGEND] tool desconhecida solicitada: {name}")
    return {
        "ok": False,
        "erro": f"Tool '{name}' nao reconhecida. Disponiveis: consultar_horarios, agendar_aula.",
    }


# ─── BLOCO DE PROMPT que descreve as tools pra IA ──────────────────────────

def construir_bloco_prompt_agendamento(pers: Dict[str, Any]) -> str:
    """Retorna o bloco a ser injetado no system prompt quando agendamento esta ativo."""
    if not pers.get("agendamento_experimental_ativo"):
        return ""

    texto_oferta = (pers.get("agendamento_texto_oferta") or "").strip()
    texto_oferta_bloco = ""
    if texto_oferta:
        texto_oferta_bloco = f'\nFRASE PADRAO PRA OFERECER (use ou adapte): "{texto_oferta}"\n'

    coletar_email = pers.get("agendamento_coletar_email", False)
    dados_min = "nome e telefone"
    if coletar_email:
        dados_min += " e email"

    return f"""[AGENDAMENTO DE AULA EXPERIMENTAL DISPONIVEL]
Voce pode oferecer e agendar uma aula experimental gratuita para o cliente.

QUANDO OFERECER:
- Cliente pergunta sobre planos, valores, ou quer conhecer
- Cliente demonstra interesse em treinar/comecar
- NAO ofereca mais de uma vez na mesma conversa
{texto_oferta_bloco}
COMO USAR AS FERRAMENTAS (TOOLS):
Quando precisar consultar horarios ou agendar, sua resposta deve conter APENAS UM BLOCO assim
(sem texto antes ou depois — o sistema vai processar e voce respondera ao cliente depois):

  <TOOL>{{"name": "consultar_horarios", "args": {{}}}}</TOOL>

ou

  <TOOL>{{"name": "agendar_aula", "args": {{"numero": 2, "nome": "Maria", "telefone": "11987654321"}}}}</TOOL>

FERRAMENTAS DISPONIVEIS:

1. consultar_horarios — lista sessoes disponiveis pros proximos dias.
   Args: {{}} (vazio) ou {{"dias": 5}}
   Use quando o cliente disser que quer experimentar/agendar.

2. agendar_aula — agenda a sessao escolhida pelo cliente.
   Args minimos: {{"numero": N, "nome": "Nome do Cliente", "telefone": "11999999999"}}
   onde N e o numero da opcao na lista de horarios mostrada.
   Email so se necessario: {{"email": "..."}}
   Dados minimos pra agendar: {dados_min}.

FLUXO RECOMENDADO:
1. Cliente quer agendar/conhecer -> ANTES de consultar horarios, pergunte
   em qual UNIDADE ele quer treinar (esta empresa tem MULTIPLAS unidades).
   Liste as unidades pra ele escolher.
2. Cliente escolhe unidade -> use:
   <TOOL>{{"name": "consultar_horarios", "args": {{"unidade": "Nome da Unidade"}}}}</TOOL>
   Use o nome EXATO ou o bairro pra match — sistema resolve.
   Se voce ja chamou uma vez nesta conversa com a unidade escolhida, nao
   precisa passar de novo (ja fica salvo no estado).
3. Sistema retorna a lista, voce mostra ao cliente em texto natural
   (max 5-7 opcoes, com numeracao). Pergunte qual horario ele prefere.
3. Cliente escolhe (ex: "a numero 2" ou "a das 9h").
   Se voce ja tem o nome dele do contexto, va para o passo 5.
   Se nao, pergunte o nome (e telefone se faltar).
4. Quando tiver os dados, use <TOOL>agendar_aula</TOOL> com {{"numero": N, "nome": ..., "telefone": ...}}
5. Sistema retorna sucesso ou erro. Confirme com o cliente em texto natural.

REGRAS IMPORTANTES:
- NUNCA invente horarios ou IDs. Sempre consulte primeiro.
- [CRITICO] DIA DA SEMANA: use SEMPRE o campo 'data_formatada_ptbr' que vem na resposta de
  consultar_horarios. NAO calcule weekday sozinho — voce ERRA. O campo ja vem certo
  (ex: 'domingo, 3 de maio às 08h00'). Copie LITERAL.
- Quando o sistema responder com instrucao_ia, SIGA essa instrucao na sua resposta ao cliente.
- Se faltar dado, peca de forma natural (uma coisa por vez).
- Se o sistema retornar 'lista_expirou' ou 'sessao_excluida', NAO mostre numeros antigos —
  chame consultar_horarios de novo e ofereca a nova lista.
- Se o sistema retornar erro, peca desculpas e sugira tentar outro horario.

[FORMATO OBRIGATORIO DA LISTA DE HORARIOS — NAO QUEBRE ESTA REGRA]
Quando mostrar a lista de horarios pro cliente, o formato eh APENAS:
   • <data_formatada_ptbr> — <nome_aula>
Exemplo correto:
   • quinta-feira, 30 de abril às 18h00 — Funcional
   • quinta-feira, 30 de abril às 19h00 — Mat Pilates

NUNCA INCLUA:
- Nome do professor / instrutor (mesmo se aparecer em algum dado, IGNORE)
- Capacidade ou vagas livres
- Codigos internos (id_activity, id_session, etc)

Mostre SEMPRE com numeracao (1, 2, 3...) pra cliente escolher por numero."""
