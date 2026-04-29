"""
Instagram Messaging API Client — Meta Graph API v21.0+

API oficial Meta. Requer:
  - Instagram Professional account (Business ou Creator)
  - App Meta com permissao instagram_business_manage_messages
  - Access token de longa duracao
  - Webhook configurado em developers.facebook.com

Docs: https://developers.facebook.com/docs/messenger-platform/instagram

Mesma interface do UazAPIClient — pode ser usado no flow_executor sem mudar.

Uso:
    client = InstagramClient(
        page_id="17841400000000000",        # IG user id (do business profile)
        access_token="IGQVJ...",            # long-lived token
    )
    await client.send_text(recipient_id, "Olá!")
"""
import asyncio
from src.utils.text_helpers import formatar_para_canal
import re
import httpx
from typing import Optional, List, Dict, Any
from src.core.config import logger, PROMETHEUS_OK, METRIC_ERROS_TOTAL

_GRAPH_VERSION = "v21.0"
_GRAPH_BASE = f"https://graph.facebook.com/{_GRAPH_VERSION}"

# Retry config (alinhado com UazAPIClient)
_MAX_RETRIES = 3
_RETRY_DELAYS = [1.0, 2.0, 4.0]

# HTTP client global (injetado pelo startup)
http_client: Optional[httpx.AsyncClient] = None


def _smart_split_ig(text: str, max_len: int = 1000) -> List[str]:
    """IG permite mensagens ate 1000 chars. Se maior, quebra em blocos."""
    text = (text or "").strip()
    if not text or len(text) <= max_len:
        return [text] if text else []
    # Divide por paragrafo
    blocks = []
    current = ""
    for p in text.split("\n\n"):
        if len(current) + len(p) + 2 > max_len and current:
            blocks.append(current.strip())
            current = p
        else:
            current = f"{current}\n\n{p}" if current else p
    if current:
        blocks.append(current.strip())
    return blocks


class InstagramClient:
    """
    Cliente Instagram Messaging API.
    Implementa a mesma interface do UazAPIClient pra ser drop-in replacement no flow_executor.

    Metodos disponiveis:
    - send_text(recipient_id, text)
    - send_text_smart(recipient_id, text)   # split automatico
    - send_quick_replies(recipient_id, text, options)  # ate 13 opcoes
    - send_generic_template(recipient_id, cards)        # carousel com botoes
    - send_button_template(recipient_id, text, buttons) # ate 3 botoes
    - send_image(recipient_id, image_url)
    - send_audio/video/file(recipient_id, url)
    - mark_seen(recipient_id)  # indicador "lida"
    - typing_on/off(recipient_id)  # indicador "digitando..."
    - send_menu(recipient_id, menu_config)  # compat com flow_executor — mapeia pra quick_replies/buttons
    """

    def __init__(
        self,
        page_id: str,
        access_token: str,
        instance_name: str = "instagram",
    ):
        """
        page_id: ID numerico da conta Instagram Business (ex: "17841400000000000")
        access_token: Long-lived access token com permissao instagram_business_manage_messages
        instance_name: compat com UazAPIClient (nao usado internamente)
        """
        self.page_id = str(page_id).strip()
        self.access_token = access_token.strip()
        self.instance_name = instance_name
        self.base_url = _GRAPH_BASE

    async def _request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        # Token sempre como query param
        params = kwargs.pop("params", {}) or {}
        params["access_token"] = self.access_token

        # [SCALE-CB] Circuit breaker do Instagram
        try:
            from main import cb_uazapi as _cb  # reusa CB generico por enquanto
            _cb_state = await _cb.get_state()
            if _cb_state == "OPEN":
                logger.warning(f"[IG-CB] Instagram circuit OPEN — rejeitando {endpoint}")
                return None
        except Exception:
            _cb = None

        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                client = http_client if http_client else httpx.AsyncClient(timeout=15.0)
                own_client = http_client is None
                try:
                    resp = await client.request(method, url, params=params, **kwargs)
                    resp.raise_for_status()
                    if _cb is not None:
                        try:
                            await _cb.record_success()
                        except Exception:
                            pass
                    return resp.json()
                finally:
                    if own_client:
                        await client.aclose()
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
                last_error = e
                delay = _RETRY_DELAYS[attempt] if attempt < len(_RETRY_DELAYS) else _RETRY_DELAYS[-1]
                logger.warning(f"⚠️ IG retry {attempt+1}/{_MAX_RETRIES} ({endpoint}): {type(e).__name__} — {delay}s")
                await asyncio.sleep(delay)
            except httpx.HTTPStatusError as e:
                _RETRYABLE = {408, 429, 500, 502, 503, 504}
                status = e.response.status_code
                if status in _RETRYABLE:
                    last_error = e
                    delay = _RETRY_DELAYS[attempt] if attempt < len(_RETRY_DELAYS) else _RETRY_DELAYS[-1]
                    logger.warning(f"⚠️ IG {status} retentavel ({endpoint}), retry em {delay}s")
                    await asyncio.sleep(delay)
                else:
                    body = ""
                    try:
                        body = e.response.text[:500]
                    except Exception:
                        pass
                    logger.error(f"❌ IG HTTP {status} ({endpoint}): {body}")
                    if PROMETHEUS_OK:
                        METRIC_ERROS_TOTAL.labels(tipo="instagram_error").inc()
                    return None
            except Exception as e:
                logger.error(f"❌ IG erro inesperado ({endpoint}): {type(e).__name__}: {e}")
                if PROMETHEUS_OK:
                    METRIC_ERROS_TOTAL.labels(tipo="instagram_error").inc()
                return None

        logger.error(f"❌ IG falhou apos {_MAX_RETRIES} tentativas ({endpoint}): {last_error}")
        if _cb is not None:
            try:
                await _cb.record_failure()
            except Exception:
                pass
        return None

    # ─────────────────────────────────────────────────────────────────
    # TEXTO
    # ─────────────────────────────────────────────────────────────────

    async def send_text(self, recipient_id: str, text: str, **kwargs) -> bool:
        """Envia mensagem de texto simples via Graph API.
        [FMT-IG] Remove *negrito* e _italico_ que nao sao suportados no IG DM
        (apareceriam literais como '*SILVER*' ao inves de SILVER em destaque)."""
        text_adaptado = formatar_para_canal(text or "", "instagram")
        payload = {
            "recipient": {"id": str(recipient_id)},
            "message": {"text": text_adaptado[:1000]},  # limite IG
        }
        res = await self._request("POST", f"{self.page_id}/messages", json=payload)
        return res is not None

    async def send_text_smart(self, recipient_id: str, text: str, **kwargs) -> bool:
        """Envia texto quebrando em blocos ≤1000 chars se necessario."""
        blocks = _smart_split_ig(text)
        if not blocks:
            return True
        ok = True
        for i, block in enumerate(blocks):
            if i > 0:
                await asyncio.sleep(0.8)  # delay entre blocos
            if not await self.send_text(recipient_id, block):
                ok = False
        return ok

    # ─────────────────────────────────────────────────────────────────
    # MENUS INTERATIVOS
    # ─────────────────────────────────────────────────────────────────

    async def send_quick_replies(
        self,
        recipient_id: str,
        text: str,
        options: List[Dict[str, str]],
    ) -> bool:
        """
        Quick Replies — até 13 opções. Aparecem como bolhas acima do teclado.
        options: [{"title": "Opção 1", "payload": "1"}, ...]
        """
        qrs = [
            {
                "content_type": "text",
                "title": (o.get("title") or o.get("label") or "")[:20],
                "payload": str(o.get("payload") or o.get("id") or o.get("value") or o.get("title", "")),
            }
            for o in options[:13]
        ]
        payload = {
            "recipient": {"id": str(recipient_id)},
            "message": {"text": text[:1000], "quick_replies": qrs},
        }
        res = await self._request("POST", f"{self.page_id}/messages", json=payload)
        return res is not None

    async def send_button_template(
        self,
        recipient_id: str,
        text: str,
        buttons: List[Dict[str, str]],
    ) -> bool:
        """
        Button Template — até 3 botões. Bom pra CTA.
        buttons: [{"title": "Comprar", "type": "postback", "payload": "comprar"}, ...]
        """
        btns = []
        for b in buttons[:3]:
            btype = b.get("type", "postback")
            btn = {"type": btype, "title": (b.get("title") or b.get("label") or "")[:20]}
            if btype == "postback":
                btn["payload"] = str(b.get("payload") or b.get("id") or b.get("title", ""))
            elif btype == "web_url":
                btn["url"] = b.get("url", "")
            btns.append(btn)

        payload = {
            "recipient": {"id": str(recipient_id)},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "button",
                        "text": text[:640],
                        "buttons": btns,
                    },
                }
            },
        }
        res = await self._request("POST", f"{self.page_id}/messages", json=payload)
        return res is not None

    async def send_generic_template(
        self,
        recipient_id: str,
        cards: List[Dict[str, Any]],
    ) -> bool:
        """
        Generic Template (carousel) — ate 10 cards, cada um com até 3 botoes.
        cards: [{"title":"T","subtitle":"S","image_url":"...","buttons":[{...}]},...]
        """
        elements = []
        for c in cards[:10]:
            el = {"title": c.get("title", "")[:80]}
            if c.get("subtitle"):
                el["subtitle"] = c["subtitle"][:80]
            if c.get("image_url"):
                el["image_url"] = c["image_url"]
            if c.get("buttons"):
                el["buttons"] = c["buttons"][:3]
            elements.append(el)

        payload = {
            "recipient": {"id": str(recipient_id)},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {"template_type": "generic", "elements": elements},
                }
            },
        }
        res = await self._request("POST", f"{self.page_id}/messages", json=payload)
        return res is not None

    # ─────────────────────────────────────────────────────────────────
    # COMPAT LAYER — send_menu alinhado ao UazAPIClient.send_menu
    # ─────────────────────────────────────────────────────────────────

    async def send_menu(self, recipient_id: str, menu_config: Dict) -> bool:
        """
        Compatibility layer — recebe a mesma estrutura de menu do UazAPI e adapta pra IG.
        menu_config esperado:
        {
            "tipo": "list"|"button"|"poll",
            "titulo": str,
            "texto": str,
            "rodape": str,
            "botao": str,
            "opcoes": [{"titulo": str, "id": str}, ...]
        }

        Strategy:
        - Se <= 3 opcoes → usa Button Template (botoes reais no IG)
        - Se <= 13 opcoes → Quick Replies (bolhas)
        - Se > 13 opcoes → manda texto com lista NUMERADA (1 - Opcao A, 2 - Opcao B...)
        """
        titulo = menu_config.get("titulo") or ""
        texto = menu_config.get("texto") or ""
        rodape = menu_config.get("rodape") or ""
        opcoes = menu_config.get("opcoes") or []

        # Header text combinado
        header_parts = [titulo, texto]
        full_text = "\n\n".join([p for p in header_parts if p]).strip() or "Escolha uma opção:"
        if rodape:
            full_text = f"{full_text}\n\n_{rodape}_"

        n = len(opcoes)

        if n == 0:
            return await self.send_text(recipient_id, full_text)

        if n <= 3:
            # Button Template (UX melhor)
            buttons = [
                {
                    "type": "postback",
                    "title": (o.get("titulo") or o.get("title") or "")[:20],
                    "payload": str(o.get("id") or o.get("payload") or o.get("titulo") or ""),
                }
                for o in opcoes[:3]
            ]
            return await self.send_button_template(recipient_id, full_text[:640], buttons)

        if n <= 13:
            # Quick Replies
            options = [
                {
                    "title": (o.get("titulo") or o.get("title") or "")[:20],
                    "payload": str(o.get("id") or o.get("payload") or o.get("titulo") or ""),
                }
                for o in opcoes
            ]
            return await self.send_quick_replies(recipient_id, full_text, options)

        # Fallback: lista numerada em texto plano
        # "1 - Quero comprar\n2 - Falar com atendente\n..."
        lines = [full_text, ""]
        for i, o in enumerate(opcoes, 1):
            title = o.get("titulo") or o.get("title") or ""
            lines.append(f"{i} - {title}")
        lines.append("")
        lines.append("_Responda com o número da opção_")
        return await self.send_text_smart(recipient_id, "\n".join(lines))

    # ─────────────────────────────────────────────────────────────────
    # MIDIA
    # ─────────────────────────────────────────────────────────────────

    async def send_media(
        self,
        recipient_id: str,
        file_url: str,
        media_type: str = "image",
        caption: str = "",
        **kwargs,
    ) -> bool:
        """
        Envia media (image/video/audio/file).
        Instagram aceita via attachment.type.
        """
        ig_types = {"image": "image", "video": "video", "audio": "audio", "document": "file", "file": "file"}
        ig_type = ig_types.get(media_type, "image")

        # Caption inline com a midia (IG permite)
        msg = {
            "attachment": {
                "type": ig_type,
                "payload": {"url": file_url, "is_reusable": True},
            }
        }
        payload = {
            "recipient": {"id": str(recipient_id)},
            "message": msg,
        }
        res = await self._request("POST", f"{self.page_id}/messages", json=payload)
        ok = res is not None
        # Envia caption como mensagem separada se houver (IG nao suporta caption em attachment)
        if ok and caption:
            await asyncio.sleep(0.3)
            await self.send_text(recipient_id, caption)
        return ok

    # Aliases compat com UazAPIClient
    async def send_image(self, recipient_id: str, image_url: str, caption: str = "", **kwargs) -> bool:
        return await self.send_media(recipient_id, image_url, "image", caption=caption)

    async def send_audio(self, recipient_id: str, audio_url: str, **kwargs) -> bool:
        return await self.send_media(recipient_id, audio_url, "audio")

    async def send_ppt(self, recipient_id: str, audio_url: str, **kwargs) -> bool:
        # IG nao tem PTT nativo, envia como audio
        return await self.send_media(recipient_id, audio_url, "audio")

    # ─────────────────────────────────────────────────────────────────
    # SENDER ACTIONS (typing, seen)
    # ─────────────────────────────────────────────────────────────────

    async def set_presence(self, recipient_id: str, presence: str = "composing", delay: int = 2000, **kwargs) -> bool:
        """
        Indicador "digitando..." (typing_on) ou "lida" (mark_seen).
        Compat com UazAPIClient.set_presence.
        """
        action_map = {
            "composing": "typing_on",
            "recording": "typing_on",  # IG nao tem gravando separadamente
            "paused": "typing_off",
            "available": "mark_seen",
        }
        action = action_map.get(presence, "typing_on")
        payload = {
            "recipient": {"id": str(recipient_id)},
            "sender_action": action,
        }
        res = await self._request("POST", f"{self.page_id}/messages", json=payload)
        return res is not None

    # ─────────────────────────────────────────────────────────────────
    # FEATURES EXCLUSIVAS IG
    # ─────────────────────────────────────────────────────────────────

    async def set_ice_breakers(self, questions: List[str]) -> bool:
        """
        Ice Breakers — ate 4 perguntas pre-definidas que aparecem ANTES do cliente escrever.
        Config nivel conta (1x setup).
        questions: ["Quero ver planos", "Agendar visita", "Falar com atendente"]
        """
        ice = [{"question": q[:80], "payload": f"ICEBREAKER_{i}"} for i, q in enumerate(questions[:4])]
        payload = {"platform": "instagram", "ice_breakers": ice}
        res = await self._request("POST", "me/messenger_profile", json=payload)
        return res is not None

    async def set_persistent_menu(self, items: List[Dict[str, str]]) -> bool:
        """
        Persistent Menu — menu sempre visivel dentro da conversa. Ate 20 items.
        items: [{"title":"Planos","payload":"PLANOS"}, {"title":"Site","url":"https://..."}, ...]
        """
        menu_items = []
        for it in items[:20]:
            title = it.get("title", "")[:30]
            if it.get("url"):
                menu_items.append({"type": "web_url", "title": title, "url": it["url"]})
            else:
                menu_items.append({
                    "type": "postback",
                    "title": title,
                    "payload": it.get("payload") or title,
                })
        payload = {
            "platform": "instagram",
            "persistent_menu": [{"locale": "default", "composer_input_disabled": False, "call_to_actions": menu_items}]
        }
        res = await self._request("POST", "me/messenger_profile", json=payload)
        return res is not None

    async def send_private_reply_to_comment(self, comment_id: str, message: str) -> bool:
        """
        Private Reply — responde em DM privado a um COMMENT publico de post.
        Feature killer do IG (OMG trigger): cliente comenta "quero" -> bot DM privado.
        """
        payload = {
            "recipient": {"comment_id": comment_id},
            "message": {"text": message[:1000]},
        }
        res = await self._request("POST", f"{self.page_id}/messages", json=payload)
        return res is not None

    # ─────────────────────────────────────────────────────────────────
    # STUBS pra compat com UazAPIClient (nao suportados no IG)
    # ─────────────────────────────────────────────────────────────────

    async def send_location(self, *args, **kwargs) -> bool:
        logger.warning("[IG] send_location nao suportado no Instagram")
        return False

    async def send_contact(self, *args, **kwargs) -> bool:
        logger.warning("[IG] send_contact nao suportado no Instagram")
        return False

    async def send_reaction(self, *args, **kwargs) -> bool:
        logger.warning("[IG] send_reaction nao suportado via Messaging API")
        return False

    async def edit_message(self, *args, **kwargs) -> bool:
        logger.warning("[IG] edit_message nao suportado")
        return False

    async def delete_message(self, *args, **kwargs) -> bool:
        logger.warning("[IG] delete_message nao suportado via API")
        return False

    async def add_label(self, *args, **kwargs) -> bool:
        logger.warning("[IG] add_label nao suportado (IG usa tags internas)")
        return False

    async def remove_label(self, *args, **kwargs) -> bool:
        return False

    async def transfer_to_team(self, *args, **kwargs) -> bool:
        logger.warning("[IG] transfer_to_team — usa handover protocol separado")
        return False
