"""
ChatwootFlowClient — drop-in do UazAPIClient/InstagramClient pro flow_executor,
mas rotea TODO envio via Chatwoot outgoing. Uso principal: Instagram chegando via
Chatwoot (sem phone_number, sem UazAPI), onde o fluxo_triagem precisa responder
pelo mesmo canal que recebeu.

Implementa so os metodos que o flow_executor realmente chama. Formatos ricos
(quick_replies nativos, poll, enquete) degradam para texto numerado — Chatwoot
nao tem suporte generico a componentes interativos cross-canal.

Uso:
    client = ChatwootFlowClient(
        account_id=7,
        conversation_id=289,
        integracao_chatwoot=integracao,
        empresa_id=1,
        nome_ia="Atendente",
    )
    await executar_fluxo(empresa_id, "ig:289", mensagem, fluxo, client, unidade_id=0)
"""
from __future__ import annotations

import mimetypes
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from src.core.config import logger


def _monta_menu_texto(menu: Dict[str, Any]) -> str:
    """Converte um dict de menu (titulo/texto/opcoes) em texto numerado."""
    titulo = (menu or {}).get("titulo") or ""
    texto = (menu or {}).get("texto") or ""
    rodape = (menu or {}).get("rodape") or ""
    opcoes = (menu or {}).get("opcoes") or []

    partes = [p for p in (titulo, texto) if p]
    header = "\n\n".join(partes).strip() or "Escolha uma opção:"

    linhas = [header, ""]
    for i, op in enumerate(opcoes, 1):
        t = op.get("titulo") or op.get("title") or op.get("label") or ""
        linhas.append(f"{i}. {t}")
    if opcoes:
        linhas.append("")
        linhas.append("_Responda com o número da opção_")
    if rodape:
        linhas.append("")
        linhas.append(f"_{rodape}_")
    return "\n".join(linhas)


class ChatwootFlowClient:
    """Adapter minimal p/ flow_executor rotear envios via Chatwoot."""

    def __init__(
        self,
        account_id: int,
        conversation_id: int,
        integracao_chatwoot: Dict[str, Any],
        empresa_id: int,
        nome_ia: str = "Atendente",
    ):
        self.account_id = account_id
        self.conversation_id = conversation_id
        self.integracao = integracao_chatwoot
        self.empresa_id = empresa_id
        self.nome_ia = nome_ia

    # ──────────────────── envio core ────────────────────
    def _resolve_url_token(self) -> tuple[Optional[str], Optional[str]]:
        """Extrai URL base e token da integracao, com normalizacao de protocolo."""
        cfg = self.integracao or {}
        url_base = cfg.get("url") or cfg.get("base_url")
        token = cfg.get("access_token") or cfg.get("token")
        if isinstance(token, dict):
            token = token.get("access_token") or token.get("token")
        if not url_base or not token:
            return None, None
        raw = str(url_base).strip()
        if not raw.startswith(("http://", "https://")):
            url_base = f"https://{raw}"
        return str(url_base).rstrip("/"), str(token)

    async def _enviar(self, text: str) -> bool:
        """
        POST direto pra API do Chatwoot. Nao depende de http_client global
        (que nao eh inicializado neste contexto — causava NoneType.post).
        """
        url_base, token = self._resolve_url_token()
        if not url_base or not token:
            logger.error(f"[ChatwootFlowClient] integracao Chatwoot incompleta conv={self.conversation_id}")
            return False

        post_url = (
            f"{url_base}/api/v1/accounts/{self.account_id}"
            f"/conversations/{self.conversation_id}/messages"
        )

        # Prefixo de nome (mesma convencao do enviar_mensagem_chatwoot)
        content = f"*{self.nome_ia}*\n{text}" if self.nome_ia else text

        payload = {
            "content": content,
            "message_type": "outgoing",
            "content_attributes": {
                "origin": "ai",
                "ai_agent": self.nome_ia,
                "ignore_webhook": True,
            },
        }
        headers = {"api_access_token": token}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(post_url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    logger.error(
                        f"[ChatwootFlowClient] send_text HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                    return False

                # Marca ID da msg no Redis pra evitar que seja reconhecida como humana
                try:
                    _data = resp.json()
                    _msg_id = _data.get("id") if isinstance(_data, dict) else None
                    if _msg_id:
                        try:
                            from src.core.redis_client import redis_client as _rc
                            await _rc.setex(f"ai_msg_id:{self.empresa_id}:{_msg_id}", 600, "1")
                            await _rc.setex(f"ai_msg_id:{_msg_id}", 600, "1")  # legado
                        except Exception:
                            pass
                except Exception:
                    pass

            return True
        except Exception as e:
            logger.error(f"[ChatwootFlowClient] _enviar exception conv={self.conversation_id}: {e}")
            return False

    # ──────────────────── texto ────────────────────
    async def send_text(self, phone: str, text: str, **kw) -> bool:
        return await self._enviar(text)

    async def send_text_smart(self, phone: str, text: str, **kw) -> bool:
        # Chatwoot não tem limite baixo como IG; envia inteiro.
        return await self._enviar(text)

    # ──────────────────── menus ────────────────────
    async def send_menu(self, phone: str, menu_config: Dict[str, Any], **kw) -> bool:
        return await self._enviar(_monta_menu_texto(menu_config))

    async def send_quick_replies(
        self, phone: str, text: str, options: List[Dict[str, str]], **kw
    ) -> bool:
        linhas = [text, ""]
        for i, o in enumerate(options, 1):
            t = o.get("title") or o.get("label") or o.get("titulo") or ""
            linhas.append(f"{i}. {t}")
        linhas.append("")
        linhas.append("_Responda com o número da opção_")
        return await self._enviar("\n".join(linhas))

    async def send_button_template(
        self, phone: str, text: str, buttons: List[Dict[str, str]], **kw
    ) -> bool:
        return await self.send_quick_replies(phone, text, buttons)

    # ──────────────────── midia ────────────────────
    async def send_media(
        self, phone: str, url: str, media_type: str = "image", caption: str = "", **kw
    ) -> bool:
        """
        Envia mídia (imagem/audio/video/doc) baixando a URL e re-uploading via
        multipart pra API do Chatwoot. Chatwoot entao roteia pro IG/WA nativo
        como attachment de verdade (nao apenas link).

        Fallback: se download ou upload falhar, manda a URL como texto —
        pior que attachment mas melhor que nada.
        """
        try:
            # 1. Baixa o arquivo
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as dl:
                r = await dl.get(url)
                r.raise_for_status()
                file_bytes = r.content
                content_type = r.headers.get("content-type") or (
                    mimetypes.guess_type(urlparse(url).path)[0] or "application/octet-stream"
                )
                # Nome do arquivo — usa o basename da URL ou um fallback
                filename = os.path.basename(urlparse(url).path) or f"file_{media_type}"
                # Garante extensao se nao tiver
                if "." not in filename:
                    _ext = mimetypes.guess_extension(content_type) or ""
                    filename = f"{filename}{_ext}"

            # 2. Extrai URL base e token da integracao Chatwoot
            url_base, token = self._resolve_url_token()
            if not url_base or not token:
                logger.warning(f"[ChatwootFlowClient] send_media: integracao incompleta — fallback texto")
                return await self._enviar(f"{url}\n\n{caption}" if caption else url)

            post_url = (
                f"{url_base}/api/v1/accounts/{self.account_id}"
                f"/conversations/{self.conversation_id}/messages"
            )

            # 3. Multipart POST — Chatwoot aceita attachments[] + content
            _content_caption = caption or ""
            # Prefixo de nome da IA pra consistencia com envio de texto
            if self.nome_ia and _content_caption:
                _content_caption = f"*{self.nome_ia}*\n{_content_caption}"
            elif self.nome_ia and not _content_caption:
                # sem caption, nao precisa prefixar nada — attachment fala por si
                pass

            files = {
                "attachments[]": (filename, file_bytes, content_type),
            }
            data = {
                "message_type": "outgoing",
                "content": _content_caption,
            }
            headers = {"api_access_token": str(token)}

            async with httpx.AsyncClient(timeout=30.0) as up:
                resp = await up.post(post_url, data=data, files=files, headers=headers)
                if resp.status_code >= 400:
                    logger.error(
                        f"[ChatwootFlowClient] upload falhou {resp.status_code}: {resp.text[:200]}"
                    )
                    # fallback: manda como texto pra nao perder a mensagem
                    return await self._enviar(f"{url}\n\n{caption}" if caption else url)

            logger.info(
                f"✅ [ChatwootFlowClient] mídia enviada conv={self.conversation_id} "
                f"tipo={media_type} size={len(file_bytes)}b"
            )
            return True

        except Exception as e:
            logger.error(f"[ChatwootFlowClient] send_media erro: {e}")
            # Ultima salvaguarda: manda URL como texto
            try:
                return await self._enviar(f"{url}\n\n{caption}" if caption else url)
            except Exception:
                return False

    async def send_image(self, phone: str, url: str, caption: str = "", **kw) -> bool:
        return await self.send_media(phone, url, "image", caption=caption)

    async def send_audio(self, phone: str, url: str, **kw) -> bool:
        return await self.send_media(phone, url, "audio")

    async def send_ptt(self, phone: str, url: str, **kw) -> bool:
        return await self.send_media(phone, url, "audio")

    async def send_video(self, phone: str, url: str, caption: str = "", **kw) -> bool:
        return await self.send_media(phone, url, "video", caption=caption)

    async def send_file(self, phone: str, url: str, **kw) -> bool:
        return await self.send_media(phone, url, "document")

    # ──────────────────── enquete / localizacao / contato ────────────────────
    async def send_poll(
        self, phone: str, pergunta: str, opcoes: List[str], multi_select: bool = False, **kw
    ) -> bool:
        linhas = [pergunta, ""]
        for i, op in enumerate(opcoes, 1):
            linhas.append(f"{i}. {op}")
        linhas.append("")
        linhas.append("_Responda com o número da opção_")
        return await self._enviar("\n".join(linhas))

    async def send_location(
        self, phone: str, latitude: float, longitude: float, name: str = "", address: str = "", **kw
    ) -> bool:
        partes = ["📍 Localização"]
        if name:
            partes.append(name)
        if address:
            partes.append(address)
        partes.append(f"https://maps.google.com/?q={latitude},{longitude}")
        return await self._enviar("\n".join(partes))

    async def send_contact(
        self, phone: str, contact_name: str, contact_phone: str, **kw
    ) -> bool:
        return await self._enviar(f"📇 {contact_name}\n{contact_phone}")

    # ──────────────────── presenca / no-ops ────────────────────
    async def set_presence(self, phone: str, presence: str = "composing", delay: int = 0, **kw) -> bool:
        return True  # Chatwoot nao expoe presence via API de webhook outgoing

    async def send_reaction(self, *a, **kw) -> bool:
        return False

    async def edit_message(self, *a, **kw) -> bool:
        return False

    async def delete_message(self, *a, **kw) -> bool:
        return False

    async def add_label(self, *a, **kw) -> bool:
        # Labels sao via API Chatwoot separada; fora de escopo aqui.
        return False

    async def remove_label(self, *a, **kw) -> bool:
        return False

    async def transfer_to_team(
        self, phone: str, team_id: Optional[int], message: str, **kw
    ) -> bool:
        # Envia a mensagem de transfer e marca pausa — a IA nao retoma ate operador
        # reabrir. A atribuicao efetiva ao time precisa de chamada a API Chatwoot
        # (nao coberto aqui pra manter o adapter minimal).
        return await self._enviar(message)
