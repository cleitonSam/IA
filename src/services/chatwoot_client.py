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


def _chatwoot_url_token(integracao: dict):
    """Extrai (url_base, token) do dict de integracao Chatwoot — suporta legado aninhado."""
    if not isinstance(integracao, dict):
        return None, None
    nested = integracao.get('token') if isinstance(integracao.get('token'), dict) else None
    if nested:
        url_base = integracao.get('url') or nested.get('url')
        token = nested.get('access_token') or nested.get('token')
    else:
        url_base = integracao.get('url') or integracao.get('base_url')
        token = integracao.get('access_token') or integracao.get('token')
    if isinstance(token, dict):
        token = token.get('access_token') or token.get('token')
    return (str(url_base).rstrip('/') if url_base else None, str(token) if token else None)


async def listar_labels_contato_chatwoot(account_id: int, contact_id: int, integracao: dict) -> list:
    """Retorna a lista de label slugs aplicadas ao CONTATO no Chatwoot.
    Cache curto (60s) pra reduzir round-trips quando o bot consulta repetidamente."""
    if not contact_id or not account_id:
        return []
    url_base, token = _chatwoot_url_token(integracao)
    if not url_base or not token:
        return []
    try:
        from src.core.redis_client import redis_client as _rc
        _ck = f"cw:labels:contact:{account_id}:{contact_id}"
        _cached = await _rc.get(_ck)
        if _cached:
            try:
                import json as _j
                return _j.loads(_cached)
            except Exception:
                pass
    except Exception:
        _rc = None
        _ck = None

    headers = {"api_access_token": str(token)}
    url = f"{url_base}/api/v1/accounts/{account_id}/contacts/{contact_id}/labels"
    try:
        resp = await http_client.get(url, headers=headers, timeout=10.0)
        if resp.status_code != 200:
            return []
        data = resp.json() or {}
        # Chatwoot retorna {payload: ["aluno-saude", ...]} ou {data: {payload: [...]}}
        payload = data.get("payload") if isinstance(data, dict) else None
        if payload is None and isinstance(data.get("data"), dict):
            payload = data["data"].get("payload")
        labels = payload if isinstance(payload, list) else []
        if _rc and _ck:
            try:
                import json as _j
                await _rc.setex(_ck, 60, _j.dumps(labels))
            except Exception:
                pass
        return labels
    except Exception as e:
        logger.warning(f"[CW labels] erro listar contato {contact_id}: {e}")
        return []


async def garantir_label_existe_chatwoot(
    account_id: int, label_slug: str, integracao: dict,
    color: str = "#10b981", description: str = "",
) -> bool:
    """Cria a label no Chatwoot se ainda não existir (idempotente).
    Necessario porque algumas versoes do Chatwoot nao auto-criam labels via /contacts/{id}/labels."""
    url_base, token = _chatwoot_url_token(integracao)
    if not url_base or not token or not account_id or not label_slug:
        return False
    headers = {"api_access_token": str(token), "Content-Type": "application/json"}
    label_slug = str(label_slug).strip().lower()

    # Lista existentes
    try:
        resp_list = await http_client.get(
            f"{url_base}/api/v1/accounts/{account_id}/labels",
            headers={"api_access_token": str(token)},
            timeout=10.0,
        )
        if resp_list.status_code == 200:
            data = resp_list.json() or {}
            payload = data.get("payload") if isinstance(data, dict) else None
            if payload is None and isinstance(data.get("data"), dict):
                payload = data["data"].get("payload")
            existentes = {str(l.get("title", "")).lower() for l in (payload or []) if isinstance(l, dict)}
            if label_slug in existentes:
                return True  # ja existe
    except Exception as e:
        logger.debug(f"[CW labels] erro listar pra garantir: {e}")

    # Cria
    try:
        resp = await http_client.post(
            f"{url_base}/api/v1/accounts/{account_id}/labels",
            json={"title": label_slug, "color": color, "description": description, "show_on_sidebar": True},
            headers=headers,
            timeout=10.0,
        )
        if 200 <= resp.status_code < 300:
            logger.info(f"[CW labels] label '{label_slug}' criada (HTTP {resp.status_code})")
            return True
        logger.warning(f"[CW labels] erro criar label '{label_slug}': HTTP {resp.status_code} {resp.text[:200]}")
        return False
    except Exception as e:
        logger.warning(f"[CW labels] excecao criar label '{label_slug}': {e}")
        return False


async def aplicar_label_contato_chatwoot(
    account_id: int, contact_id: int, label_slug: str, integracao: dict,
    grupo_prefix: str = "aluno-",
) -> bool:
    """Adiciona uma label ao contato no Chatwoot (idempotente).
    O endpoint POST /contacts/{id}/labels SUBSTITUI a lista — entao buscamos primeiro
    a lista atual, juntamos com a nova, e mandamos o conjunto completo.
    Se grupo_prefix passado, REMOVE labels antigas que comecam com esse prefixo
    (ex: cliente mudou de unidade -> remove aluno-saude antiga, aplica aluno-altino).
    [BLINDADO] Garante que a label EXISTE na conta antes de aplicar."""
    if not contact_id or not account_id or not label_slug:
        return False
    url_base, token = _chatwoot_url_token(integracao)
    if not url_base or not token:
        return False

    label_slug = str(label_slug).strip().lower()
    if not label_slug:
        return False

    # [BLINDAGEM] Garante que a label existe na conta — algumas versoes do Chatwoot
    # nao auto-criam quando aplicadas via POST /contacts/{id}/labels.
    await garantir_label_existe_chatwoot(account_id, label_slug, integracao)

    atuais = await listar_labels_contato_chatwoot(account_id, contact_id, integracao)
    # Remove qualquer label do mesmo grupo (ex: aluno-*) — substitui pela nova
    if grupo_prefix:
        atuais = [l for l in atuais if not str(l).lower().startswith(grupo_prefix.lower())]
    if label_slug in atuais:
        # Ja tinha exatamente esta — nada a fazer (e nao removemos do mesmo grupo)
        # Reaplica pra ter certeza
        pass
    novas = list(atuais) + [label_slug]

    headers = {"api_access_token": str(token), "Content-Type": "application/json"}
    url = f"{url_base}/api/v1/accounts/{account_id}/contacts/{contact_id}/labels"
    try:
        resp = await http_client.post(url, json={"labels": novas}, headers=headers, timeout=10.0)
        if 200 <= resp.status_code < 300:
            # Invalida cache de labels
            try:
                from src.core.redis_client import redis_client as _rc
                await _rc.delete(f"cw:labels:contact:{account_id}:{contact_id}")
            except Exception:
                pass
            logger.info(f"[CW labels] '{label_slug}' aplicada contato={contact_id} acc={account_id}")
            return True
        logger.warning(f"[CW labels] HTTP {resp.status_code} aplicar {label_slug}: {resp.text[:200]}")
        return False
    except Exception as e:
        logger.warning(f"[CW labels] erro aplicar {label_slug} contato {contact_id}: {e}")
        return False


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


# ── Extensões de arquivo por tipo de mídia ──────────────────────────────────
_EXT_VIDEO    = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".3gp", ".m4v"}
_EXT_AUDIO    = {".ogg", ".mp3", ".wav", ".aac", ".m4a", ".flac", ".opus"}
_EXT_IMAGE    = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"}
_EXT_DOCUMENT = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".zip", ".txt", ".csv"}
# Plataformas de vídeo que devem ser enviadas como link (não como arquivo direto)
_LINK_DOMAINS = ("youtube.com", "youtu.be", "vimeo.com", "instagram.com", "tiktok.com")


def _detectar_tipo_midia(url: str) -> tuple:
    """
    Detecta o tipo de mídia a partir da URL.
    Retorna (media_type, caption) onde media_type pode ser:
      "image"    → imagem direta
      "video"    → vídeo direto (arquivo .mp4 etc.)
      "audio"    → áudio direto
      "document" → documento (pdf, docx etc.)
      "link"     → URL de plataforma de vídeo/streaming — enviar como texto
    """
    url_lower = url.lower().split("?")[0]  # ignora query string para detectar extensão

    # Verifica domínios de streaming — devem ir como link preview
    for domain in _LINK_DOMAINS:
        if domain in url_lower:
            return "link", ""

    # Detecta extensão
    for ext in _EXT_VIDEO:
        if url_lower.endswith(ext):
            return "video", ""
    for ext in _EXT_AUDIO:
        if url_lower.endswith(ext):
            return "audio", ""
    for ext in _EXT_IMAGE:
        if url_lower.endswith(ext):
            return "image", ""
    for ext in _EXT_DOCUMENT:
        if url_lower.endswith(ext):
            return "document", ""

    # Heurísticas adicionais por padrão de URL
    if "/tts/" in url_lower or "audio" in url_lower:
        return "audio", ""
    if "/video/" in url_lower or "video" in url_lower:
        return "video", ""

    # Fallback seguro: imagem (maioria dos is_direct_url são fotos de unidade)
    return "image", ""


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
            base_url=_cfg.get("url") or _cfg.get("base_url") or _cfg.get("api_url") or "",
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
                # Detecta o tipo de mídia pela URL antes de enviar
                url_clean = content.strip()
                _media_type, _caption = _detectar_tipo_midia(url_clean)
                if _media_type == "link":
                    # YouTube, Vimeo, etc. — envia como texto com link preview
                    await client.send_text(fone, url_clean, link_preview=True)
                else:
                    await client.send_media(fone, url_clean, media_type=_media_type)
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

        # Salva ID da mensagem no Redis para identificação no webhook
        # Evita que mensagens da IA sejam confundidas com mensagens humanas (pause_ia)
        try:
            msg_data = resp.json()
            if msg_data and "id" in msg_data:
                await redis_client.setex(f"ai_msg_id:{msg_data['id']}", 600, "1")
        except Exception:
            pass

        return resp
    except Exception as e:
        logger.error(f"❌ Erro Chatwoot: {e} | URL: {url_m}")
        if PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="chatwoot_error").inc()
        return None


async def escalar_para_humano(
    account_id: int,
    conversation_id: int,
    empresa_id: int,
    integracao: dict,
    motivo: str = "Cliente precisa de atendimento humano",
    nome_ia: str = "Assistente"
) -> bool:
    """
    Escala conversa para atendente humano:
    1. Pausa a IA nesta conversa
    2. Envia mensagem informando o cliente
    3. Tenta mudar status da conversa no Chatwoot para "open" (fila de atendimento)
    """
    try:
        # 1. Pausa IA
        await redis_client.setex(f"pause_ia:{empresa_id}:{conversation_id}", 43200, "1")  # 12h

        # 2. Mensagem para o cliente
        _msg_escalacao = (
            "Entendi sua situação e quero garantir o melhor atendimento possível. "
            "Vou te transferir para um dos nossos atendentes que poderá te ajudar pessoalmente. "
            "Aguarde um momento, por favor! 🤝"
        )
        await enviar_mensagem_chatwoot(
            account_id, conversation_id, _msg_escalacao,
            integracao, empresa_id,
            nome_ia=nome_ia, evitar_prefixo_nome=True
        )

        # 3. Nota interna no Chatwoot com o motivo
        nested = integracao.get('token') if isinstance(integracao.get('token'), dict) else None
        if nested:
            url_base = integracao.get('url') or nested.get('url')
            token = nested.get('access_token') or nested.get('token')
        else:
            url_base = integracao.get('url') or integracao.get('base_url')
            token = integracao.get('access_token') or integracao.get('token')

        if url_base and token:
            headers = {"api_access_token": str(token)}
            # Nota privada com motivo
            nota_url = f"{str(url_base).rstrip('/')}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
            await http_client.post(nota_url, json={
                "content": f"🚨 **Escalação automática por IA**\nMotivo: {motivo}",
                "message_type": "outgoing",
                "private": True,
                "content_attributes": {"origin": "ai"}
            }, headers=headers, timeout=10.0)

            # Muda status para "open" (fila de atendimento humano)
            status_url = f"{str(url_base).rstrip('/')}/api/v1/accounts/{account_id}/conversations/{conversation_id}/toggle_status"
            await http_client.post(status_url, json={"status": "open"}, headers=headers, timeout=10.0)

        logger.info(f"🚨 [E:{empresa_id}] Conversa {conversation_id} escalada para humano: {motivo}")
        return True
    except Exception as e:
        logger.error(f"❌ Erro ao escalar conversa {conversation_id}: {e}")
        return False


async def validar_assinatura(request, signature: str):
    if not CHATWOOT_WEBHOOK_SECRET:
        return
    body = await request.body()
    expected = hmac.new(CHATWOOT_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature or "", expected):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Assinatura inválida")
