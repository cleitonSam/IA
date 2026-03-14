import asyncio
import httpx
from typing import Optional, List, Dict, Any
from src.core.config import logger, PROMETHEUS_OK, METRIC_ERROS_TOTAL

# HTTP client — deve ser inicializado pelo startup_event no bot_core
http_client: httpx.AsyncClient = None

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
            "Content-Type": "application/json"
        }

    async def _request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict]:
        if not http_client:
            logger.error("🚫 UazAPIClient: http_client não inicializado.")
            return None
            
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            resp = await http_client.request(method, url, headers=self.headers, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"❌ Erro na UazAPI ({endpoint}): {e}")
            if PROMETHEUS_OK:
                METRIC_ERROS_TOTAL.labels(tipo="uazapi_error").inc()
            return None

    async def send_text(self, chat_id: str, text: str, delay: int = 0) -> bool:
        """Envia mensagem de texto com simulação opcional de typing."""
        payload = {
            "chatId": chat_id,
            "text": text,
            "delay": delay
        }
        res = await self._request("POST", "/message/text", json=payload)
        return res is not None and res.get("status") in (200, 201, "success")

    async def set_presence(self, chat_id: str, presence: str = "composing", delay: int = 2000) -> bool:
        """
        Simula presença: 'composing' (digitando), 'recording' (gravando), 'paused'.
        """
        payload = {
            "chatId": chat_id,
            "presence": presence,
            "delay": delay
        }
        res = await self._request("POST", "/message/presence", json=payload)
        return res is not None

    async def send_media(self, chat_id: str, url: str, caption: str = "", media_type: str = "image") -> bool:
        """Envia imagem, vídeo ou documento via URL."""
        payload = {
            "chatId": chat_id,
            "url": url,
            "caption": caption,
            "type": media_type
        }
        res = await self._request("POST", "/send/media", json=payload)
        return res is not None

    async def send_ptt(self, chat_id: str, url: str) -> bool:
        """Envia áudio como PTT (gravado na hora)."""
        payload = {
            "chatId": chat_id,
            "url": url,
            "ptt": True
        }
        res = await self._request("POST", "/send/media", json=payload)
        return res is not None
