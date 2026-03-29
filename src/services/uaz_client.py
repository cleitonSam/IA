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

class UazAPIClient:
    """
    Cliente para interface com UazAPI.
    Suporta múltiplas instâncias dinamicamente.
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
                logger.warning(f"⚠️ UazAPI retry {attempt+1}/{_MAX_RETRIES} ({endpoint}): {type(e).__name__} — aguardando {delay}s")
                await asyncio.sleep(delay)
            except httpx.HTTPStatusError as e:
                # Não faz retry para erros 4xx (exceto 429)
                if e.response.status_code == 429:
                    last_error = e
                    delay = _RETRY_DELAYS[attempt] if attempt < len(_RETRY_DELAYS) else _RETRY_DELAYS[-1]
                    logger.warning(f"⚠️ UazAPI rate limited ({endpoint}), retry em {delay}s")
                    await asyncio.sleep(delay)
                else:
                    body = ""
                    try:
                        body = e.response.text[:300]
                    except Exception:
                        pass
                    logger.error(f"❌ UazAPI erro HTTP {e.response.status_code} ({endpoint}): {e} | body={body}")
                    if PROMETHEUS_OK:
                        METRIC_ERROS_TOTAL.labels(tipo="uazapi_error").inc()
                    return None
            except Exception as e:
                last_error = e
                logger.error(f"❌ UazAPI erro inesperado ({endpoint}): {type(e).__name__}: {e}")
                if PROMETHEUS_OK:
                    METRIC_ERROS_TOTAL.labels(tipo="uazapi_error").inc()
                return None

        logger.error(f"❌ UazAPI falhou após {_MAX_RETRIES} tentativas ({endpoint}): {last_error}")
        if PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="uazapi_error").inc()
        return None

    async def send_text(self, number: str, text: str, delay: int = 0) -> bool:
        """Envia mensagem de texto simples (bloco único)."""
        clean_number = "".join(filter(str.isdigit, number))
        payload = {
            "number": clean_number,
            "text": text,
            "delay": delay
        }
        res = await self._request("POST", "/send/text", json=payload)
        return res is not None

    async def send_text_smart(self, number: str, text: str, delay: int = 0) -> bool:
        """
        Envia texto dividido em blocos semânticos.
        Cada bloco vira uma mensagem separada no WhatsApp com delay de digitação.
        """
        blocks = _smart_split(text)
        if len(blocks) <= 1:
            return await self.send_text(number, text, delay=delay)

        logger.debug(f"📨 smart_split: {len(blocks)} blocos para {number}")
        ok = True
        for i, block in enumerate(blocks):
            # Delay proporcional ao tamanho do bloco (simula digitação)
            typing_delay = max(800, min(len(block) * 8, 3000))
            if i == 0:
                typing_delay = delay or typing_delay
            res = await self.send_text(number, block, delay=typing_delay)
            if not res:
                ok = False
        return ok

    async def set_presence(self, number: str, presence: str = "composing", delay: int = 2000) -> bool:
        """
        Simula presença: 'composing' (digitando), 'recording' (gravando), 'paused'.
        """
        clean_number = "".join(filter(str.isdigit, number))
        payload = {
            "number": clean_number,
            "presence": presence,
            "delay": str(delay)
        }
        res = await self._request("POST", "/send/presence", json=payload)
        return res is not None

    async def send_media(self, number: str, file_url: str, media_type: str = "image", caption: str = "", delay: int = 0) -> bool:
        """Envia imagem, vídeo ou documento via URL seguindo padrão UazAPI."""
        clean_number = "".join(filter(str.isdigit, number))
        payload = {
            "number": clean_number,
            "type": media_type,
            "file": file_url
        }
        if delay:
            payload["delay"] = delay
        if caption:
            payload["text"] = caption
        logger.debug(f"📎 send_media payload: number={clean_number}, type={media_type}, file={file_url[:80]}...")
        res = await self._request("POST", "/send/media", json=payload)
        if res is None:
            # Fallback: tenta como document (URLs que falham como image/video)
            if media_type != "document":
                logger.warning(f"⚠️ send_media fallback: tentando como document para {file_url[:80]}")
                payload["type"] = "document"
                res = await self._request("POST", "/send/media", json=payload)
        return res is not None

    async def send_ptt(self, number: str, file_url: str, delay: int = 0) -> bool:
        """Envia áudio como PTT (Push-to-Talk / mensagem de voz)."""
        clean_number = "".join(filter(str.isdigit, number))
        payload = {
            "number": clean_number,
            "type": "ptt",
            "file": file_url,
            "delay": delay
        }
        res = await self._request("POST", "/send/media", json=payload)
        return res is not None

    async def send_menu(self, number: str, config: dict) -> bool:
        """
        Envia menu interativo de triagem via UazAPI.
        Suporta tipos: list, button.
        config deve conter: tipo, texto, titulo, rodape, botao, opcoes (lista de {id, titulo, descricao}).
        """
        clean_number = "".join(filter(str.isdigit, number))
        tipo = config.get("tipo", "list")
        opcoes = config.get("opcoes", [])

        if tipo == "list":
            # Formato esperado pela UazAPI (igual ao fluxo N8N):
            # choices: ["[NomeSeção]", "Titulo|id|Descricao", ...]
            choices = [f"[{config.get('titulo', 'Opções')}]"]
            for opt in opcoes:
                titulo = opt.get("titulo", "")
                opt_id = opt.get("id", "")
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
                "delay": 1000
            }
        elif tipo == "button":
            # Botões de resposta rápida (máx 3 no WhatsApp)
            choices = [opt.get("titulo", "") for opt in opcoes[:3]]
            payload = {
                "number": clean_number,
                "type": "button",
                "text": config.get("texto", ""),
                "footerText": config.get("rodape", ""),
                "choices": choices,
                "readchat": True,
                "readmessages": True,
                "delay": 1000
            }
        else:
            logger.warning(f"⚠️ Tipo de menu não suportado: {tipo}")
            return False

        res = await self._request("POST", "/send/menu", json=payload)
        return res is not None

    async def send_buttons(self, number: str, text: str, buttons: list, footer: str = "") -> bool:
        """
        Envia mensagem com botões de resposta rápida (máx 3 no WhatsApp).
        buttons: [{"id": "btn1", "text": "Opção 1"}, ...]
        """
        clean_number = "".join(filter(str.isdigit, number))
        choices = [btn.get("text", btn.get("titulo", "")) for btn in buttons[:3]]
        payload = {
            "number": clean_number,
            "type": "button",
            "text": text,
            "footerText": footer,
            "choices": choices,
            "readchat": True,
            "readmessages": True,
            "delay": 1000
        }
        res = await self._request("POST", "/send/menu", json=payload)
        return res is not None

    async def send_list(self, number: str, text: str, sections: list,
                        button_text: str = "Ver opções", footer: str = "") -> bool:
        """
        Envia lista interativa com seções e itens (máx 10 opções no WhatsApp).
        sections: [{"title": "Seção", "rows": [{"id": "1", "title": "Item", "description": "Desc"}]}]
        """
        clean_number = "".join(filter(str.isdigit, number))
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
            "delay": 1000
        }
        res = await self._request("POST", "/send/menu", json=payload)
        return res is not None

    async def send_location(self, number: str, latitude: float, longitude: float,
                            name: str = "", address: str = "") -> bool:
        """Envia localização (pin no mapa) via WhatsApp."""
        clean_number = "".join(filter(str.isdigit, number))
        payload = {
            "number": clean_number,
            "latitude": latitude,
            "longitude": longitude,
            "name": name,
            "address": address,
            "delay": 1000
        }
        res = await self._request("POST", "/send/location", json=payload)
        return res is not None
