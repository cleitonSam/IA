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
    """Substitui {{variavel}} por valores do dicionário de sessão."""
    if not text:
        return text

    def replacer(m):
        key = m.group(1).strip()
        return str(vars_dict.get(key, m.group(0)))

    return re.sub(r"\{\{(\w+)\}\}", replacer, text)


# ─────────────────────────────────────────────────────────────
# Redis helpers de estado
# ─────────────────────────────────────────────────────────────

async def _get_state(empresa_id: int, phone: str) -> Optional[Dict]:
    return await redis_get_json(f"fluxo_state:{empresa_id}:{phone}")


async def _set_state(empresa_id: int, phone: str, state: Dict):
    await redis_set_json(f"fluxo_state:{empresa_id}:{phone}", state, FLOW_STATE_TTL)


async def _clear_state(empresa_id: int, phone: str):
    await redis_client.delete(f"fluxo_state:{empresa_id}:{phone}")


async def _get_vars(empresa_id: int, phone: str) -> Dict:
    v = await redis_get_json(f"fluxo_vars:{empresa_id}:{phone}")
    return v if isinstance(v, dict) else {}


async def _set_vars(empresa_id: int, phone: str, vars_dict: Dict):
    await redis_set_json(f"fluxo_vars:{empresa_id}:{phone}", vars_dict, FLOW_VARS_TTL)


async def _update_var(empresa_id: int, phone: str, key: str, value: Any):
    v = await _get_vars(empresa_id, phone)
    v[key] = value
    await _set_vars(empresa_id, phone, v)


# ─────────────────────────────────────────────────────────────
# IA helper (chama LLM diretamente via openai/openrouter)
# ─────────────────────────────────────────────────────────────

async def _call_ia(prompt: str, user_message: str, max_tokens: int = 150) -> str:
    """Chama o LLM com um prompt simples e retorna texto."""
    try:
        from src.services.llm_service import cliente_ia
        from src.core.config import MODEL_NAME_PADRAO
        if not cliente_ia:
            return ""
        resp = await asyncio.wait_for(
            cliente_ia.chat.completions.create(
                model=MODEL_NAME_PADRAO or "openai/gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user",   "content": user_message},
                ],
                max_tokens=max_tokens,
                temperature=0.3,
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
) -> bool:
    """
    Ponto de entrada do executor de fluxo.

    Retorna True se o fluxo tratou a mensagem (não chamar IA padrão).
    Retorna False se o fluxo não está ativo ou não tratou a mensagem.
    """
    if not fluxo or not fluxo.get("ativo"):
        return False

    state = await _get_state(empresa_id, phone)
    session_vars = await _get_vars(empresa_id, phone)

    # Injeta variáveis de contexto automáticas
    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    session_vars.setdefault("phone", phone)
    session_vars.setdefault("hora", agora.strftime("%H:%M"))
    session_vars.setdefault("data", agora.strftime("%d/%m/%Y"))

    if state:
        # Fluxo em andamento — processar resposta do usuário
        next_node_id = await _process_state(
            state, mensagem, fluxo, empresa_id, phone, session_vars
        )
        if next_node_id is None:
            # Nenhuma ramificação correspondente — encerra
            await _clear_state(empresa_id, phone)
            return True
        await _execute_from(
            empresa_id, phone, mensagem, fluxo, next_node_id, uaz_client, session_vars
        )
    else:
        # Início do fluxo
        start_node = _find_node_by_type(fluxo, "start")
        if not start_node:
            logger.warning(f"[FlowExecutor] Fluxo sem nó 'start' para empresa {empresa_id}")
            return False
        first_next = _get_next_node_id(fluxo, start_node["id"])
        if not first_next:
            return False
        await _execute_from(
            empresa_id, phone, mensagem, fluxo, first_next, uaz_client, session_vars
        )

    return True


async def _process_state(
    state: Dict,
    mensagem: str,
    fluxo: Dict,
    empresa_id: int,
    phone: str,
    session_vars: Dict,
) -> Optional[str]:
    """
    Processa a resposta do usuário dado o estado atual do fluxo.
    Retorna o id do próximo nó a executar, ou None se nenhum match.
    """
    node_id = state.get("node_id")
    step = state.get("step", "")
    await _clear_state(empresa_id, phone)

    node = _find_node(fluxo, node_id)
    if not node:
        return None

    node_type = node.get("type", "")

    # ── WaitInput: salva resposta em variável e avança ──
    if node_type == "waitInput":
        var_name = node.get("data", {}).get("variavel", "input")
        await _update_var(empresa_id, phone, var_name, mensagem)
        session_vars[var_name] = mensagem
        return _get_next_node_id(fluxo, node_id)

    # ── Switch: compara seleção de menu ──
    if node_type == "switch":
        conditions = node.get("data", {}).get("conditions", [])
        msg_lower = mensagem.lower().strip()
        # Tenta por value (ID da opção) e por label
        for cond in conditions:
            val = str(cond.get("value", "")).lower()
            label = str(cond.get("label", "")).lower()
            if msg_lower == val or msg_lower in label or label in msg_lower:
                return _get_next_node_id(fluxo, node_id, cond.get("handle"))
        # Nenhum match: tenta a primeira saída padrão
        handles = _get_all_next_handles(fluxo, node_id)
        return handles[0][1] if handles else None

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
            await _update_var(empresa_id, phone, variaveis[step_idx], mensagem)
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
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1)
        return

    # ── End ──
    if node_type == "end":
        await _clear_state(empresa_id, phone)
        logger.info(f"[FlowExecutor] Fluxo encerrado para {phone} empresa {empresa_id}")
        return

    # ── SendText ──
    if node_type == "sendText":
        texto = _render_vars(data.get("texto", ""), session_vars)
        if texto:
            await _bot_sent_marker(empresa_id, phone)
            await uaz_client.send_text(phone, texto)
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1)
        return

    # ── SendMenu ──
    if node_type == "sendMenu":
        menu_data = dict(data)
        # Renderiza variáveis no texto e título
        menu_data["texto"] = _render_vars(menu_data.get("texto", ""), session_vars)
        menu_data["titulo"] = _render_vars(menu_data.get("titulo", ""), session_vars)
        await _bot_sent_marker(empresa_id, phone)
        sent = await uaz_client.send_menu(phone, menu_data)
        if sent:
            # Pausa o fluxo: aguarda resposta
            next_id = _get_next_node_id(fluxo, node_id)
            if next_id:
                await _set_state(empresa_id, phone, {
                    "node_id": next_id,
                    "step": "awaiting_menu_reply",
                })
        return

    # ── SendImage ──
    if node_type == "sendImage":
        url = _render_vars(data.get("url", ""), session_vars)
        caption = _render_vars(data.get("caption", ""), session_vars)
        if url:
            await _bot_sent_marker(empresa_id, phone)
            await uaz_client.send_media(phone, url, caption, media_type="image")
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1)
        return

    # ── SendAudio ──
    if node_type == "sendAudio":
        url = _render_vars(data.get("url", ""), session_vars)
        if url:
            await _bot_sent_marker(empresa_id, phone)
            await uaz_client.send_ptt(phone, url)
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1)
        return

    # ── Delay ──
    if node_type == "delay":
        seconds = int(data.get("seconds", 1))
        seconds = max(1, min(seconds, 15))  # limite 15s
        await asyncio.sleep(seconds)
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1)
        return

    # ── WaitInput ──
    if node_type == "waitInput":
        prompt_msg = _render_vars(data.get("prompt", ""), session_vars)
        if prompt_msg:
            await _bot_sent_marker(empresa_id, phone)
            await uaz_client.send_text(phone, prompt_msg)
        await _set_state(empresa_id, phone, {
            "node_id": node_id,
            "step": "awaiting_input",
        })
        return

    # ── Switch ──
    if node_type == "switch":
        # Ramifica pela mensagem atual
        conditions = data.get("conditions", [])
        msg_lower = mensagem.lower().strip()
        matched_handle = None
        for cond in conditions:
            val = str(cond.get("value", "")).lower()
            label = str(cond.get("label", "")).lower()
            if msg_lower == val or msg_lower in label or label in msg_lower:
                matched_handle = cond.get("handle")
                break
        if matched_handle:
            next_id = _get_next_node_id(fluxo, node_id, matched_handle)
        else:
            handles = _get_all_next_handles(fluxo, node_id)
            next_id = handles[0][1] if handles else None
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1)
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
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1)
        return

    # ── AIRespond ──
    if node_type == "aiRespond":
        # Delega ao bot_core via redis pub/sub para usar todo o pipeline de IA
        prompt_extra = data.get("prompt_extra", "")
        await redis_client.publish(
            f"flow:ai_respond:{empresa_id}:{phone}",
            json.dumps({"prompt_extra": prompt_extra, "mensagem": mensagem})
        )
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1)
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
            classification = await _call_ia(prompt, mensagem, max_tokens=20)
            classification_lower = classification.lower().strip()
            matched_handle = None
            for cond in conditions:
                if cond.get("label", "").lower() in classification_lower:
                    matched_handle = cond.get("handle")
                    break
            var_name = data.get("variavel", "intencao")
            await _update_var(empresa_id, phone, var_name, classification)
            session_vars[var_name] = classification
            if matched_handle:
                next_id = _get_next_node_id(fluxo, node_id, matched_handle)
                if next_id:
                    await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1)
                return
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1)
        return

    # ── AISentiment ──
    if node_type == "aiSentiment":
        prompt = (
            "Analise o sentimento da mensagem do usuário.\n"
            "Responda APENAS com uma palavra: 'positivo', 'neutro' ou 'negativo'."
        )
        sentiment = await _call_ia(prompt, mensagem, max_tokens=10)
        sentiment_lower = sentiment.lower().strip()
        var_name = data.get("variavel", "sentimento")
        await _update_var(empresa_id, phone, var_name, sentiment_lower)
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
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1)
        return

    # ── AIQualify ──
    if node_type == "aiQualify":
        await _execute_aiqualify(empresa_id, phone, mensagem, fluxo, node, uaz_client, session_vars, _depth)
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
            result_raw = await _call_ia(prompt, mensagem, max_tokens=200)
            try:
                extracted = json.loads(result_raw)
                for campo in campos:
                    var = campo.get("variavel", campo.get("label", ""))
                    label = campo.get("label", "")
                    val = extracted.get(label) or extracted.get(var)
                    if val:
                        await _update_var(empresa_id, phone, var, str(val))
                        session_vars[var] = str(val)
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"[FlowExecutor] AIExtract: resposta inválida da IA: {result_raw}")
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1)
        return

    # ── HumanTransfer ──
    if node_type == "humanTransfer":
        mensagem_transfer = _render_vars(
            data.get("mensagem", "Transferindo para um atendente humano. Aguarde!"),
            session_vars
        )
        await _bot_sent_marker(empresa_id, phone)
        await uaz_client.send_text(phone, mensagem_transfer)
        # Pausa a IA para este contato (usando chave genérica de fone)
        await redis_client.setex(f"pause_ia_phone:{empresa_id}:{phone}", 86400, "1")
        await _clear_state(empresa_id, phone)
        logger.info(f"[FlowExecutor] HumanTransfer: IA pausada para {phone} empresa {empresa_id}")
        return

    # ── Webhook ──
    if node_type == "webhook":
        await _execute_webhook(data, session_vars, empresa_id, phone)
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1)
        return

    # ── Loop ──
    if node_type == "loop":
        target_id = data.get("target_node_id")
        if not target_id:
            return
        loop_key = f"fluxo_loop:{empresa_id}:{phone}:{node_id}"
        count_raw = await redis_client.get(loop_key)
        count = int(count_raw) if count_raw else 0
        if count >= MAX_LOOP_COUNT:
            # Esgotou tentativas — segue para próximo após o loop
            await redis_client.delete(loop_key)
            next_id = _get_next_node_id(fluxo, node_id)
            if next_id:
                await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1)
        else:
            await redis_client.setex(loop_key, FLOW_STATE_TTL, str(count + 1))
            await _execute_from(empresa_id, phone, mensagem, fluxo, target_id, uaz_client, session_vars, _depth + 1)
        return

    logger.warning(f"[FlowExecutor] Tipo de nó desconhecido: {node_type}")


# ─────────────────────────────────────────────────────────────
# AIQualify — fluxo de qualificação multi-pergunta
# ─────────────────────────────────────────────────────────────

async def _execute_aiqualify(
    empresa_id: int,
    phone: str,
    mensagem: str,
    fluxo: Dict,
    node: Dict,
    uaz_client,
    session_vars: Dict,
    _depth: int,
):
    """Gerencia o fluxo de perguntas sequenciais do AIQualify."""
    node_id = node["id"]
    data = node.get("data", {})
    perguntas = data.get("perguntas", [])
    variaveis = data.get("variaveis", [])

    state = await _get_state(empresa_id, phone)
    step_idx = state.get("qualify_step", 0) if state else 0

    if step_idx < len(perguntas):
        pergunta = _render_vars(perguntas[step_idx], session_vars)
        await _bot_sent_marker(empresa_id, phone)
        await uaz_client.send_text(phone, pergunta)
        await _set_state(empresa_id, phone, {
            "node_id": node_id,
            "step": "awaiting_qualify",
            "qualify_step": step_idx + 1,
        })
    else:
        # Todas as perguntas foram respondidas
        next_id = _get_next_node_id(fluxo, node_id)
        if next_id:
            await _execute_from(empresa_id, phone, mensagem, fluxo, next_id, uaz_client, session_vars, _depth + 1)


# ─────────────────────────────────────────────────────────────
# Webhook externo
# ─────────────────────────────────────────────────────────────

async def _execute_webhook(data: Dict, session_vars: Dict, empresa_id: int, phone: str):
    """Chama uma URL externa com dados da sessão."""
    url = data.get("url", "")
    method = data.get("method", "POST").upper()
    body_template = data.get("body", {})

    if not url:
        return

    # Renderiza variáveis no body
    rendered_body = {}
    for k, v in body_template.items():
        rendered_body[k] = _render_vars(str(v), session_vars)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if method == "GET":
                resp = await client.get(url, params=rendered_body)
            else:
                resp = await client.post(url, json=rendered_body)
            logger.info(f"[FlowExecutor] Webhook {method} {url} → status {resp.status_code} empresa {empresa_id}")
    except Exception as e:
        logger.error(f"[FlowExecutor] Webhook error para empresa {empresa_id}: {e}")


# ─────────────────────────────────────────────────────────────
# Marker de bot (evita fromMe echo no UazAPI)
# ─────────────────────────────────────────────────────────────

async def _bot_sent_marker(empresa_id: int, phone: str):
    """Marca que o próximo fromMe é do bot (não do atendente humano)."""
    await redis_client.setex(f"uaz_bot_sent:{empresa_id}:{phone}", 30, "1")
