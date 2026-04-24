"""
UazAPIGO V2 Client — Motor SaaS IA
Sincronizado com a documentação oficial: https://docs.uazapi.com

Melhorias aplicadas (2026-03-29):
- Todos os métodos recebem track_source="chatbot" para rastreamento no painel UazAPI
- readchat + readmessages habilitados por padrão (UX mais fluida)
- replyid: suporte a respostas vinculadas
- send_text: linkPreview completo (auto ou customizado)
- send_media: docName, mimetype, thumbnail, tipos sticker/myaudio/ptv
- set_presence: fix bug — delay enviado como int (era str)
- send_menu: poll (enquete) + carousel + botões ricos (URL, call, copy, imageButton)
- send_contact: novo — envia vCard
- send_poll: atalho para enviar enquetes
"""
import asyncio
import re
import httpx
from typing import Optional, List, Dict, Any
from src.core.config import logger, PROMETHEUS_OK, METRIC_ERROS_TOTAL


# ── Smart split: divide mensagem longa em blocos lógicos ──────────────
_MIN_BLOCK_LEN = 30   # bloco mínimo para não gerar micro-mensagens
_MAX_BLOCK_LEN = 700  # acima disso, WhatsApp corta ou fica ruim de ler


def _smart_split(text: str) -> List[str]:
    """
    Divide texto em blocos semânticos para envio sequencial no WhatsApp.
    Regras de separação (em ordem de prioridade):
      1. Blocos separados por linha dupla em branco (\n\n)
      2. Se um bloco ainda for grande, separa por bullet/tópico (• ou - ou *)
      3. Pergunta final (última frase terminando em ?) vira bloco próprio
    Blocos muito pequenos são mesclados com o anterior.
    """
    text = text.strip()
    if not text or len(text) <= _MAX_BLOCK_LEN:
        return [text] if text else []

    # ── Passo 1: separar por parágrafos (dupla quebra de linha) ──
    raw_blocks = re.split(r'\n\s*\n', text)
    blocks: List[str] = []

    for raw in raw_blocks:
        raw = raw.strip()
        if not raw:
            continue

        # ── Passo 2: se o bloco for grande, tentar separar por bullets ──
        if len(raw) > _MAX_BLOCK_LEN:
            # Separa por linhas que começam com bullet (•, -, *, ou número.)
            bullet_parts = re.split(r'(?=\n\s*(?:[•\-\*]|\d+[\.\)])\s)', raw)
            # Primeiro item pode ser um header ("Oferecemos:")
            for part in bullet_parts:
                part = part.strip()
                if part:
                    blocks.append(part)
        else:
            blocks.append(raw)

    # ── Passo 3: extrair pergunta final como bloco próprio ──
    if len(blocks) > 0:
        last = blocks[-1]
        # Procura última frase terminando com ? (possivelmente seguida de emoji)
        match = re.search(r'(?:^|\n)([^\n]*\?[^\n]{0,10})$', last)
        if match and len(last) > len(match.group(1)) + _MIN_BLOCK_LEN:
            pergunta = match.group(1).strip()
            resto = last[:match.start(1)].strip()
            if resto:
                blocks[-1] = resto
                blocks.append(pergunta)

    # ── Passo 4: mesclar blocos pequenos demais com o anterior ──
    merged: List[str] = []
    for blk in blocks:
        if merged and len(blk) < _MIN_BLOCK_LEN:
            merged[-1] = merged[-1] + "\n\n" + blk
        else:
            merged.append(blk)

    # Se resultou em 1 bloco igual ao original, retorna sem split
    if len(merged) <= 1:
        return [text]

    return merged


# HTTP client — deve ser inicializado pelo startup_event no bot_core
http_client: httpx.AsyncClient = None

# Retry config
_MAX_RETRIES = 3
_RETRY_DELAYS = [1.0, 2.0, 4.0]  # exponential backoff

# Tipos de mídia suportados pela UazAPI
MEDIA_TYPES_SUPPORTED = {"image", "video", "document", "audio", "myaudio", "ptt", "ptv", "sticker"}


class UazAPIClient:
    """
    Cliente para interface com UazAPIGO V2.
    Suporta múltiplas instâncias dinamicamente.

    Todos os métodos de envio incluem por padrão:
    - track_source="chatbot" (rastreamento no painel UazAPI)
    - readchat=True (limpa contador de não lidas)
    - readmessages=True (marca mensagens recebidas como lidas)
    """

    def __init__(self, base_url: str, token: str, instance_name: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.instance_name = instance_name
        self.headers = {
            "token": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    async def _request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        last_error = None

        for attempt in range(_MAX_RETRIES):
            try:
                client = http_client if http_client else httpx.AsyncClient(timeout=15.0)
                own_client = http_client is None
                try:
                    resp = await client.request(method, url, headers=self.headers, **kwargs)
                    resp.raise_for_status()
                    return resp.json()
                finally:
                    if own_client:
                        await client.aclose()
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
                last_error = e
                delay = _RETRY_DELAYS[attempt] if attempt < len(_RETRY_DELAYS) else _RETRY_DELAYS[-1]
                logger.warning(
                    f"⚠️ UazAPI retry {attempt+1}/{_MAX_RETRIES} ({endpoint}): "
                    f"{type(e).__name__} — aguardando {delay}s"
                )
                await asyncio.sleep(delay)
            except httpx.HTTPStatusError as e:
                # [QW-9] Retry para status retentaveis: 408 (request timeout),
                # 429 (rate limit), 500, 502, 503, 504 (erros transientes de servidor).
                # 4xx (exceto os acima) sao erros do cliente e nao fazem retry.
                _RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
                status = e.response.status_code
                if status in _RETRYABLE_STATUS:
                    last_error = e
                    delay = _RETRY_DELAYS[attempt] if attempt < len(_RETRY_DELAYS) else _RETRY_DELAYS[-1]
                    logger.warning(
                        f"⚠️ UazAPI status {status} retentavel ({endpoint}), "
                        f"retry {attempt+1}/{_MAX_RETRIES} em {delay}s"
                    )
                    await asyncio.sleep(delay)
                else:
                    body = ""
                    try:
                        body = e.response.text[:500]
                    except Exception:
                        pass
                    logger.error(
                        f"❌ UazAPI erro HTTP {status} ({endpoint}): body={body}"
                    )
                    if PROMETHEUS_OK:
                        METRIC_ERROS_TOTAL.labels(tipo="uazapi_error").inc()
                    return None
            except Exception as e:
                last_error = e
                logger.error(
                    f"❌ UazAPI erro inesperado ({endpoint}): {type(e).__name__}: {e}"
                )
                if PROMETHEUS_OK:
                    METRIC_ERROS_TOTAL.labels(tipo="uazapi_error").inc()
                return None

        logger.error(
            f"❌ UazAPI falhou após {_MAX_RETRIES} tentativas ({endpoint}): {last_error}"
        )
        if PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="uazapi_error").inc()
        return None

    # ─────────────────────────────────────────────────────────────────
    # TEXTO
    # ─────────────────────────────────────────────────────────────────

    async def send_text(
        self,
        number: str,
        text: str,
        delay: int = 0,
        *,
        replyid: Optional[str] = None,
        readchat: bool = True,
        readmessages: bool = True,
        link_preview: bool = False,
        link_preview_title: Optional[str] = None,
        link_preview_description: Optional[str] = None,
        link_preview_image: Optional[str] = None,
        link_preview_large: bool = False,
        track_id: Optional[str] = None,
    ) -> bool:
        """
        Envia mensagem de texto.

        Args:
            number: Telefone, grupo (@g.us) ou canal (@newsletter)
            text: Texto da mensagem (suporta placeholders UazAPI como {{name}})
            delay: Delay em ms antes do envio (mostra "Digitando...")
            replyid: ID da mensagem original para criar resposta vinculada
            readchat: Limpa contador de não lidas no chat
            readmessages: Marca últimas 10 mensagens recebidas como lidas
            link_preview: Ativa preview automático de links no texto
            link_preview_title/description/image/large: Customiza o preview
            track_id: ID livre para rastreamento em sistemas externos
        """
        clean_number = "".join(filter(str.isdigit, number)) if "@" not in number else number
        payload: Dict[str, Any] = {
            "number": clean_number,
            "text": text,
            "readchat": readchat,
            "readmessages": readmessages,
            "track_source": "chatbot",
        }
        if delay:
            payload["delay"] = delay
        if replyid:
            payload["replyid"] = replyid
        if track_id:
            payload["track_id"] = track_id
        if link_preview:
            payload["linkPreview"] = True
            if link_preview_title:
                payload["linkPreviewTitle"] = link_preview_title
            if link_preview_description:
                payload["linkPreviewDescription"] = link_preview_description
            if link_preview_image:
                payload["linkPreviewImage"] = link_preview_image
                payload["linkPreviewLarge"] = link_preview_large

        res = await self._request("POST", "/send/text", json=payload)
        return res is not None

    async def send_text_smart(
        self,
        number: str,
        text: str,
        delay: int = 0,
        *,
        replyid: Optional[str] = None,
        track_id: Optional[str] = None,
    ) -> bool:
        """
        Envia texto dividido em blocos semânticos.
        Cada bloco vira uma mensagem separada no WhatsApp com delay de digitação.
        """
        blocks = _smart_split(text)
        if len(blocks) <= 1:
            return await self.send_text(number, text, delay=delay, replyid=replyid, track_id=track_id)

        logger.debug(f"📨 smart_split: {len(blocks)} blocos para {number}")
        ok = True
        for i, block in enumerate(blocks):
            # Delay proporcional ao tamanho do bloco (simula digitação)
            typing_delay = max(800, min(len(block) * 8, 3000))
            if i == 0:
                typing_delay = delay or typing_delay
            # Só envia replyid no primeiro bloco (vincula a mensagem original)
            reply = replyid if i == 0 else None
            res = await self.send_text(
                number, block, delay=typing_delay, replyid=reply, track_id=track_id
            )
            if not res:
                ok = False
        return ok

    # ─────────────────────────────────────────────────────────────────
    # PRESENÇA (digitando / gravando)
    # ─────────────────────────────────────────────────────────────────

    async def set_presence(
        self,
        number: str,
        presence: str = "composing",
        delay: int = 2000,
    ) -> bool:
        """
        Simula presença: 'composing' (digitando), 'recording' (gravando), 'paused'.
        CORREÇÃO: delay enviado como int (era str — bug na versão anterior).
        """
        clean_number = "".join(filter(str.isdigit, number)) if "@" not in number else number
        payload = {
            "number": clean_number,
            "presence": presence,
            "delay": int(delay),  # ← FIX: era str(delay), docs exigem integer
        }
        res = await self._request("POST", "/send/presence", json=payload)
        return res is not None

    # ─────────────────────────────────────────────────────────────────
    # MÍDIA
    # ─────────────────────────────────────────────────────────────────

    async def send_media(
        self,
        number: str,
        file_url: str,
        media_type: str = "image",
        caption: str = "",
        delay: int = 0,
        *,
        doc_name: Optional[str] = None,
        mimetype: Optional[str] = None,
        thumbnail: Optional[str] = None,
        replyid: Optional[str] = None,
        readchat: bool = True,
        readmessages: bool = True,
        track_id: Optional[str] = None,
    ) -> bool:
        """
        Envia mídia (imagem, vídeo, áudio, documento, sticker, PTT, vídeo-nota).

        Tipos suportados: image, video, document, audio, myaudio, ptt, ptv, sticker

        Args:
            doc_name: Nome do arquivo para documentos (ex: "Contrato.pdf")
            mimetype: MIME type explícito (detectado automaticamente se omitido)
            thumbnail: URL ou base64 de thumbnail para vídeos/documentos
            replyid: ID da mensagem para resposta vinculada
        """
        clean_number = "".join(filter(str.isdigit, number)) if "@" not in number else number

        # Normaliza tipo inválido para "document" (fallback seguro)
        if media_type not in MEDIA_TYPES_SUPPORTED:
            logger.warning(
                f"⚠️ send_media: tipo '{media_type}' não suportado → usando 'document'"
            )
            media_type = "document"

        # ImageKit transforma vídeos automaticamente, gerando MP4 inválido para
        # whatsmeow/UazAPI. Forçar ?tr=orig-true para servir o arquivo original.
        if "imagekit.io" in file_url and media_type in ("video", "ptv"):
            sep = "&" if "?" in file_url else "?"
            if "tr=orig" not in file_url:
                file_url = f"{file_url}{sep}tr=orig-true"
                logger.debug(f"📎 ImageKit video: forçando original → {file_url[:100]}")

        # Auto-detecta mimetype quando não fornecido explicitamente.
        # Ignora query string (?updatedAt=...) para detectar extensão real.
        # Evita erro "invalid MP4 file format" na UazAPI ao processar vídeos.
        if not mimetype:
            url_path = file_url.lower().split("?")[0]  # ex: /path/video.mp4

            if media_type == "video" or any(url_path.endswith(e) for e in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".3gp", ".m4v")):
                if url_path.endswith(".mov"):
                    mimetype = "video/quicktime"
                elif url_path.endswith(".webm"):
                    mimetype = "video/webm"
                elif url_path.endswith(".3gp"):
                    mimetype = "video/3gpp"
                else:
                    mimetype = "video/mp4"
                media_type = "video"  # garante tipo correto

            elif media_type == "ptt" or (media_type == "audio" and url_path.endswith(".ogg")):
                mimetype = "audio/ogg; codecs=opus"

            elif media_type == "audio" or any(url_path.endswith(e) for e in (".ogg", ".mp3", ".wav", ".aac", ".m4a", ".opus")):
                if url_path.endswith(".mp3"):
                    mimetype = "audio/mpeg"
                elif url_path.endswith(".wav"):
                    mimetype = "audio/wav"
                elif url_path.endswith(".aac"):
                    mimetype = "audio/aac"
                elif url_path.endswith(".m4a"):
                    mimetype = "audio/mp4"
                else:
                    mimetype = "audio/ogg"

            elif url_path.endswith(".jpg") or url_path.endswith(".jpeg"):
                mimetype = "image/jpeg"
            elif url_path.endswith(".png"):
                mimetype = "image/png"
            elif url_path.endswith(".gif"):
                mimetype = "image/gif"
            elif url_path.endswith(".webp"):
                mimetype = "image/webp"

            elif url_path.endswith(".pdf"):
                mimetype = "application/pdf"
                media_type = "document"
                if not doc_name:
                    doc_name = file_url.split("/")[-1].split("?")[0] or "documento.pdf"
            elif url_path.endswith(".docx"):
                mimetype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                media_type = "document"
                if not doc_name:
                    doc_name = file_url.split("/")[-1].split("?")[0] or "arquivo.docx"

        payload: Dict[str, Any] = {
            "number": clean_number,
            "type": media_type,
            "file": file_url,
            "readchat": readchat,
            "readmessages": readmessages,
            "track_source": "chatbot",
        }
        if delay:
            payload["delay"] = delay
        if caption:
            payload["text"] = caption
        if doc_name and media_type == "document":
            payload["docName"] = doc_name
        if mimetype:
            payload["mimetype"] = mimetype
        if thumbnail and media_type in ("video", "document"):
            payload["thumbnail"] = thumbnail
        if replyid:
            payload["replyid"] = replyid
        if track_id:
            payload["track_id"] = track_id

        logger.debug(
            f"📎 send_media: number={clean_number}, type={media_type}, "
            f"file={file_url[:80]}..."
        )
        res = await self._request("POST", "/send/media", json=payload)

        if res is None and media_type not in ("document", "sticker", "ptt", "ptv"):
            # Fallback: tenta como document (URLs que falham como image/video)
            logger.warning(
                f"⚠️ send_media fallback: tentando como 'document' para {file_url[:80]}"
            )
            payload["type"] = "document"
            # Remove mimetype de vídeo/imagem — UazAPI rejeita document com mimetype incompatível
            payload.pop("mimetype", None)
            # Adiciona docName para que o arquivo tenha nome legível no WhatsApp
            if not payload.get("docName"):
                _fallback_name = file_url.split("/")[-1].split("?")[0] or "arquivo"
                payload["docName"] = _fallback_name
            res = await self._request("POST", "/send/media", json=payload)

        return res is not None

    async def send_ptt(
        self,
        number: str,
        file_url: str,
        delay: int = 0,
    ) -> bool:
        """Envia áudio como PTT (Push-to-Talk / mensagem de voz)."""
        return await self.send_media(
            number, file_url,
            media_type="ptt",
            delay=delay,
        )

    async def send_sticker(
        self,
        number: str,
        file_url: str,
    ) -> bool:
        """Envia uma figurinha (sticker) via WhatsApp. Suporta .webp e .png."""
        return await self.send_media(
            number, file_url,
            media_type="sticker",
            mimetype="image/webp" if file_url.lower().split("?")[0].endswith(".webp") else None,
        )

    async def send_contact(
        self,
        number: str,
        contact_name: str,
        contact_phone: str,
        *,
        delay: int = 0,
    ) -> bool:
        """
        Envia um cartão de contato (vCard) via WhatsApp.

        Args:
            contact_name: Nome exibido no contato
            contact_phone: Telefone do contato (somente dígitos, com DDI)
        """
        clean_number = "".join(filter(str.isdigit, number)) if "@" not in number else number
        clean_phone = "".join(filter(str.isdigit, contact_phone))
        # vCard mínimo reconhecido pelo WhatsApp
        vcard = (
            "BEGIN:VCARD\n"
            "VERSION:3.0\n"
            f"FN:{contact_name}\n"
            f"TEL;type=CELL;type=VOICE;waid={clean_phone}:+{clean_phone}\n"
            "END:VCARD"
        )
        payload: Dict[str, Any] = {
            "number": clean_number,
            "vcard": vcard,
            "fullName": contact_name,
            "track_source": "chatbot",
        }
        if delay:
            payload["delay"] = delay
        res = await self._request("POST", "/send/contact", json=payload)
        return res is not None

    # ─────────────────────────────────────────────────────────────────
    # MENUS INTERATIVOS (botão, lista, enquete, carrossel)
    # ─────────────────────────────────────────────────────────────────

    async def send_menu(
        self,
        number: str,
        config: dict,
    ) -> bool:
        """
        Envia menu interativo via UazAPI.

        Suporta tipos: list, button, poll, carousel.
        config deve conter: tipo, texto, titulo, rodape, botao, opcoes.

        Para poll (enquete):
            config = {
                "tipo": "poll",
                "texto": "Qual horário prefere?",
                "opcoes": [{"titulo": "Manhã"}, {"titulo": "Tarde"}],
                "selectable_count": 1,
            }

        Para carousel, use send_carousel() diretamente.
        """
        clean_number = "".join(filter(str.isdigit, number)) if "@" not in number else number
        tipo = config.get("tipo", "list")

        if tipo == "list":
            # choices: ["[NomeSeção]", "Titulo|id|Descricao", ...]
            choices = [f"[{config.get('titulo', 'Opções')}]"]
            for opt in config.get("opcoes", []):
                titulo = opt.get("titulo", "")
                opt_id = opt.get("id", titulo)
                descricao = opt.get("descricao", "")
                choices.append(f"{titulo}|{opt_id}|{descricao}")

            payload = {
                "number": clean_number,
                "type": "list",
                "text": config.get("texto", ""),
                "footerText": config.get("rodape", ""),
                "listButton": config.get("botao", "Ver opções"),
                "selectableCount": 1,
                "choices": choices,
                "readchat": True,
                "readmessages": True,
                "track_source": "chatbot",
                "delay": config.get("delay", 1000),
            }

        elif tipo == "button":
            # Botões ricos: "texto|id", "texto|url:https://...", "texto|call:+55..."
            choices = []
            for opt in config.get("opcoes", [])[:4]:
                titulo = opt.get("titulo", "")
                btn_id = opt.get("id", "")
                btn_url = opt.get("url", "")
                btn_call = opt.get("call", "")

                if btn_url:
                    choices.append(f"{titulo}|{btn_url}")
                elif btn_call:
                    choices.append(f"{titulo}|call:{btn_call}")
                elif btn_id:
                    choices.append(f"{titulo}|{btn_id}")
                else:
                    choices.append(titulo)

            payload = {
                "number": clean_number,
                "type": "button",
                "text": config.get("texto", ""),
                "footerText": config.get("rodape", ""),
                "choices": choices,
                "readchat": True,
                "readmessages": True,
                "track_source": "chatbot",
                "delay": config.get("delay", 1000),
            }
            # Imagem no cabeçalho dos botões (opcional)
            if config.get("imagem"):
                payload["imageButton"] = config["imagem"]

        elif tipo == "poll":
            choices = [opt.get("titulo", str(opt)) for opt in config.get("opcoes", [])]
            payload = {
                "number": clean_number,
                "type": "poll",
                "text": config.get("texto", ""),
                "choices": choices,
                "selectableCount": config.get("selectable_count", 1),
                "readchat": True,
                "readmessages": True,
                "track_source": "chatbot",
                "delay": config.get("delay", 1000),
            }

        else:
            logger.warning(f"⚠️ Tipo de menu não suportado por send_menu: {tipo}")
            return False

        res = await self._request("POST", "/send/menu", json=payload)
        return res is not None

    async def send_buttons(
        self,
        number: str,
        text: str,
        buttons: list,
        footer: str = "",
        image_url: Optional[str] = None,
    ) -> bool:
        """
        Envia mensagem com botões de resposta rápida.

        buttons: [
            {"id": "btn1", "text": "Opção 1"},         # botão resposta
            {"text": "Ver site", "url": "https://..."},  # botão URL
            {"text": "Ligar", "call": "+5511999999"},    # botão chamada
        ]
        image_url: Imagem opcional no cabeçalho dos botões
        """
        clean_number = "".join(filter(str.isdigit, number)) if "@" not in number else number
        choices = []
        for btn in buttons[:4]:
            titulo = btn.get("text", btn.get("titulo", ""))
            if btn.get("url"):
                choices.append(f"{titulo}|{btn['url']}")
            elif btn.get("call"):
                choices.append(f"{titulo}|call:{btn['call']}")
            else:
                btn_id = btn.get("id", titulo)
                choices.append(f"{titulo}|{btn_id}" if btn_id != titulo else titulo)

        payload: Dict[str, Any] = {
            "number": clean_number,
            "type": "button",
            "text": text,
            "footerText": footer,
            "choices": choices,
            "readchat": True,
            "readmessages": True,
            "track_source": "chatbot",
            "delay": 1000,
        }
        if image_url:
            payload["imageButton"] = image_url

        res = await self._request("POST", "/send/menu", json=payload)
        return res is not None

    async def send_list(
        self,
        number: str,
        text: str,
        sections: list,
        button_text: str = "Ver opções",
        footer: str = "",
    ) -> bool:
        """
        Envia lista interativa com seções e itens (máx 10 opções no WhatsApp).
        sections: [{"title": "Seção", "rows": [{"id": "1", "title": "Item", "description": "Desc"}]}]
        """
        clean_number = "".join(filter(str.isdigit, number)) if "@" not in number else number
        choices = []
        for section in sections:
            section_title = section.get("title", "Opções")
            choices.append(f"[{section_title}]")
            for row in section.get("rows", []):
                titulo = row.get("title", "")
                row_id = row.get("id", titulo)
                desc = row.get("description", "")
                choices.append(f"{titulo}|{row_id}|{desc}")

        payload = {
            "number": clean_number,
            "type": "list",
            "text": text,
            "footerText": footer,
            "listButton": button_text,
            "selectableCount": 1,
            "choices": choices,
            "readchat": True,
            "readmessages": True,
            "track_source": "chatbot",
            "delay": 1000,
        }
        res = await self._request("POST", "/send/menu", json=payload)
        return res is not None

    async def send_poll(
        self,
        number: str,
        question: str,
        options: List[str],
        selectable_count: int = 1,
    ) -> bool:
        """
        Envia enquete interativa no WhatsApp.

        Args:
            question: Pergunta da enquete
            options: Lista de opções (ex: ["Manhã", "Tarde", "Noite"])
            selectable_count: Quantas opções o usuário pode marcar
        """
        clean_number = "".join(filter(str.isdigit, number)) if "@" not in number else number
        payload = {
            "number": clean_number,
            "type": "poll",
            "text": question,
            "choices": options,
            "selectableCount": selectable_count,
            "readchat": True,
            "readmessages": True,
            "track_source": "chatbot",
            "delay": 1000,
        }
        res = await self._request("POST", "/send/menu", json=payload)
        return res is not None

    async def send_carousel(
        self,
        number: str,
        header_text: str,
        cards: List[Dict[str, Any]],
    ) -> bool:
        """
        Envia carrossel de cartões com imagens e botões.

        cards: [
            {
                "title": "Produto X",
                "description": "Descrição curta",
                "image": "https://exemplo.com/img.jpg",
                "buttons": [
                    {"text": "Ver mais", "url": "https://..."},
                    {"text": "Código", "copy": "PROMO10"},
                    {"text": "Ligar", "call": "+5511999999"},
                ]
            }
        ]
        """
        clean_number = "".join(filter(str.isdigit, number)) if "@" not in number else number
        choices = []
        for card in cards:
            title = card.get("title", "")
            desc = card.get("description", "")
            card_text = f"{title}\n{desc}" if desc else title
            choices.append(f"[{card_text}]")

            if card.get("image"):
                choices.append(f"{{{card['image']}}}")

            for btn in card.get("buttons", [])[:3]:
                btn_text = btn.get("text", "")
                if btn.get("url"):
                    choices.append(f"{btn_text}|{btn['url']}")
                elif btn.get("copy"):
                    choices.append(f"{btn_text}|copy:{btn['copy']}")
                elif btn.get("call"):
                    choices.append(f"{btn_text}|call:{btn['call']}")
                else:
                    choices.append(btn_text)

        payload = {
            "number": clean_number,
            "type": "carousel",
            "text": header_text,
            "choices": choices,
            "readchat": True,
            "readmessages": True,
            "track_source": "chatbot",
            "delay": 1000,
        }
        res = await self._request("POST", "/send/menu", json=payload)
        return res is not None

    # ─────────────────────────────────────────────────────────────────
    # LOCALIZAÇÃO
    # ─────────────────────────────────────────────────────────────────

    async def send_location(
        self,
        number: str,
        latitude: float,
        longitude: float,
        name: str = "",
        address: str = "",
    ) -> bool:
        """Envia localização (pin no mapa) via WhatsApp."""
        clean_number = "".join(filter(str.isdigit, number)) if "@" not in number else number
        payload = {
            "number": clean_number,
            "latitude": latitude,
            "longitude": longitude,
            "name": name,
            "address": address,
            "readchat": True,
            "readmessages": True,
            "track_source": "chatbot",
            "delay": 1000,
        }
        res = await self._request("POST", "/send/location", json=payload)
        return res is not None

    # ─────────────────────────────────────────────────────────────────
    # REACOES, EDIT, DELETE
    # ─────────────────────────────────────────────────────────────────

    async def send_reaction(
        self,
        number: str,
        message_id: str,
        emoji: str,
    ) -> bool:
        """
        Envia reacao emoji a uma mensagem especifica.
        emoji: string unicode. Passar string vazia remove a reacao.
        """
        clean_number = "".join(filter(str.isdigit, number)) if "@" not in number else number
        payload = {
            "number": clean_number,
            "messageId": message_id,
            "reaction": emoji,
            "track_source": "chatbot",
        }
        res = await self._request("POST", "/send/reaction", json=payload)
        return res is not None

    async def edit_message(
        self,
        number: str,
        message_id: str,
        new_text: str,
    ) -> bool:
        """Edita uma mensagem de texto ja enviada."""
        clean_number = "".join(filter(str.isdigit, number)) if "@" not in number else number
        payload = {
            "number": clean_number,
            "messageId": message_id,
            "text": new_text,
            "track_source": "chatbot",
        }
        res = await self._request("POST", "/message/edit", json=payload)
        return res is not None

    async def delete_message(
        self,
        number: str,
        message_id: str,
    ) -> bool:
        """Revoga/deleta uma mensagem enviada (apaga para ambos)."""
        clean_number = "".join(filter(str.isdigit, number)) if "@" not in number else number
        payload = {
            "number": clean_number,
            "messageId": message_id,
            "track_source": "chatbot",
        }
        res = await self._request("POST", "/message/delete", json=payload)
        return res is not None

    # ─────────────────────────────────────────────────────────────────
    # LABELS / TAGS
    # ─────────────────────────────────────────────────────────────────

    async def add_label(
        self,
        number: str,
        labels: List[str],
    ) -> bool:
        """Adiciona uma ou mais labels/tags a um contato."""
        clean_number = "".join(filter(str.isdigit, number)) if "@" not in number else number
        payload = {
            "number": clean_number,
            "labels": labels,
            "track_source": "chatbot",
        }
        res = await self._request("POST", "/label/add", json=payload)
        return res is not None

    async def remove_label(
        self,
        number: str,
        labels: List[str],
    ) -> bool:
        """Remove uma ou mais labels/tags de um contato."""
        clean_number = "".join(filter(str.isdigit, number)) if "@" not in number else number
        payload = {
            "number": clean_number,
            "labels": labels,
            "track_source": "chatbot",
        }
        res = await self._request("POST", "/label/remove", json=payload)
        return res is not None

    # ─────────────────────────────────────────────────────────────────
    # TRANSFER (handoff)
    # ─────────────────────────────────────────────────────────────────

    async def transfer_to_team(
        self,
        number: str,
        team_id=None,
        team_name=None,
        note: str = "",
    ) -> bool:
        """
        [QW-1] Transfere conversa para time/fila. A UazAPI nao tem endpoint
        nativo de transferencia, entao estrategia e marcar com LABEL do time.
        """
        try:
            labels = []
            if team_id:
                labels.append(f"team:{team_id}")
            if team_name:
                labels.append(f"team_name:{team_name}")
            if labels:
                await self.add_label(number, labels)

            if note:
                clean_number = "".join(filter(str.isdigit, number)) if "@" not in number else number
                payload = {
                    "number": clean_number,
                    "text": note,
                    "readchat": True,
                    "readmessages": True,
                    "track_source": f"transfer:{team_id or 'unknown'}",
                }
                await self._request("POST", "/send/text", json=payload)

            logger.info(f"transfer_to_team: numero={number} team_id={team_id}")
            return True
        except Exception as e:
            logger.error(f"transfer_to_team falhou: {e}")
            return False

