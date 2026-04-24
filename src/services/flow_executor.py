"""
flow_executor.py — Engine de execução do fluxo visual de triagem (n8n-style).

Percorre o grafo de nós e executa ações: envia menus, textos, imagens, áudios,
chama IA para classificação/sentimento/qualificação/extração/resposta,
transfere para humano, chama webhooks externos, aguarda input do usuário.

Estado de conversação é salvo em Redis com TTL de 30 minutos.
Variáveis de sessão ({{nome}}, {{produto}}) também são salvas em Redis.
"""

import json
import asyncio
import re
import httpx
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo

from src.core.config import logger
from src.core.redis_client import redis_client, redis_get_json, redis_set_json
from src.services.db_queries import buscar_resposta_faq, carregar_personalidade
from src.services.ia_processor import buscar_cache_semantico

# TTL do estado de fluxo: 30 minutos de inatividade reativa o fluxo do início
FLOW_STATE_TTL = 1800
FLOW_VARS_TTL = 1800
MAX_LOOP_COUNT = 3


# ─────────────────────────────────────────────────────────────
# Utilitários de grafo
# ─────────────────────────────────────────────────────────────

def _find_node(fluxo: Dict, node_id: str) -> Optional[Dict]:
    """Retorna o nó pelo id."""
    for n in fluxo.get("nodes", []):
        if n["id"] == node_id:
            return n
    return None


def _find_node_by_type(fluxo: Dict, node_type: str) -> Optional[Dict]:
    """Retorna o primeiro nó do tipo informado."""
    for n in fluxo.get("nodes", []):
        if n["type"] == node_type:
            return n
    return None


def _get_next_node_id(fluxo: Dict, source_id: str, source_handle: Optional[str] = None) -> Optional[str]:
    """
    Retorna o id do próximo nó conectado a source_id.
    Se source_handle for informado, filtra pela edge com aquele handle.
    """
    for edge in fluxo.get("edges", []):
        if edge["source"] == source_id:
            if source_handle is None or edge.get("sourceHandle") == source_handle:
                return edge["target"]
    return None


def _get_all_next_handles(fluxo: Dict, source_id: str) -> List[Tuple[str, str]]:
    """Retorna lista de (sourceHandle, targetNodeId) para um nó."""
    result = []
    for edge in fluxo.get("edges", []):
        if edge["source"] == source_id:
            result.append((edge.get("sourceHandle", ""), edge["target"]))
    return result


# ─────────────────────────────────────────────────────────────
# Substituição de variáveis {{var}}
# ─────────────────────────────────────────────────────────────

def _render_vars(text: str, vars_dict: Dict) -> str:
    """Substitui {{variavel.nested}} por valores do dicionário de sessão."""
    if not text or not isinstance(text, str):
        return text

    def replacer(m):
        key_path = m.group(1).strip()
        # Suporte básico a dot notation: "user.name"
        parts = key_path.split(".")
        val = vars_dict
        for p in parts:
            if isinstance(val, dict) and p in val:
                val = val[p]
            else:
                return m.group(0) # Retorna o original se não achar
        return str(val)

    # Regex agora aceita pontos e underscores
    return re.sub(r"\{\{([\w\.]+)\}\}", replacer, text)


# ─────────────────────────────────────────────────────────────
# Redis helpers de estado
# ─────────────────────────────────────────────────────────────

async def _get_state(empresa_id: int, phone: str, unidade_id: int = 0) -> Optional[Dict]:
    return await redis_get_json(f"fluxo_state:{empresa_id}:{unidade_id}:{phone}")


async def _set_state(empresa_id: int, phone: str, state: Dict, unidade_id: int = 0):
    await redis_set_json(f"fluxo_state:{empresa_id}:{unidade_id}:{phone}", state, FLOW_STATE_TTL)


async def _clear_state(empresa_id: int, phone: str, unidade_id: int = 0):
    await redis_client.delete(f"fluxo_state:{empresa_id}:{unidade_id}:{phone}")


async def _get_vars(empresa_id: int, phone: str, unidade_id: int = 0) -> Dict:
    v = await redis_get_json(f"fluxo_vars:{empresa_id}:{unidade_id}:{phone}")
    return v if isinstance(v, dict) else {}


async def _set_vars(empresa_id: int, phone: str, vars_dict: Dict, unidade_id: int = 0):
    await redis_set_json(f"fluxo_vars:{empresa_id}:{unidade_id}:{phone}", vars_dict, FLOW_VARS_TTL)


async def _update_var(empresa_id: int, phone: str, key: str, value: Any, unidade_id: int = 0):
    v = await _get_vars(empresa_id, phone, unidade_id)
    v[key] = value
    await _set_vars(empresa_id, phone, v, unidade_id)


# ─────────────────────────────────────────────────────────────
# IA helper (chama LLM diretamente via openai/openrouter)
# ─────────────────────────────────────────────────────────────

async def _call_ia(empresa_id: int, prompt: str, user_message: str, max_tokens: int = 0) -> str:
    """Chama o LLM usando modelo/temperatura/max_tokens da personalidade da empresa."""
    try:
        from src.services.llm_service import cliente_ia
        if not cliente_ia:
            return ""

        pers    = await carregar_personalidade(empresa_id) or {}
        model   = pers.get("modelo_preferido") or "openai/gpt-4o-mini"
        temp    = float(pers.get("temperatura") or 0.7)
        max_tok = max_tokens or int(pers.get("max_tokens") or 500)

        resp = await asyncio.wait_for(
            cliente_ia.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user",   "content": user_message},
                ],
                max_tokens=max_tok,
                temperature=temp,
            ),
            timeout=20,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error(f"[FlowExecutor] Erro IA: {e}")
        return ""


# ─────────────────────────────────────────────────────────────
# Executor principal
# ─────────────────────────────────────────────────────────────

async def executar_fluxo(
    empresa_id: int,
    phone: str,
    mensagem: str,
    fluxo: Dict,
    uaz_client,
    unidade_id: int = 0,
) -> bool:
    """
    Ponto de entrada do executor de fluxo.

    Retorna True se o fluxo tratou a mensagem (não chamar IA padrão).
    Retorna False se o fluxo não está ativo ou não tratou a mensagem.
    """
    if not fluxo or not fluxo.get("ativo"):
        return False

    # ── Normaliza mensagem: o buffer pode entregar JSON '{"text":"oi","files":[]}'
    #    em vez do texto puro — extraímos só o campo "text" nesse caso ──────────
    if isinstance(mensagem, str) and mensagem.strip().startswith("{"):
        try:
            _msg_obj = json.loads(mensagem)
            if isinstance(_msg_obj, dict) and "text" in _msg_obj:
                mensagem = str(_msg_obj["text"]).strip()
        except (ValueError, TypeError):
            pass
    elif not isinstance(mensagem, str):
        mensagem = str(mensagem)

    state = await _get_state(empresa_id, phone, unidade_id)
    session_vars = await _get_vars(empresa_id, phone, unidade_id)

    # Injeta variáveis de contexto automáticas
    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    session_vars.setdefault("phone", phone)
    session_vars.setdefault("hora", agora.strftime("%H:%M"))
    session_vars.setdefault("data", agora.strftime("%d/%m/%Y"))
    session_vars["_unidade_id"] = unidade_id

    if state:
        # Fluxo em andamento — processar resposta do usuário
        logger.info(f"🔄 [FlowExecutor] Continuando fluxo para {phone} no nó {state.get('node_id')}")
        next_node_id = await _process_state(
            state, mensagem, fluxo, empresa_id, phone, session_vars, unidade_id
        )
        if next_node_id is None:
            logger.info(f"⏹️ [FlowExecutor] Nenhuma ramificação para '{mensagem}', encerrando fluxo.")
            await _clear_state(empresa_id, phone, unidade_id)
            return True
        await _execute_from(
            empresa_id, phone, mensagem, fluxo, next_node_id, uaz_client, session_vars, unidade_id=unidade_id
        )
    else:
        # Início do fluxo
        start_node = _find_node_by_type(fluxo, "start")
        if not start_node:
            logger.warning(f"[FlowExecutor] Fluxo sem nó 'start' para empresa {empresa_id}")
            return False
        first_next = _get_next_node_id(fluxo, start_node["id"])
        if not first_next:
            logger.warning(f"[FlowExecutor] Nó 'start' ({start_node['id']}) não está conectado a nada.")
            return False

        logger.info(f"🚀 [FlowExecutor] Iniciando novo fluxo para {phone}")
        await _execute_from(
            empresa_id, phone, mensagem, fluxo, first_next, uaz_client, session_vars, unidade_id=unidade_id
        )

    # Persiste todas as variáveis alteradas durante o processamento/execução
    await _set_vars(empresa_id, phone, session_vars, unidade_id)
    return True


async def _process_state(
    state: Dict,
    mensagem: str,
    fluxo: Dict,
    empresa_id: int,
    phone: str,
    session_vars: Dict,
    unidade_id: int = 0,
) -> Optional[str]:
    """
    Processa a resposta do usuário dado o estado atual do fluxo.
    Retorna o id do próximo nó a executar, ou None se nenhum match.
    """
    node_id = state.get("node_id")
    step = state.get("step", "")
    await _clear_state(empresa_id, phone, unidade_id)

    node = _find_node(fluxo, node_id)
    if not node:
        return None

    node_type = node.get("type", "")

    # ── WaitInput: salva resposta em variável e avança ──
    if node_type == "waitInput":
        var_name = node.get("data", {}).get("variavel", "input")
        await _update_var(empresa_id, phone, var_name, mensagem, unidade_id=unidade_id)
        session_vars[var_name] = mensagem
        return _get_next_node_id(fluxo, node_id)

    # ── setVariable: apenas avança (a lógica é executada no _execute_from) ──
    if node_type == "setVariable":
        return _get_next_node_id(fluxo, node_id)

    # ── getVariable: apenas avança (a lógica é executada no _execute_from) ──
    if node_type == "getVariable":
        return _get_next_node_id(fluxo, node_id)

    # ── generateProtocol: apenas avança (a lógica é executada no _execute_from) ──
    if node_type == "generateProtocol":
        return _get_next_node_id(fluxo, node_id)

    # ── Switch: compara seleção de menu ──
    if node_type == "switch":
        conditions = node.get("data", {}).get("conditions", [])
        msg_lower = mensagem.lower().strip()
        # Strip prefixo de seleção de menu UazAPI ("[Selecionou no menu]: X")
        _PREFIX_MENU = "[selecionou no menu]: "
        if msg_lower.startswith(_PREFIX_MENU):
            msg_lower = msg_lower[len(_PREFIX_MENU):].strip()

        logger.info(f"[Switch] msg_lower='{msg_lower}' | conditions={[(c.get('label',''), c.get('value','')) for c in conditions]}")
        matched_handle = None

        def _save_match(cond: dict) -> str:
            h = cond.get("handle")
            session_vars["last_choice"] = str(cond.get("value", "")).lower().strip()
            session_vars["last_choice_label"] = str(cond.get("label", "")).lower().strip()
            if node.get("data", {}).get("variavel"):
                session_vars[node["data"]["variavel"]] = session_vars["last_choice_label"]
            return h

        for cond in conditions:
            val = str(cond.get("value", "")).lower().strip()
            label = str(cond.get("label", "")).lower().strip()

            # 1. Match exato (valor ou label)
            if msg_lower == val or (label and msg_lower == label):
                matched_handle = _save_match(cond)
                break

            # 2. Suporte a Formato de Lista UazAPI/Chatwoot
            if val and f"({val})" in msg_lower:
                matched_handle = _save_match(cond)
                break
            if label and f"selecao: {label}" in msg_lower:
                matched_handle = _save_match(cond)
                break

            # 3. Match numérico inteligente (ex: "1" em "1 - Opção")
            if msg_lower.isdigit():
                if val == msg_lower:
                    matched_handle = _save_match(cond)
                    break
                if label.startswith(msg_lower):
                    suffix = label[len(msg_lower):]
                    if not suffix or not suffix[0].isdigit():
                        matched_handle = _save_match(cond)
                        break

            # 4. Match de texto por palavra inteira
            if label and len(msg_lower) > 2:
                if re.search(rf"\b{re.escape(msg_lower)}\b", label):
                    matched_handle = _save_match(cond)
                    break
                if len(label) > 3 and label in msg_lower:
                    matched_handle = _save_match(cond)
                    break

        # 5. Fallback: match por posição usando _menu_opcoes salvo no estado
        if not matched_handle:
            menu_opcoes = state.get("_menu_opcoes", [])
            if menu_opcoes and msg_lower:
                for i, titulo in enumerate(menu_opcoes):
                    if titulo.lower().strip() == msg_lower or titulo.lower().strip() in msg_lower:
                        pos_str = str(i + 1)
                        logger.info(f"[Switch] match por posição: '{msg_lower}' = opcao {pos_str} ('{titulo}')")
                        for cond in conditions:
                            val = str(cond.get("value", "")).lower().strip()
                            label = str(cond.get("label", "")).lower().strip()
                            if val == pos_str or label == titulo.lower().strip():
                                matched_handle = _save_match(cond)
                                break
                        if matched_handle:
                            break

        logger.info(f"[Switch] matched_handle={matched_handle}")
        if matched_handle:
            return _get_next_node_id(fluxo, node_id, matched_handle)
        # Nenhum match: volta ao nó de menu para repetir a mensagem
        _menu_src = state.get("_menu_node_id")
        if _menu_src:
            logger.info(f"[Switch] Sem match → repetindo menu nó '{_menu_src}'")
            return _menu_src
        # Sem referência de menu: tenta a primeira saída padrão
        handles = _get_all_next_handles(fluxo, node_id)
        return handles[0][1] if handles else None

    # ── MenuFixoIA: identifica a opção escolhida e salva handle para o _execute_from ──
    if node_type == "menuFixoIA":
        opcoes = node.get("data", {}).get("opcoes", [])
        msg_lower = mensagem.lower().strip()
        _PREFIX_MENU = "[selecionou no menu]: "
        if msg_lower.startswith(_PREFIX_MENU):
            msg_lower = msg_lower[len(_PREFIX_MENU):].strip()

        matched_handle = None
        matched_label = ""
        for i, op in enumerate(opcoes):
            op_id = str(op.get("id", "")).lower().strip()
            op_titulo = str(op.get("titulo", "")).lower().strip()
            if msg_lower == op_id or msg_lower == op_titulo:
                matched_handle = op.get("handle")
                matched_label = op.get("titulo", "")
                break
            if op_titulo and op_titulo in msg_lower:
                matched_handle = op.get("handle")
                matched_label = op.get("titulo", "")
                break
            if msg_lower.isdigit() and int(msg_lower) == i + 1:
                matched_handle = op.get("handle")
                matched_label = op.get("titulo", "")
                break

        if not matched_handle and opcoes:
            matched_handle = opcoes[0].get("handle", "")
            matched_label = opcoes[0].get("titulo", "")

        session_vars["last_choice_label"] = matched_label
        session_vars["_menuFixoIA_handle"] = matched_handle or ""
        return node_id  # re-executa em _execute_from para chamar IA e rotear

    # ── AIMenuDinamicoIA: identifica posição da opção escolhida ──
    if node_type == "aiMenuDinamicoIA":
        generated_options = state.get("generated_options", [])
        msg_lower = mensagem.lower().strip()
        _PREFIX_MENU = "[selecionou no menu]: "
        if msg_lower.startswith(_PREFIX_MENU):
            msg_lower = msg_lower[len(_PREFIX_MENU):].strip()

        matched_pos = 0
        matched_label = ""
        for i, opt in enumerate(generated_options):
            opt_id = str(opt.get("id", "")).lower().strip()
            opt_titulo = str(opt.get("titulo", "")).lower().strip()
            if msg_lower == opt_id or msg_lower == opt_titulo:
                matched_pos = i
                matched_label = opt.get("titulo", "")
                break
            if opt_titulo and opt_titulo in msg_lower:
                matched_pos = i
                matched_label = opt.get("titulo", "")
                break
            if msg_lower.isdigit() and int(msg_lower) == i + 1:
                matched_pos = i
                matched_label = opt.get("titulo", "")
                break

        session_vars["last_choice_label"] = matched_label
        session_vars["_aimenudionamicoIA_pos"] = matched_pos
        return node_id  # re-executa em _execute_from para chamar IA e rotear

    # ── AIClassify: aguarda que a resposta já foi avaliada no nó ──
    if node_type == "aiClassify":
        # A lógica é executada no _execute_from ao chegar neste nó
        return node_id  # re-executa o nó com a mensagem recebida

    # ── AIQualify: fase multi-pergunta ──
    if node_type == "aiQualify":
        data = node.get("data", {})
        perguntas = data.get("perguntas", [])
        variaveis = data.get("variaveis", [])
        step_idx = state.get("qualify_step", 0)
        if step_idx < len(variaveis):
            await _update_var(empresa_id, phone, variaveis[step_idx], mensagem, unidade_id=unidade_id)
            session_vars[variaveis[step_idx]] = mensagem
        next_step = step_idx + 1
        if next_step < len(perguntas):
            # Ainda tem perguntas — salva estado e re-envia próxima pergunta
            return None  # sinaliza que vamos reagendar no _execute_aiqualify
        # Terminou todas as perguntas
        return _get_next_node_id(fluxo, node_id)

    # ── Condição simples ──
    if node_type == "condition":
        data = node.get("data", {})
        pattern = data.get("pattern", "")
        try:
            matched = bool(re.search(pattern, mensagem, re.IGNORECASE)) if pattern else False
        except re.error:
            matched = pattern.lower() in mensagem.lower()
        handles = _get_all_next_handles(fluxo, node_id)
        # handle "sim" = primeiro, "nao" = segundo
        if matched:
            return handles[0][1] if handles else None
        return handles[1][1] if len(handles) > 1 else None

    # ── Search: ramifica baseado no resultado da busca ──
    if node_type == "search":
        # A lógica é executada no _execute_from, aqui apenas avançamos
        return _get_next_node_id(fluxo, node_id)

    # ── SourceFilter: ramifica baseado na origem (privado/grupo) ──
    if node_type == "sourceFilter":
        return _get_next_node_id(fluxo, node_id)

    # ── Redis (DB): apenas avança ──
    if node_type == "redis":
        return _get_next_node_id(fluxo, node_id)

    return _get_next_node_id(fluxo, node_id)


# ─────────────────────────────────────────────────────────────
# Execução de nó
# ─────────────────────────────────────────────────────────────

async def _execute_from(
    empresa_id: int,
    phone: str,
    mensagem: str,
    fluxo: Dict,
    node_id: str,
    uaz_client,
    session_vars: Dict,
    _depth: int = 0,
    unidade_id: int = 0,
):
    """Executa o nó node_id e avança recursivamente pelo grafo."""
    if _depth > 20:
        logger.warning(f"[FlowExecutor] Profundidade máxima atingida para empresa {empresa_id}")
        return

    node = _find_node(fluxo, node_id)
    if not node:
        return

    node_type = node.get("type", "")
    data = node.get("data", {})

    logger.info(f"[FlowExecutor] Executando nó {node_id} tipo={node_type} empresa={empresa_id} phone={phone}")

    # ── Start ──
    if node_type == "start":
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── End ──
    if node_type == "end":
        await _clear_state(empresa_id, phone, unidade_id)
        logger.info(f"[FlowExecutor] Fluxo encerrado para {phone} empresa {empresa_id}")
        return

    # ── GoToMenu: reinicia o fluxo a partir do nó Start ──
    if node_type == "goToMenu":
        await _clear_state(empresa_id, phone, unidade_id)
        logger.info(f"[FlowExecutor] Voltando ao menu inicial para {phone} empresa {empresa_id}")
        start_node = _find_node_by_type(fluxo, "start")
        if start_node:
            first_next = _get_next_node_id(fluxo, start_node["id"])
            if first_next:
                await _execute_from(
                    empresa_id, phone, mensagem, fluxo, first_next,
                    uaz_client, session_vars, _depth + 1, unidade_id=unidade_id,
                )
        return

    # ── SendText ──
    if node_type == "sendText":
        texto = _render_vars(data.get("texto", ""), session_vars)
        if texto:
            await _bot_sent_marker(empresa_id, phone, unidade_id)
            await uaz_client.send_text(phone, texto)
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── SendMenu ──
    if node_type == "sendMenu":
        menu_data = dict(data)
        # Renderiza variáveis no texto e título
        menu_data["texto"] = _render_vars(menu_data.get("texto", ""), session_vars)
        menu_data["titulo"] = _render_vars(menu_data.get("titulo", ""), session_vars)
        await _bot_sent_marker(empresa_id, phone, unidade_id)
        sent = await uaz_client.send_menu(phone, menu_data)
        if sent:
            # Pausa o fluxo: aguarda resposta
            next_id = _get_next_node_id(fluxo, node_id)
            if next_id:
                # Salva as opções do menu para match por posição no switch
                _opcoes_titulos = [op.get("titulo", "") for op in menu_data.get("opcoes", [])]
                await _set_state(empresa_id, phone, {
                    "node_id": next_id,
                    "step": "awaiting_menu_reply",
                    "_menu_opcoes": _opcoes_titulos,
                    "_menu_node_id": node_id,   # permite repetir o menu se o switch não bater
                }, unidade_id=unidade_id)
        return

    # ── SendImage ──
    if node_type == "sendImage":
        url = _render_vars(data.get("url", ""), session_vars)
        caption = _render_vars(data.get("caption", ""), session_vars)
        if url:
            await _bot_sent_marker(empresa_id, phone, unidade_id)
            await uaz_client.send_media(phone, url, media_type="image", caption=caption)
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── SendAudio ──
    if node_type == "sendAudio":
        url = _render_vars(data.get("url", ""), session_vars)
        if url:
            await _bot_sent_marker(empresa_id, phone, unidade_id)
            await uaz_client.send_ptt(phone, url)
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Delay ──
    if node_type == "delay":
        seconds = int(data.get("seconds", 1))
        seconds = max(1, min(seconds, 15))  # limite 15s
        await asyncio.sleep(seconds)
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── WaitInput ──
    if node_type == "waitInput":
        prompt_msg = _render_vars(data.get("prompt", ""), session_vars)
        if prompt_msg:
            await _bot_sent_marker(empresa_id, phone, unidade_id)
            await uaz_client.send_text(phone, prompt_msg)
        await _set_state(empresa_id, phone, {
            "node_id": node_id,
            "step": "awaiting_input",
        }, unidade_id=unidade_id)
        return

    # ── Switch ──
    if node_type == "switch":
        # Ramifica pela mensagem atual
        conditions = data.get("conditions", [])
        msg_lower = mensagem.lower().strip()
        # Strip prefixo de seleção de menu UazAPI ("[Selecionou no menu]: X")
        _PREFIX_MENU = "[selecionou no menu]: "
        if msg_lower.startswith(_PREFIX_MENU):
            msg_lower = msg_lower[len(_PREFIX_MENU):].strip()

        logger.info(f"[Switch/exec] msg_lower='{msg_lower}' | conditions={[(c.get('label',''), c.get('value','')) for c in conditions]}")
        matched_handle = None

        def _sv(cond: dict) -> str:
            h = cond.get("handle")
            session_vars["last_choice"] = str(cond.get("value", "")).lower().strip()
            session_vars["last_choice_label"] = str(cond.get("label", "")).lower().strip()
            if data.get("variavel"):
                session_vars[data["variavel"]] = session_vars["last_choice_label"]
            return h

        for cond in conditions:
            val = str(cond.get("value", "")).lower().strip()
            label = str(cond.get("label", "")).lower().strip()

            # 1. Match exato
            if msg_lower == val or (label and msg_lower == label):
                matched_handle = _sv(cond)
                break

            # 2. Suporte a UazAPI (id) ou "Selecao: label"
            if val and f"({val})" in msg_lower:
                matched_handle = _sv(cond)
                break
            if label and f"selecao: {label}" in msg_lower:
                matched_handle = _sv(cond)
                break

            # 3. Match numérico
            if msg_lower.isdigit():
                if val == msg_lower:
                    matched_handle = _sv(cond)
                    break
                if label.startswith(msg_lower):
                    suffix = label[len(msg_lower):]
                    if not suffix or not suffix[0].isdigit():
                        matched_handle = _sv(cond)
                        break

            # 4. Match de texto (palavra inteira ou label na mensagem)
            if label and len(msg_lower) > 2:
                if re.search(rf"\b{re.escape(msg_lower)}\b", label):
                    matched_handle = _sv(cond)
                    break
                if len(label) > 3 and label in msg_lower:
                    matched_handle = _sv(cond)
                    break

        logger.info(f"[Switch/exec] matched_handle={matched_handle}")
        if matched_handle:
            next_id = _get_next_node_id(fluxo, node_id, matched_handle)
        else:
            handles = _get_all_next_handles(fluxo, node_id)
            next_id = handles[0][1] if handles else None
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Condition ──
    if node_type == "condition":
        pattern = data.get("pattern", "")
        try:
            matched = bool(re.search(pattern, mensagem, re.IGNORECASE)) if pattern else False
        except re.error:
            matched = pattern.lower() in mensagem.lower()
        handles = _get_all_next_handles(fluxo, node_id)
        next_id = handles[0][1] if matched and handles else (handles[1][1] if len(handles) > 1 else None)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── AIRespond ──
    if node_type == "aiRespond":
        prompt_extra = data.get("prompt_extra", "")
        pers = await carregar_personalidade(empresa_id) or {}

        nome        = pers.get("nome_ia") or "Assistente"
        personalid  = pers.get("personalidade") or ""
        instrucoes  = pers.get("instrucoes_base") or ""
        tom_voz     = pers.get("tom_voz") or ""
        usar_emoji  = pers.get("usar_emoji", True)
        objetivos   = pers.get("objetivos_venda") or ""
        idioma      = pers.get("idioma") or "Português"

        partes = [f"Você é {nome}, um assistente virtual."]
        if personalid:  partes.append(f"Personalidade: {personalid}")
        if instrucoes:  partes.append(f"Instruções: {instrucoes}")
        if tom_voz:     partes.append(f"Tom de voz: {tom_voz}")
        if objetivos:   partes.append(f"Objetivos: {objetivos}")
        partes.append(f"Responda sempre em: {idioma}")
        if not usar_emoji:
            partes.append("Não utilize emojis nas respostas.")
        if prompt_extra:
            partes.append(f"INSTRUÇÕES EXTRAS DO FLUXO: {prompt_extra}")

        full_prompt = "\n".join(partes)
        resposta_ia = await _call_ia(empresa_id, full_prompt, mensagem)
        
        if resposta_ia:
            await _bot_sent_marker(empresa_id, phone, unidade_id)
            await uaz_client.send_text_smart(phone, resposta_ia)

        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── AIClassify ──
    if node_type == "aiClassify":
        conditions = data.get("conditions", [])
        labels = [c.get("label", "") for c in conditions]
        if labels:
            prompt = (
                f"Classifique a mensagem do usuário em UMA das seguintes categorias: {', '.join(labels)}.\n"
                f"Responda APENAS com o nome exato da categoria, sem pontuação ou explicação."
            )
            classification = await _call_ia(empresa_id, prompt, mensagem, max_tokens=20)
            classification_lower = classification.lower().strip()
            matched_handle = None
            for cond in conditions:
                if cond.get("label", "").lower() in classification_lower:
                    matched_handle = cond.get("handle")
                    break
            var_name = data.get("variavel", "intencao")
            await _update_var(empresa_id, phone, var_name, classification, unidade_id=unidade_id)
            session_vars[var_name] = classification
            if matched_handle:
                next_id = _get_next_node_id(fluxo, node_id, matched_handle)
                if next_id:
                    await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
                return
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── AISentiment ──
    if node_type == "aiSentiment":
        prompt = (
            "Analise o sentimento da mensagem do usuário.\n"
            "Responda APENAS com uma palavra: 'positivo', 'neutro' ou 'negativo'."
        )
        sentiment = await _call_ia(empresa_id, prompt, mensagem, max_tokens=10)
        sentiment_lower = sentiment.lower().strip()
        var_name = data.get("variavel", "sentimento")
        await _update_var(empresa_id, phone, var_name, sentiment_lower, unidade_id=unidade_id)
        session_vars[var_name] = sentiment_lower

        # Encontra a handle correspondente
        handles = _get_all_next_handles(fluxo, node_id)
        handle_map = {h: t for h, t in handles}
        next_id = (
            handle_map.get("positivo")
            if "positivo" in sentiment_lower
            else handle_map.get("negativo")
            if "negativo" in sentiment_lower
            else handle_map.get("neutro")
        )
        if not next_id and handles:
            next_id = handles[0][1]
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── AIQualify ──
    if node_type == "aiQualify":
        await _execute_aiqualify(empresa_id, phone, mensagem, fluxo, node, uaz_client, session_vars, _depth, unidade_id=unidade_id)
        return

    # ── AIExtract ──
    if node_type == "aiExtract":
        campos = data.get("campos", [])  # [{"label": "nome", "variavel": "nome_lead"}, ...]
        if campos:
            campos_str = ", ".join(f"'{c['label']}'" for c in campos)
            prompt = (
                f"Extraia as seguintes informações da mensagem do usuário: {campos_str}.\n"
                f"Responda em JSON no formato: {{\"nome_campo\": \"valor\"}}.\n"
                f"Se uma informação não estiver presente, use null.\n"
                f"Responda APENAS com o JSON, sem explicações."
            )
            result_raw = await _call_ia(empresa_id, prompt, mensagem, max_tokens=200)
            try:
                extracted = json.loads(result_raw)
                for campo in campos:
                    var = campo.get("variavel", campo.get("label", ""))
                    label = campo.get("label", "")
                    val = extracted.get(label) or extracted.get(var)
                    if val:
                        await _update_var(empresa_id, phone, var, str(val), unidade_id=unidade_id)
                        session_vars[var] = str(val)
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"[FlowExecutor] AIExtract: resposta inválida da IA: {result_raw}")
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── HumanTransfer ──
    if node_type == "humanTransfer":
        mensagem_transfer = _render_vars(
            data.get("mensagem", "Transferindo para um atendente humano. Aguarde!"),
            session_vars
        )
        team_id = data.get("team_id")
        await _bot_sent_marker(empresa_id, phone, unidade_id)
        # Se team_id for informado, podemos passar para o uaz_client (exemplo hipotético de suporte no client)
        if team_id and hasattr(uaz_client, "transfer_to_team"):
            await uaz_client.transfer_to_team(phone, team_id, mensagem_transfer)
        else:
            await uaz_client.send_text(phone, mensagem_transfer)
            
        # Pausa a IA para este contato (usando chave genérica de fone + unidade)
        await redis_client.setex(f"pause_ia_phone:{empresa_id}:{unidade_id}:{phone}", 86400, "1")
        await _clear_state(empresa_id, phone, unidade_id)
        logger.info(f"[FlowExecutor] HumanTransfer: IA pausada para {phone} empresa {empresa_id} (Team {team_id})")
        return

    # ── TransferTeam — atribui conversa a um time do Chatwoot ──────────────
    if node_type == "transferTeam":
        team_id   = data.get("team_id")
        team_name = data.get("team_name", "")
        mensagem_transfer = _render_vars(
            data.get("mensagem", ""),
            session_vars
        )

        if team_id:
            try:
                from src.services.db_queries import carregar_integracao as _ci
                from src.core.database import db_pool as _db_pool

                integ = await _ci(empresa_id, "chatwoot")
                if integ:
                    _url  = (integ.get("url") or integ.get("base_url") or "").rstrip("/")
                    _acc  = integ.get("account_id") or integ.get("accountId")

                    # Extrai token — mesma lógica de extrair_token_chatwoot()
                    _raw_tok = integ.get("token")
                    if isinstance(_raw_tok, dict):
                        _tok = (
                            _raw_tok.get("api_access_token")
                            or _raw_tok.get("api_token")
                            or _raw_tok.get("access_token")
                            or _raw_tok.get("token")
                            or ""
                        )
                    elif _raw_tok:
                        _tok = str(_raw_tok).strip()
                    else:
                        _tok = (
                            integ.get("api_access_token")
                            or integ.get("api_token")
                            or integ.get("access_token")
                            or ""
                        )

                    if _url and _tok and _acc and _db_pool:
                        # Busca o conversation_id ativo deste telefone no banco
                        _conv_row = await _db_pool.fetchrow("""
                            SELECT conversation_id, account_id
                            FROM conversas
                            WHERE empresa_id = $1
                              AND (contato_fone = $2 OR contato_telefone = $2)
                              AND status NOT IN ('encerrada', 'resolved', 'closed')
                            ORDER BY created_at DESC
                            LIMIT 1
                        """, empresa_id, phone)

                        if _conv_row:
                            _cid = _conv_row["conversation_id"]
                            _headers = {"api_access_token": str(_tok)}
                            # Endpoint correto: /assignments com team_id no body
                            _conv_url = f"{_url}/api/v1/accounts/{_acc}/conversations/{_cid}/assignments"
                            async with httpx.AsyncClient(timeout=8.0) as _hc:
                                _r = await _hc.post(
                                    _conv_url,
                                    json={"team_id": int(team_id)},
                                    headers=_headers,
                                )
                            if _r.status_code < 400:
                                logger.info(
                                    f"[FlowExecutor] TransferTeam: conversa {_cid} → time {team_id} ({team_name}) "
                                    f"empresa={empresa_id}"
                                )
                            else:
                                logger.warning(
                                    f"[FlowExecutor] TransferTeam: Chatwoot retornou {_r.status_code} "
                                    f"body={_r.text} para conversa {_cid}"
                                )
            except Exception as _e:
                logger.error(f"[FlowExecutor] TransferTeam erro ao chamar Chatwoot: {_e}")

        # Envia mensagem de aviso se configurada (opcional)
        if mensagem_transfer.strip():
            await _bot_sent_marker(empresa_id, phone, unidade_id)
            await uaz_client.send_text(phone, mensagem_transfer)

        # Continua o fluxo (não pausa a IA — use humanTransfer para isso)
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── BusinessHours — suporta modo "global" (personalidade) e "custom" (inline no nó) ──
    if node_type == "businessHours":
        from src.utils.time_helpers import ia_esta_no_horario
        modo = data.get("modo", "global")

        if modo == "custom" and data.get("horarios"):
            tz_name = data.get("fusoHorario", "America/Sao_Paulo")
            try:
                now = datetime.now(ZoneInfo(tz_name))
            except Exception:
                now = datetime.now(ZoneInfo("America/Sao_Paulo"))
            dia = now.weekday()
            horarios = data.get("horarios", {})
            horario_dia = horarios.get(str(dia), {})
            is_open = False
            if horario_dia.get("ativo"):
                hora_atual = now.strftime("%H:%M")
                hora_inicio = horario_dia.get("inicio", "00:00")
                hora_fim = horario_dia.get("fim", "23:59")
                is_open = hora_inicio <= hora_atual <= hora_fim
        else:
            pers = await carregar_personalidade(empresa_id) or {}
            horario_cfg = pers.get("horario_comercial")
            is_open = ia_esta_no_horario(horario_cfg)

        handle = "aberto" if is_open else "fechado"
        logger.info(f"[FlowExecutor] BusinessHours empresa={empresa_id} modo={modo} → {handle}")
        next_id = _get_next_node_id(fluxo, node_id, source_handle=handle)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        else:
            # [HORA-01] Handle sem conexao — loga WARNING pra admin saber, mas NAO envia
            # mensagem automatica (nao interfere no atendimento humano fora do horario).
            logger.warning(
                f"[FlowExecutor] BusinessHours handle='{handle}' SEM conexao proxima empresa={empresa_id}. "
                f"Se quer comportamento especifico, conecte o handle '{handle}' a um no no editor."
            )
        return

    # ── code (Python Snippet) ──
    if node_type == "code":
        code_str = data.get("code", "")
        # Executa em ambiente restrito
        local_vars = {"vars": session_vars, "mensagem": mensagem, "json": json, "random": __import__("random")}
        try:
            # Padrão: o código deve definir uma variável 'output'
            exec(code_str, {}, local_vars)
            session_vars.update(local_vars.get("vars", {}))
            if "output" in local_vars:
                session_vars["code_output"] = local_vars["output"]
        except Exception as e:
            logger.error(f"[FlowExecutor] Erro no nó Code: {e}")
        
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── setVariable ──
    if node_type == "setVariable":
        key = data.get("chave", "")
        value = _render_vars(data.get("valor", ""), session_vars)
        if key:
            await _update_var(empresa_id, phone, key, value, unidade_id=unidade_id)
            session_vars[key] = value
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── getVariable ──
    if node_type == "getVariable":
        key = data.get("chave", "")
        # A variável já está no session_vars se foi carregada no início do executar_fluxo
        # mas aqui podemos forçar um 'rename' ou apenas garantir que o fluxo continue
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── generateProtocol ──
    if node_type == "generateProtocol":
        import random
        protocolo = str(random.randint(100000, 999999))
        var_name = data.get("variavel", "protocolo")
        await _update_var(empresa_id, phone, var_name, protocolo, unidade_id=unidade_id)
        session_vars[var_name] = protocolo
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── aiMenu (Inovador) ──
    if node_type == "aiMenu":
        await _execute_aimenu(empresa_id, phone, mensagem, fluxo, node, uaz_client, session_vars, _depth, unidade_id=unidade_id)
        return

    # ── Webhook ──
    if node_type == "webhook":
        await _execute_webhook(data, session_vars, empresa_id, phone)
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Search (Busca IA) ──
    if node_type == "search":
        termo = _render_vars(data.get("termo", ""), session_vars)
        if not termo:
            termo = mensagem
        
        # Tenta FAQ (Token Match)
        # Para isso precisamos do slug da unidade se houver.
        # Por enquanto, assumimos busca global ou passamos None se não houver contexto claro.
        slug = session_vars.get("unidade_slug") or "default"
        resultado = await buscar_resposta_faq(termo, slug, empresa_id)
        
        if not resultado:
            # Tenta Cache Semântico (Embedding)
            res_cache = await buscar_cache_semantico(termo, slug, empresa_id)
            if res_cache:
                resultado = res_cache.get("resposta")

        var_name = data.get("variavel", "v_busca")
        matched_handle = "not_found"
        if resultado:
            await _update_var(empresa_id, phone, var_name, resultado, unidade_id=unidade_id)
            session_vars[var_name] = resultado
            matched_handle = "found"
        
        next_id = _get_next_node_id(fluxo, node_id, matched_handle)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Redis (DB) ──
    if node_type == "redis":
        operacao = data.get("operacao", "set")
        chave = _render_vars(data.get("chave", ""), session_vars)
        if chave:
            if operacao == "set":
                valor = _render_vars(data.get("valor", ""), session_vars)
                await redis_client.setex(chave, 86400, valor)
            elif operacao == "get":
                valor = await redis_client.get(chave)
                var_dest = data.get("variavel_destino", "v_redis")
                if valor:
                    await _update_var(empresa_id, phone, var_dest, valor, unidade_id=unidade_id)
                    session_vars[var_dest] = valor
            elif operacao == "del":
                await redis_client.delete(chave)
        
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── SourceFilter (Privado vs Grupo) ──
    if node_type == "sourceFilter":
        # phone geralmente é o número, mas no uazapi para grupos é @g.us
        # Precisamos de algo mais confiável. No uaz_webhook.py passamos o 'phone' extraído.
        # Se contiver '-' ou '@g.us' é grupo.
        is_group = "@g.us" in phone or "-" in phone
        handle = "group" if is_group else "private"
        next_id = _get_next_node_id(fluxo, node_id, handle)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Send Media (Imagem, Vídeo, Documento) ──
    if node_type == "sendMedia":
        url = _render_vars(data.get("url", ""), session_vars)
        if url:
            m_type = data.get("type", "image")
            caption = _render_vars(data.get("caption", ""), session_vars)
            await _bot_sent_marker(empresa_id, phone)
            await uaz_client.send_media(phone, url, m_type, caption=caption, delay=1000)
        
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Loop ──
    if node_type == "loop":
        target_id = data.get("target_node_id")
        if not target_id:
            return
        loop_key = f"fluxo_loop:{empresa_id}:{unidade_id}:{phone}:{node_id}"
        count_raw = await redis_client.get(loop_key)
        count = int(count_raw) if count_raw else 0
        if count >= MAX_LOOP_COUNT:
            # Esgotou tentativas — segue para próximo após o loop
            await redis_client.delete(loop_key)
            next_id = _get_next_node_id(fluxo, node_id)
            if next_id:
                await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        else:
            await redis_client.setex(loop_key, FLOW_STATE_TTL, str(count + 1))
            await _execute_from(empresa_id, phone, mensagem, fluxo, target_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── MenuFixoIA (Menu Fixo + IA Responde) ──
    if node_type == "menuFixoIA":
        selected_handle = session_vars.get("_menuFixoIA_handle")
        if "_menuFixoIA_handle" in session_vars:
            # Segunda fase: IA gera resposta e roteia pelo handle
            instrucaoIA = _render_vars(data.get("instrucaoIA", "Responda de forma personalizada sobre a opção escolhida."), session_vars)
            ia_response = await _call_ia(empresa_id, instrucaoIA, mensagem, max_tokens=300)
            if ia_response:
                await _bot_sent_marker(empresa_id, phone, unidade_id)
                await uaz_client.send_text_smart(phone, ia_response)
            # Limpa flag temporária
            session_vars.pop("_menuFixoIA_handle", None)
            await _set_vars(empresa_id, phone, session_vars, unidade_id)
            next_id = _get_next_node_id(fluxo, node_id, selected_handle) if selected_handle else None
            if not next_id:
                handles = _get_all_next_handles(fluxo, node_id)
                next_id = handles[0][1] if handles else None
            if next_id:
                await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        else:
            # Primeira fase: envia o menu fixo
            opcoes = [{"id": op.get("id", ""), "titulo": op.get("titulo", "")} for op in data.get("opcoes", [])]
            menu_data = {
                "tipo": data.get("tipo", "list"),
                "titulo": _render_vars(data.get("titulo", ""), session_vars),
                "texto": _render_vars(data.get("texto", ""), session_vars),
                "rodape": data.get("rodape", ""),
                "botao": data.get("botao", "Ver opções"),
                "opcoes": opcoes,
            }
            await _bot_sent_marker(empresa_id, phone, unidade_id)
            sent = await uaz_client.send_menu(phone, menu_data)
            if sent:
                await _set_state(empresa_id, phone, {
                    "node_id": node_id,
                    "step": "awaiting_menufixoia",
                }, unidade_id=unidade_id)
        return

    # ── AIMenuDinamicoIA (IA gera menu + IA responde à seleção) ──
    if node_type == "aiMenuDinamicoIA":
        matched_pos = session_vars.get("_aimenudionamicoIA_pos")
        if "_aimenudionamicoIA_pos" in session_vars:
            # Segunda fase: IA gera resposta contextual e roteia por posição
            instrucaoResposta = _render_vars(data.get("instrucaoResposta", "Responda sobre a escolha do usuário: {{last_choice_label}}."), session_vars)
            ia_response = await _call_ia(empresa_id, instrucaoResposta, mensagem, max_tokens=300)
            if ia_response:
                await _bot_sent_marker(empresa_id, phone, unidade_id)
                await uaz_client.send_text_smart(phone, ia_response)
            handle = f"h{int(matched_pos) + 1}"
            session_vars.pop("_aimenudionamicoIA_pos", None)
            await _set_vars(empresa_id, phone, session_vars, unidade_id)
            next_id = _get_next_node_id(fluxo, node_id, handle)
            if not next_id:
                handles = _get_all_next_handles(fluxo, node_id)
                next_id = handles[0][1] if handles else None
            if next_id:
                await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        else:
            # Primeira fase: gera menu dinamicamente com IA
            instrucaoMenu = _render_vars(data.get("instrucaoMenu", "Gere um menu de opções relevante para o usuário."), session_vars)
            opcoes_count = int(data.get("opcoes_count", 3))
            prompt = (
                f"Você é um assistente de atendimento via WhatsApp.\n"
                f"Instrução: {instrucaoMenu}\n"
                f"Mensagem do usuário: {mensagem}\n"
                f"Contexto: {json.dumps(session_vars, ensure_ascii=False)}\n\n"
                f"Gere exatamente {opcoes_count} opções de menu. Responda APENAS com JSON válido:\n"
                f"{{\"texto\": \"...\", \"titulo\": \"...\", \"choices\": [\"Opção Visível|id_curto\", ...]}}"
            )
            result_raw = await _call_ia(empresa_id, prompt, mensagem, max_tokens=400)
            try:
                json_str = result_raw.strip()
                for marker in ("```json", "```"):
                    if marker in json_str:
                        json_str = json_str.split(marker)[1].split("```")[0].strip()
                        break
                menu_config = json.loads(json_str)
                choices_raw = menu_config.get("choices", [])
                opcoes = []
                for choice in choices_raw:
                    if "|" in choice:
                        lbl, cid = choice.split("|", 1)
                        opcoes.append({"titulo": lbl.strip(), "id": cid.strip()})
                    else:
                        opcoes.append({"titulo": choice.strip(), "id": choice.strip().lower().replace(" ", "_")})
                final_menu = {
                    "tipo": "list",
                    "titulo": menu_config.get("titulo", "Opções"),
                    "texto": menu_config.get("texto", "Como posso ajudar?"),
                    "rodape": data.get("rodape", "Powered by IA"),
                    "botao": data.get("botao", "Ver opções"),
                    "opcoes": opcoes,
                }
                await _bot_sent_marker(empresa_id, phone, unidade_id)
                sent = await uaz_client.send_menu(phone, final_menu)
                if sent:
                    await _set_state(empresa_id, phone, {
                        "node_id": node_id,
                        "step": "awaiting_aimenudionamicoIA",
                        "generated_options": opcoes,
                    }, unidade_id=unidade_id)
            except Exception as e:
                logger.error(f"[FlowExecutor] aiMenuDinamicoIA erro ao gerar menu empresa {empresa_id}: {e}")
                next_id = _get_next_node_id(fluxo, node_id)
                if next_id:
                    await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ═════════════════════════════════════════════════════════════
    # NOVOS NOS (Onda 1/2) — expoe recursos UazAPI subutilizados
    # ═════════════════════════════════════════════════════════════

    # ── Send Location (pin no mapa) ──
    if node_type == "sendLocation":
        try:
            latitude = float(_render_vars(str(data.get("latitude", "0")), session_vars))
            longitude = float(_render_vars(str(data.get("longitude", "0")), session_vars))
        except (TypeError, ValueError):
            latitude = longitude = 0.0
        name = _render_vars(data.get("name", ""), session_vars)
        address = _render_vars(data.get("address", ""), session_vars)
        if latitude or longitude:
            await _bot_sent_marker(empresa_id, phone, unidade_id)
            await uaz_client.send_location(phone, latitude, longitude, name=name, address=address)
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Send Contact (vCard) ──
    if node_type == "sendContact":
        contact_name = _render_vars(data.get("contact_name", ""), session_vars)
        contact_phone = _render_vars(data.get("contact_phone", ""), session_vars)
        if contact_name and contact_phone:
            await _bot_sent_marker(empresa_id, phone, unidade_id)
            # send_contact existe no client — assinatura: (number, contact_name, contact_phone)
            try:
                await uaz_client.send_contact(phone, contact_name, contact_phone)
            except AttributeError:
                logger.warning("[FlowExecutor] send_contact nao disponivel no client")
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Send Poll (enquete) ──
    if node_type == "sendPoll":
        pergunta = _render_vars(data.get("pergunta", ""), session_vars)
        opcoes_raw = data.get("opcoes", [])
        # Aceita lista de strings ou lista de dicts
        opcoes = []
        for o in opcoes_raw:
            if isinstance(o, dict):
                opcoes.append(_render_vars(o.get("titulo") or o.get("label") or "", session_vars))
            else:
                opcoes.append(_render_vars(str(o), session_vars))
        opcoes = [o for o in opcoes if o]
        if pergunta and opcoes:
            await _bot_sent_marker(empresa_id, phone, unidade_id)
            try:
                await uaz_client.send_poll(phone, pergunta, opcoes, multi_select=bool(data.get("multi_select", False)))
            except AttributeError:
                # Fallback: usa send_menu tipo poll
                menu_cfg = {"tipo": "poll", "texto": pergunta, "opcoes": [{"titulo": o, "id": o} for o in opcoes]}
                await uaz_client.send_menu(phone, menu_cfg)
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Set Presence (digitando...) ──
    if node_type == "setPresence":
        estado = data.get("estado", "composing")  # composing / recording / paused / available / unavailable
        duracao_ms = int(data.get("duracao_ms", 2000))
        try:
            await uaz_client.set_presence(phone, estado, delay=duracao_ms)
        except AttributeError:
            logger.warning("[FlowExecutor] set_presence nao disponivel no client")
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Send Reaction (emoji a mensagem especifica) ──
    if node_type == "sendReaction":
        # message_id pode vir de: data.message_id (explicit), session_vars (_last_msg_id), ou
        # a mensagem atual do cliente (caso queira reagir a mensagem entrante — precisa estar em vars)
        message_id = _render_vars(data.get("message_id", ""), session_vars) or session_vars.get("_last_msg_id", "")
        emoji = _render_vars(data.get("emoji", "👍"), session_vars)
        if message_id:
            try:
                await uaz_client.send_reaction(phone, message_id, emoji)
            except AttributeError:
                logger.warning("[FlowExecutor] send_reaction nao disponivel no client")
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Edit Message ──
    if node_type == "editMessage":
        message_id = _render_vars(data.get("message_id", ""), session_vars) or session_vars.get("_last_bot_msg_id", "")
        new_text = _render_vars(data.get("new_text", ""), session_vars)
        if message_id and new_text:
            try:
                await uaz_client.edit_message(phone, message_id, new_text)
            except AttributeError:
                logger.warning("[FlowExecutor] edit_message nao disponivel no client")
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Delete Message ──
    if node_type == "deleteMessage":
        message_id = _render_vars(data.get("message_id", ""), session_vars) or session_vars.get("_last_bot_msg_id", "")
        if message_id:
            try:
                await uaz_client.delete_message(phone, message_id)
            except AttributeError:
                logger.warning("[FlowExecutor] delete_message nao disponivel no client")
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Add Label (tag no contato) ──
    if node_type == "addLabel":
        labels_raw = data.get("labels", [])
        if isinstance(labels_raw, str):
            labels = [l.strip() for l in labels_raw.split(",") if l.strip()]
        else:
            labels = [_render_vars(str(l), session_vars) for l in labels_raw if l]
        if labels:
            try:
                await uaz_client.add_label(phone, labels)
            except AttributeError:
                logger.warning("[FlowExecutor] add_label nao disponivel no client")
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Remove Label ──
    if node_type == "removeLabel":
        labels_raw = data.get("labels", [])
        if isinstance(labels_raw, str):
            labels = [l.strip() for l in labels_raw.split(",") if l.strip()]
        else:
            labels = [_render_vars(str(l), session_vars) for l in labels_raw if l]
        if labels:
            try:
                await uaz_client.remove_label(phone, labels)
            except AttributeError:
                logger.warning("[FlowExecutor] remove_label nao disponivel no client")
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Delay humanizado (aleatorio entre min e max segundos) ──
    if node_type == "delayHuman":
        import random as _rand
        min_s = float(data.get("min_seconds", 2))
        max_s = float(data.get("max_seconds", 5))
        # limites de seguranca
        min_s = max(0.5, min(min_s, 20))
        max_s = max(min_s, min(max_s, 30))
        delay = _rand.uniform(min_s, max_s)
        logger.debug(f"[FlowExecutor] delayHuman {delay:.1f}s empresa={empresa_id}")
        # Opcional: mostra "digitando..." durante o delay
        if data.get("show_typing", True):
            try:
                await uaz_client.set_presence(phone, "composing", delay=int(delay * 1000))
            except AttributeError:
                pass
        await asyncio.sleep(delay)
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── A/B Test Split (divide usuarios por percentual) ──
    if node_type == "abTestSplit":
        import hashlib as _hash
        variants = data.get("variants") or [
            {"handle": "a", "weight": 50, "label": "A"},
            {"handle": "b", "weight": 50, "label": "B"},
        ]
        # Hash deterministico do phone para mesma pessoa cair sempre no mesmo bucket
        seed = f"{empresa_id}:{unidade_id}:{phone}:{node_id}"
        h = int(_hash.md5(seed.encode()).hexdigest(), 16) % 10000  # 0..9999
        total_weight = sum(max(1, int(v.get("weight", 1))) for v in variants)
        threshold = 0
        chosen = variants[0]
        for v in variants:
            threshold += int(v.get("weight", 1)) * 10000 // total_weight
            if h <= threshold:
                chosen = v
                break
        chosen_handle = chosen.get("handle", "a")
        # Salva qual variant foi escolhido em sessao (pra tracking/analytics)
        var_name = data.get("variavel", "_ab_variant")
        session_vars[var_name] = chosen.get("label", chosen_handle)
        await _update_var(empresa_id, phone, var_name, chosen.get("label", chosen_handle), unidade_id=unidade_id)
        logger.info(f"[FlowExecutor] abTestSplit empresa={empresa_id} phone={phone} -> variant={chosen_handle}")
        next_id = _get_next_node_id(fluxo, node_id, chosen_handle)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Form Validation (CPF, CNPJ, email, telefone BR) ──
    if node_type == "formValidation":
        import re as _re
        tipo = (data.get("tipo") or "email").lower()  # email/cpf/cnpj/telefone
        valor = _render_vars(data.get("valor", mensagem), session_vars).strip()
        is_valid = False

        if tipo == "email":
            is_valid = bool(_re.match(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", valor))
        elif tipo == "cpf":
            digits = [int(c) for c in valor if c.isdigit()]
            if len(digits) == 11 and len(set(digits)) > 1:
                # Dig verificador 1
                s1 = sum(digits[i] * (10 - i) for i in range(9))
                d1 = (s1 * 10) % 11
                if d1 == 10: d1 = 0
                # Dig verificador 2
                s2 = sum(digits[i] * (11 - i) for i in range(10))
                d2 = (s2 * 10) % 11
                if d2 == 10: d2 = 0
                is_valid = digits[9] == d1 and digits[10] == d2
        elif tipo == "cnpj":
            digits = [int(c) for c in valor if c.isdigit()]
            if len(digits) == 14 and len(set(digits)) > 1:
                w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
                w2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
                s1 = sum(digits[i] * w1[i] for i in range(12))
                d1 = 11 - (s1 % 11)
                if d1 >= 10: d1 = 0
                s2 = sum(digits[i] * w2[i] for i in range(13))
                d2 = 11 - (s2 % 11)
                if d2 >= 10: d2 = 0
                is_valid = digits[12] == d1 and digits[13] == d2
        elif tipo in ("telefone", "phone", "celular"):
            digits = "".join(c for c in valor if c.isdigit())
            # Brasil: 10 (fixo com DDD) ou 11 (celular com DDD) digitos;
            # aceita tambem 12/13 com DDI 55
            if digits.startswith("55") and len(digits) in (12, 13):
                digits = digits[2:]
            is_valid = len(digits) in (10, 11) and digits[2] == "9" if len(digits) == 11 else len(digits) in (10, 11)

        # Salva resultado em variavel (opcional)
        var_out = data.get("variavel_resultado") or "_validation_ok"
        session_vars[var_out] = bool(is_valid)
        await _update_var(empresa_id, phone, var_out, bool(is_valid), unidade_id=unidade_id)

        handle = "valid" if is_valid else "invalid"
        logger.info(f"[FlowExecutor] formValidation tipo={tipo} valor={valor[:40]} -> {handle}")
        next_id = _get_next_node_id(fluxo, node_id, handle)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── Sticky Note (no-op no runtime — so existe no editor) ──
    if node_type == "stickyNote":
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    # ── HTTP Request (no generico — M-1 do backlog) ──
    # Suporta GET/POST/PUT/DELETE/PATCH, headers, auth (bearer/basic), body, e
    # mapeamento de campos da resposta JSON pra variaveis de sessao.
    if node_type == "httpRequest":
        await _execute_http_request(data, session_vars, empresa_id, phone, unidade_id)
        _last_status = int(session_vars.get("_http_last_status", 0) or 0)
        if 200 <= _last_status < 300:
            next_id = _get_next_node_id(fluxo, node_id, "success") or _get_next_node_id(fluxo, node_id)
        else:
            next_id = _get_next_node_id(fluxo, node_id, "error") or _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1, unidade_id=unidade_id)
        return

    logger.warning(f"[FlowExecutor] Tipo de no desconhecido: {node_type}")


# ─────────────────────────────────────────────────────────────
# HTTP Request (no generico — M-1) — generico, novo
# ─────────────────────────────────────────────────────────────

async def _execute_http_request(
    data: Dict,
    session_vars: Dict,
    empresa_id: int,
    phone: str,
    unidade_id: int = 0,
):
    """
    Chamada HTTP genérica:
    - Métodos: GET, POST, PUT, DELETE, PATCH
    - Auth: none / bearer / basic
    - Headers customizáveis
    - Body JSON (dict ou string com {{vars}}) ou form urlencoded
    - Query params com {{vars}}
    - Timeout customizável (default 15s)
    - response_map = {"var_name": "dot.path.in.json"} — salva campos em vars
    Salva em session_vars: _http_last_status, _http_last_body_preview, _http_last_error
    """
    import json as _json

    url = _render_vars(data.get("url", ""), session_vars)
    if not url:
        session_vars["_http_last_status"] = 0
        session_vars["_http_last_error"] = "url_vazia"
        return

    method = str(data.get("method", "GET")).upper()
    timeout_s = float(data.get("timeout", 15.0))

    headers = {}
    for k, v in (data.get("headers") or {}).items():
        headers[str(k)] = _render_vars(str(v), session_vars)

    auth_type = (data.get("auth_type") or "none").lower()
    if auth_type == "bearer":
        token = _render_vars(data.get("auth_token", ""), session_vars)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "basic":
        import base64 as _b64
        user = _render_vars(data.get("auth_user", ""), session_vars)
        pwd = _render_vars(data.get("auth_password", ""), session_vars)
        if user or pwd:
            creds = _b64.b64encode(f"{user}:{pwd}".encode()).decode()
            headers["Authorization"] = f"Basic {creds}"

    params = {}
    for k, v in (data.get("query_params") or {}).items():
        params[str(k)] = _render_vars(str(v), session_vars)

    body_raw = data.get("body")
    rendered_body = None
    body_type = (data.get("body_type") or "json").lower()

    if body_raw is not None and method in {"POST", "PUT", "PATCH", "DELETE"}:
        if isinstance(body_raw, dict):
            rendered_body = {}
            for k, v in body_raw.items():
                if isinstance(v, str):
                    rendered_body[k] = _render_vars(v, session_vars)
                else:
                    rendered_body[k] = v
        elif isinstance(body_raw, str):
            rendered_str = _render_vars(body_raw, session_vars)
            if body_type == "json":
                try:
                    rendered_body = _json.loads(rendered_str) if rendered_str.strip() else None
                except _json.JSONDecodeError:
                    rendered_body = rendered_str
            else:
                rendered_body = rendered_str

    status_code = 0
    body_preview = ""
    parsed_json = None

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            kwargs = {"params": params, "headers": headers}
            if rendered_body is not None:
                if body_type == "form" and isinstance(rendered_body, dict):
                    kwargs["data"] = rendered_body
                elif isinstance(rendered_body, (dict, list)):
                    kwargs["json"] = rendered_body
                else:
                    kwargs["content"] = rendered_body if isinstance(rendered_body, (bytes, str)) else str(rendered_body)
                    lower_headers = {k.lower(): k for k in headers}
                    if "content-type" not in lower_headers:
                        kwargs["headers"]["Content-Type"] = "application/json" if body_type == "json" else "text/plain"

            resp = await client.request(method, url, **kwargs)
            status_code = resp.status_code
            body_preview = resp.text[:500] if resp.text else ""
            try:
                parsed_json = resp.json()
            except Exception:
                parsed_json = None

            logger.info(f"[FlowExecutor] HTTP {method} {url} -> status {status_code} empresa {empresa_id}")

    except httpx.TimeoutException:
        session_vars["_http_last_status"] = 0
        session_vars["_http_last_error"] = "timeout"
        logger.warning(f"[FlowExecutor] HTTP {method} {url} TIMEOUT empresa {empresa_id}")
        return
    except Exception as e:
        session_vars["_http_last_status"] = 0
        session_vars["_http_last_error"] = f"{type(e).__name__}: {str(e)[:200]}"
        logger.error(f"[FlowExecutor] HTTP {method} {url} ERROR empresa {empresa_id}: {e}")
        return

    session_vars["_http_last_status"] = status_code
    session_vars["_http_last_body_preview"] = body_preview
    session_vars.pop("_http_last_error", None)

    response_map = data.get("response_map") or {}
    if parsed_json is not None and isinstance(response_map, dict):
        for var_name, path in response_map.items():
            try:
                value = _extract_dot_path(parsed_json, str(path))
                if value is not None:
                    session_vars[var_name] = value
                    await _update_var(empresa_id, phone, var_name, value, unidade_id=unidade_id)
            except Exception as e:
                logger.debug(f"[FlowExecutor] response_map falhou para {var_name}={path}: {e}")


def _extract_dot_path(obj, path: str):
    """Extrai valor JSON por dot-notation. Ex: 'data.user.name', 'items[0].id'."""
    if not path:
        return obj
    cur = obj
    tokens = []
    for part in path.split("."):
        if "[" in part and part.endswith("]"):
            name, idx_str = part.split("[", 1)
            if name:
                tokens.append(name)
            try:
                tokens.append(int(idx_str.rstrip("]")))
            except ValueError:
                tokens.append(idx_str.rstrip("]"))
        else:
            tokens.append(part)
    for t in tokens:
        if cur is None:
            return None
        if isinstance(t, int) and isinstance(cur, list):
            cur = cur[t] if 0 <= t < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(str(t))
        else:
            return None
    return cur
