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

def _fmt_horarios_para_ia(horarios: list, max_itens: int = 8) -> Dict[str, Any]:
    """Reduz a lista de horarios pra um formato que a IA consome bem
    (max N itens, com numero pro cliente escolher)."""
    selecao = horarios[:max_itens]
    return {
        "total_disponiveis": len(horarios),
        "mostrando": len(selecao),
        "horarios": [
            {
                "numero": i + 1,  # pro cliente escolher por numero
                "id_activity_session": h.get("idActivitySession"),
                "id_activity": h.get("idActivity"),
                "nome_aula": h.get("name"),
                "instrutor": h.get("instructor"),
                "data": h.get("activityDate"),
                "horario": f"{h.get('startTime', '')}-{h.get('endTime', '')}",
                "vagas_livres": h.get("vagas"),
                "area": h.get("area"),
            }
            for i, h in enumerate(selecao)
        ],
    }


# ─── EXECUTOR de tool ──────────────────────────────────────────────────────

async def executar_tool(
    name: str,
    args: Dict[str, Any],
    empresa_id: int,
    conversation_id: int,
    contato_fone: Optional[str],
    pers: Dict[str, Any],
    unidade_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Executa uma tool e retorna resultado estruturado.
    pers = dict da personalidade (pra ler config de agendamento).
    Retorna {ok: bool, ...} sempre — IA deve interpretar e responder ao cliente."""

    if not pers.get("agendamento_experimental_ativo"):
        return {"ok": False, "erro": "Agendamento experimental nao esta ativo nesta personalidade."}

    name = (name or "").strip().lower()

    # ─── consultar_horarios ───
    if name in ("consultar_horarios", "listar_horarios", "ver_horarios"):
        dias = int(args.get("dias") or pers.get("agendamento_dias_a_frente") or 5)
        id_branch = pers.get("agendamento_id_branch")
        id_acts_raw = pers.get("agendamento_id_activities") or []
        if isinstance(id_acts_raw, str):
            try:
                id_acts_raw = json.loads(id_acts_raw)
            except Exception:
                id_acts_raw = []
        filtro = [int(x) for x in id_acts_raw if str(x).isdigit()] if id_acts_raw else None

        horarios = await listar_horarios_disponiveis_evo(
            empresa_id=empresa_id,
            unidade_id=unidade_id,
            dias_a_frente=dias,
            id_branch=id_branch,
            filtro_id_activities=filtro,
        )

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
                "Use formato amigavel: 'Quarta 30/04 - 07h Funcional (Maria)'. "
                "Pergunte qual ele prefere. Se ele disser um numero (1, 2, 3...), use a id_activity_session correspondente."
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
                    activity_date = h.get("data")  # formato "yyyy-MM-dd HH:mm"
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

        # 2. Cria prospect na EVO
        lead_data = {
            "name": nome,
            "email": email,
            "cellphone": telefone,
            "notes": "Aula experimental via IA WhatsApp",
        }
        id_prospect = await criar_prospect_evo(empresa_id, unidade_id, lead_data)
        if not id_prospect or id_prospect is True:
            return {
                "ok": False,
                "erro": "Falha ao criar prospect na EVO",
                "instrucao_ia": "Diga ao cliente que houve um erro tecnico e que voce vai pedir pro time entrar em contato.",
            }

        # 3. Agenda a aula
        res = await agendar_aula_experimental_evo(
            empresa_id=empresa_id,
            unidade_id=unidade_id,
            id_prospect=int(id_prospect),
            activity_date=str(activity_date),
            activity_name=str(activity_name),
            service_name="Aula Experimental",
            id_activity=int(id_activity) if id_activity else None,
            id_service=pers.get("agendamento_id_service"),
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
            return {
                "ok": False,
                "erro": "EVO recusou o agendamento",
                "mensagens": mensagens,
                "instrucao_ia": (
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
1. Cliente quer agendar -> use <TOOL>consultar_horarios</TOOL>
2. Sistema retorna a lista, voce mostra ao cliente em texto natural
   (max 5-7 opcoes, com numeracao). Pergunte qual ele prefere.
3. Cliente escolhe (ex: "a numero 2" ou "a das 9h").
   Se voce ja tem o nome dele do contexto, va para o passo 5.
   Se nao, pergunte o nome (e telefone se faltar).
4. Quando tiver os dados, use <TOOL>agendar_aula</TOOL> com {{"numero": N, "nome": ..., "telefone": ...}}
5. Sistema retorna sucesso ou erro. Confirme com o cliente em texto natural.

REGRAS IMPORTANTES:
- NUNCA invente horarios ou IDs. Sempre consulte primeiro.
- Quando o sistema responder com instrucao_ia, SIGA essa instrucao na sua resposta ao cliente.
- Se faltar dado, peca de forma natural (uma coisa por vez).
- Se o sistema retornar erro, pesa desculpas e sugira tentar outro horario."""
