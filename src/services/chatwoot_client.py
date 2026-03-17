import asyncio
import re
import hmac
import hashlib
import httpx
from typing import Optional, Any

from src.core.config import logger, PROMETHEUS_OK, METRIC_ERROS_TOTAL, CHATWOOT_WEBHOOK_SECRET
from src.core.redis_client import redis_client
from src.utils.text_helpers import limpar_markdown, primeiro_nome_cliente, nome_eh_valido
from src.utils.redis_helper import get_tenant_cache, set_tenant_cache

# HTTP client — set externally during startup
http_client: httpx.AsyncClient = None


async def simular_digitacao(account_id: int, conversation_id: int, integracao: dict, segundos: float = 2.0):
    """
    Simula tempo de digitação humana com um simples sleep.
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
    # Normaliza config (suporta estrutura plana e aninhada legada)
    nested = integracao.get('token') if isinstance(integracao.get('token'), dict) else None
    if nested:
        logger.error("Config Chatwoot aninhado sob 'token' — re-salve a integração no painel")
        url_base = integracao.get('url') or nested.get('url')
        token = nested.get('access_token') or nested.get('token')
    else:
        url_base = integracao.get('url') or integracao.get('base_url')
        token = integracao.get('access_token') or integracao.get('token')
    if not url_base or not token:
        return False

    headers = {"api_access_token": str(token)}
    payload = {"name": nome.strip()}
    url = f"{str(url_base).rstrip('/')}/api/v1/accounts/{account_id}/contacts/{contact_id}"
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
    url_base_ou_integracao: Any, # Aceita URL string ou dict de integração
    empresa_id: int,
    token: str = None,
    contact_id: int = None,
    nome_ia: str = "Assistente",
    evitar_prefixo_nome: bool = False,
    source: str = "chatwoot",
    fone: str = None,
    is_direct_url: bool = False
):
    # Fluxo UazAPI (WhatsApp Direto)
    if source == "uazapi" and fone:
        from src.services.uaz_client import UazAPIClient
        _cfg = url_base_ou_integracao if isinstance(url_base_ou_integracao, dict) else {}
        client = UazAPIClient(
            base_url=_cfg.get("url") or _cfg.get("base_url") or "",
            token=_cfg.get("token") or token or "",
            instance_name=_cfg.get("instance_name") or "lead"
        )
        try:
            # Prefixo de nome sem emoticons
            _prefixed_content = f"*{nome_ia}*\n{content}" if nome_ia else f"{content}"
            
            await set_tenant_cache(empresa_id, f"uaz_bot_sent_conv:{conversation_id}", "1", 120)
            # Chave usada pelo uaz_webhook.py para identificar eco de imagem enviada pelo bot
            await redis_client.setex(f"uaz_bot_sent:{empresa_id}:{fone}", 120, "1")

            if is_direct_url:
                await client.send_media(fone, _prefixed_content, media_type="image")
            else:
                await client.send_text(fone, _prefixed_content)
            return True
        except Exception as e:
            logger.error(f"❌ Erro ao enviar via UAZAPI: {e}")
            return False

    # Fluxo Chatwoot clássico
    if isinstance(url_base_ou_integracao, dict):
        cfg = url_base_ou_integracao
        nested = cfg.get('token') if isinstance(cfg.get('token'), dict) else None
        if nested:
            logger.error("Config Chatwoot aninhado sob 'token' — re-salve a integração no painel")
            url_base = cfg.get('url') or nested.get('url')
            token = nested.get('access_token') or nested.get('token')
        else:
            url_base = cfg.get('url') or cfg.get('base_url')
            token = cfg.get('access_token') or cfg.get('token')
    else:
        url_base = url_base_ou_integracao

    if not url_base or not token:
        logger.error(f"❌ Integ Chatwoot incompleta para emp {empresa_id} conv {conversation_id}: url ou token ausentes")
        return None

    # Normalização de Protocolo (CHATWOOT-V5)
    raw_url = str(url_base).strip()
    if not raw_url.startswith(("http://", "https://")):
        if "." in raw_url:
            url_base = f"https://{raw_url}"
        else:
            logger.error(f"❌ URL Chatwoot inválida: '{raw_url}'")
            return None

    url_m = f"{str(url_base).rstrip('/')}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    
    # Padroniza formatação
    content = formatar_mensagem_saida(content)

    # Personalização com nome
    if not evitar_prefixo_nome:
        _nome_salvo = await get_tenant_cache(empresa_id, f"nome_cliente:{conversation_id}")
        content = suavizar_personalizacao_nome(content, _nome_salvo)

    payload = {
        "content": content,
        "message_type": "outgoing",
        "content_attributes": {
            "origin": "ai",
            "ai_agent": nome_ia,
            "ignore_webhook": True
        }
    }
    if is_direct_url:
        payload["content_attributes"]["external_url"] = content
    # Proteção: garante que token seja string válida
    if isinstance(token, dict):
        logger.error(f"⚠️ Token do Chatwoot chegou como dict — extraindo access_token/token")
        token = token.get('access_token') or token.get('token')
    headers = {"api_access_token": str(token) if token else ""}
    
    logger.info(f"🚀 [CHATWOOT-V5] Postando conv={conversation_id} emp={empresa_id}")

    try:
        resp = await http_client.post(url_m, json=payload, headers=headers, timeout=15.0)
        resp.raise_for_status()
        return resp
    except Exception as e:
        logger.error(f"❌ Erro Chatwoot: {e} | URL: {url_m}")
        if PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="chatwoot_error").inc()
        return None


async def validar_assinatura(request, signature: str):
    if not CHATWOOT_WEBHOOK_SECRET:
        return
    body = await request.body()
    expected = hmac.new(CHATWOOT_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature or "", expected):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Assinatura inválida")
