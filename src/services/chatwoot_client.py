import asyncio
import re
import hmac
import hashlib
import httpx
from typing import Optional

from src.core.config import logger, PROMETHEUS_OK, METRIC_ERROS_TOTAL, CHATWOOT_WEBHOOK_SECRET
from src.core.redis_client import redis_client
from src.utils.text_helpers import limpar_markdown, primeiro_nome_cliente, nome_eh_valido

# HTTP client — set externally during startup via:
#   import src.services.chatwoot_client as _cw
#   _cw.http_client = httpx.AsyncClient(...)
http_client: httpx.AsyncClient = None


async def simular_digitacao(account_id: int, conversation_id: int, integracao: dict, segundos: float = 2.0):
    """
    Simula tempo de digitação humana com um simples sleep.
    O endpoint REST de typing status do Chatwoot requer WebSocket (ActionCable),
    não funciona via API token — usamos apenas o delay para naturalidade.
    """
    await asyncio.sleep(max(0.5, min(segundos, 6.0)))


def formatar_mensagem_saida(content: str) -> str:
    """Padroniza quebras de linha e espaços para mensagens mais legíveis."""
    txt = limpar_markdown(content or "")
    txt = txt.replace("\r\n", "\n").replace("\r", "\n")
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def suavizar_personalizacao_nome(content: str, nome: Optional[str]) -> str:
    """Evita vocativo artificial repetido e mantém menção natural ao nome."""
    txt = (content or "").strip()
    primeiro = primeiro_nome_cliente(nome)
    if not primeiro or not txt:
        return txt

    linhas = txt.split("\n")
    if linhas and re.fullmatch(rf"{re.escape(primeiro)}[,]?", linhas[0].strip(), flags=re.IGNORECASE):
        linhas = linhas[1:]
        while linhas and not linhas[0].strip():
            linhas = linhas[1:]
        txt = "\n".join(linhas).strip()

    inicio = txt[:120].lower()
    if primeiro.lower() not in inicio:
        txt = f"{primeiro}, {txt}"

    return txt.strip()


async def atualizar_nome_contato_chatwoot(account_id: int, contact_id: int, nome: str, integracao: dict) -> bool:
    """Atualiza nome do contato no Chatwoot quando o nome válido é identificado."""
    if not contact_id or not nome_eh_valido(nome):
        return False
    url_base = integracao.get('url')
    token = integracao.get('token')
    if not url_base or not token:
        return False

    headers = {"api_access_token": token}
    payload = {"name": nome.strip()}
    url = f"{url_base}/api/v1/accounts/{account_id}/contacts/{contact_id}"
    try:
        resp = await http_client.put(url, json=payload, headers=headers, timeout=10.0)
        resp.raise_for_status()
        return True
    except Exception:
        try:
            resp = await http_client.patch(url, json=payload, headers=headers, timeout=10.0)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"Não foi possível atualizar nome do contato {contact_id} no Chatwoot: {e}")
            return False


async def enviar_mensagem_chatwoot(
    account_id: int,
    conversation_id: int,
    content: str,
    nome_ia: str,
    integracao: dict,
    evitar_prefixo_nome: bool = False
):
    url_base = integracao.get('url')
    token = integracao.get('token')
    if not url_base or not token:
        logger.error("Integração Chatwoot incompleta: url ou token ausentes")
        return None

    # Padroniza formatação antes de enviar
    content = formatar_mensagem_saida(content)

    # Personalização natural com nome (sem repetição artificial)
    if not evitar_prefixo_nome:
        try:
            _nome_salvo = await redis_client.get(f"nome_cliente:{conversation_id}")
        except Exception:
            _nome_salvo = None
        content = suavizar_personalizacao_nome(content, _nome_salvo)

    url_m = f"{url_base}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    payload = {
        "content": content,
        "message_type": "outgoing",
        "content_attributes": {
            "origin": "ai",
            "ai_agent": nome_ia,
            "ignore_webhook": True
        }
    }
    headers = {"api_access_token": token}

    try:
        resp = await http_client.post(url_m, json=payload, headers=headers)
        resp.raise_for_status()
        logger.info(f"📤 Mensagem enviada para conversa {conversation_id}")
        return resp
    except httpx.TimeoutException as e:
        logger.error(f"⏱️ Timeout ao enviar mensagem para conversa {conversation_id}: {e}")
        if PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="chatwoot_timeout").inc()
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ HTTP {e.response.status_code} ao enviar para conversa {conversation_id}: {e}")
        if PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="chatwoot_http_error").inc()
        return None
    except httpx.ConnectError as e:
        logger.error(f"🔌 Conexão falhou ao enviar para conversa {conversation_id}: {e}")
        if PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="chatwoot_connect_error").inc()
        return None
    except Exception as e:
        logger.error(f"Erro inesperado ao enviar mensagem para Chatwoot: {e}")
        if PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="chatwoot_unknown").inc()
        return None


async def validar_assinatura(request, signature: str):
    if not CHATWOOT_WEBHOOK_SECRET:
        return
    body = await request.body()
    expected = hmac.new(CHATWOOT_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature or "", expected):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Assinatura inválida")
