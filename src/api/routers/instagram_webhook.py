"""
[MKT-05] Instagram DM webhook — recebe mensagens de Instagram Direct e enfileira no
mesmo Redis Stream que o UazAPI/Chatwoot, reaproveitando todo o pipeline de IA.

Setup no Meta for Developers:
  1. Criar App tipo "Business" no Meta developers
  2. Adicionar produto "Instagram" e "Messenger"
  3. Gerar Page Access Token e pegar o INSTAGRAM_BUSINESS_ACCOUNT_ID
  4. Subscrever webhooks: messages, messaging_postbacks
  5. Configurar URL de callback: https://seu-dominio/webhook/instagram
  6. Verify token deve bater com INSTAGRAM_VERIFY_TOKEN no .env

Envs necessarias:
  INSTAGRAM_VERIFY_TOKEN     — usado na verificacao GET inicial do Meta
  INSTAGRAM_APP_SECRET       — usado para validar assinatura HMAC SHA256
  INSTAGRAM_PAGE_ACCESS_TOKEN — para responder via Graph API

Fluxo:
  1. Meta envia GET de verificacao -> retornamos hub.challenge se verify_token bater
  2. Meta envia POST com mensagem -> validamos HMAC, extraimos texto, enfileiramos no stream
  3. Worker processa (mesmo de WhatsApp) e chama send_instagram_message() para responder
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
import httpx

from src.core.config import logger
from src.core.redis_client import redis_client
from src.services.db_queries import carregar_integracao

router = APIRouter()


INSTAGRAM_VERIFY_TOKEN = os.getenv("INSTAGRAM_VERIFY_TOKEN", "").strip()
INSTAGRAM_APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET", "").strip()
INSTAGRAM_GRAPH_VERSION = os.getenv("INSTAGRAM_GRAPH_VERSION", "v21.0")


# ============================================================
# Verification (GET) — exigida pelo Meta
# ============================================================

@router.get("/webhook/instagram/{empresa_id}")
async def instagram_verify(
    empresa_id: int,
    mode: str = Query(..., alias="hub.mode"),
    token: str = Query(..., alias="hub.verify_token"),
    challenge: str = Query(..., alias="hub.challenge"),
):
    """Endpoint GET chamado pelo Meta para verificar propriedade do webhook."""
    integracao = await carregar_integracao(empresa_id, "instagram")
    expected = (
        (integracao.get("verify_token") if integracao else None)
        or INSTAGRAM_VERIFY_TOKEN
    )

    if mode == "subscribe" and token == expected and expected:
        logger.info(f"[MKT-05] Instagram webhook verificado empresa={empresa_id}")
        # Meta espera o challenge como texto puro
        return int(challenge) if challenge.isdigit() else challenge

    logger.warning(f"[MKT-05] Instagram verify falhou empresa={empresa_id} mode={mode}")
    raise HTTPException(status_code=403, detail="Verification failed")


# ============================================================
# Receive messages (POST)
# ============================================================

def _valid_signature(app_secret: str, body: bytes, header: Optional[str]) -> bool:
    """Valida X-Hub-Signature-256 com comparacao constant-time."""
    if not header or not app_secret:
        return False
    try:
        expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
        received = header.split("=", 1)[-1] if "=" in header else header
        return hmac.compare_digest(expected, received)
    except Exception:
        return False


@router.post("/webhook/instagram/{empresa_id}")
async def instagram_receive(
    empresa_id: int,
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None),
):
    """Recebe eventos do Instagram, valida HMAC e enfileira no Redis Stream."""
    body = await request.body()

    integracao = await carregar_integracao(empresa_id, "instagram")
    if not integracao:
        logger.warning(f"[MKT-05] Sem integracao Instagram para empresa={empresa_id}")
        raise HTTPException(status_code=400, detail="Integracao nao configurada")

    app_secret = (integracao.get("app_secret") or INSTAGRAM_APP_SECRET).strip()
    if not app_secret:
        logger.error(f"[MKT-05] app_secret ausente empresa={empresa_id} — rejeitando fail-closed")
        raise HTTPException(status_code=400, detail="App secret nao configurado")

    if not _valid_signature(app_secret, body, x_hub_signature_256):
        logger.warning(f"[MKT-05] Assinatura invalida empresa={empresa_id}")
        raise HTTPException(status_code=401, detail="Assinatura invalida")

    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored", "reason": "invalid_json"}

    objeto = payload.get("object")
    if objeto not in ("instagram", "page"):
        return {"status": "ignored", "reason": f"object={objeto}"}

    enqueued = 0
    for entry in payload.get("entry", []) or []:
        messaging = entry.get("messaging", []) or []
        for msg in messaging:
            sender = (msg.get("sender") or {}).get("id")
            recipient = (msg.get("recipient") or {}).get("id")
            message = msg.get("message") or {}
            text = (message.get("text") or "").strip()
            attachments = message.get("attachments") or []

            if not sender:
                continue
            if message.get("is_echo"):  # eco da nossa propria resposta
                continue

            # Dedup — ignora msg ja processada
            msg_mid = message.get("mid") or msg.get("timestamp")
            dedup_key = f"dedup:ig:{empresa_id}:{sender}:{msg_mid}"
            try:
                already = await redis_client.set(dedup_key, "1", nx=True, ex=120)
                if not already:
                    continue
            except Exception:
                pass

            # Content — texto ou placeholder se for attachment
            content = text
            has_audio = False
            has_image = False
            media_url = ""

            if not content and attachments:
                att = attachments[0]
                att_type = (att.get("type") or "").lower()
                att_url = (att.get("payload") or {}).get("url") or ""
                media_url = att_url
                if att_type == "image":
                    has_image = True
                    content = "[Imagem recebida]"
                elif att_type == "audio":
                    has_audio = True
                    content = "[Audio recebido]"
                elif att_type == "video":
                    has_image = True  # reutiliza pipeline de imagem
                    content = "[Video recebido]"
                else:
                    content = f"[Anexo: {att_type}]"

            if not content:
                continue

            job_data = {
                "source": "instagram",
                "empresa_id": str(empresa_id),
                "unidade_id": str(integracao.get("unidade_id") or 0),
                "phone": f"ig:{sender}",  # usamos ig:<user_id> para diferenciar de WhatsApp
                "content": content,
                "nome_cliente": "Cliente Instagram",
                "msg_id": str(msg_mid or ""),
                "instance": str(recipient or ""),
                "has_audio": "1" if has_audio else "",
                "audio_url": media_url if has_audio else "",
                "has_image": "1" if has_image else "",
                "image_url": media_url if has_image else "",
            }

            try:
                await redis_client.xadd("ia:webhook:stream", job_data)
                enqueued += 1
            except Exception as e:
                logger.error(f"[MKT-05] xadd falhou: {e}")

    logger.info(f"[MKT-05] Instagram webhook empresa={empresa_id} enqueued={enqueued}")
    return {"status": "ok", "enqueued": enqueued}


# ============================================================
# Send message (usado pelo worker para responder)
# ============================================================

async def send_instagram_message(
    empresa_id: int,
    recipient_id: str,
    text: str,
) -> bool:
    """Envia texto para um IG user via Graph API. Use o id retornado sem prefixo 'ig:'."""
    integracao = await carregar_integracao(empresa_id, "instagram")
    if not integracao:
        logger.error(f"[MKT-05] send sem integracao empresa={empresa_id}")
        return False

    token = integracao.get("page_access_token") or integracao.get("access_token") or ""
    page_id = integracao.get("page_id") or integracao.get("business_account_id") or ""
    if not token or not page_id:
        logger.error(f"[MKT-05] send: token ou page_id ausente empresa={empresa_id}")
        return False

    # Remove prefixo ig: se vier
    rid = recipient_id.removeprefix("ig:")

    url = f"https://graph.facebook.com/{INSTAGRAM_GRAPH_VERSION}/{page_id}/messages"
    payload = {
        "recipient": {"id": rid},
        "message": {"text": text[:1000]},
        "messaging_type": "RESPONSE",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                url,
                params={"access_token": token},
                json=payload,
            )
            if r.status_code >= 400:
                logger.error(f"[MKT-05] send failed {r.status_code}: {r.text[:200]}")
                return False
        return True
    except Exception as e:
        logger.error(f"[MKT-05] send exception: {e}")
        return False
