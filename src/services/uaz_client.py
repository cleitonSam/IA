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
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            # Usa o http_client global se disponível; cria um local como fallback
            client = http_client if http_client else httpx.AsyncClient(timeout=15.0)
            own_client = http_client is None
            try:
                resp = await client.request(method, url, headers=self.headers, **kwargs)
                resp.raise_for_status()
                return resp.json()
            finally:
                if own_client:
                    await client.aclose()
        except Exception as e:
            logger.error(f"❌ Erro na UazAPI ({endpoint}): {e}")
            if PROMETHEUS_OK:
                METRIC_ERROS_TOTAL.labels(tipo="uazapi_error").inc()
            return None

    async def send_text(self, number: str, text: str, delay: int = 0) -> bool:
        """Envia mensagem de texto com simulação opcional de typing."""
        # Limpa o número para conter apenas dígitos (remove @s.whatsapp.net se presente)
        clean_number = "".join(filter(str.isdigit, number))
        payload = {
            "number": clean_number,
            "text": text,
            "delay": str(delay) # UazAPI as vezes prefere string para delay
        }
        res = await self._request("POST", "/send/text", json=payload)
        return res is not None

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

    async def send_media(self, number: str, file_url: str, media_type: str = "image", delay: int = 0) -> bool:
        """Envia imagem, vídeo ou documento via URL seguindo padrão UazAPI."""
        clean_number = "".join(filter(str.isdigit, number))
        payload = {
            "number": clean_number,
            "type": media_type,
            "file": file_url,
            "delay": str(delay)
        }
        res = await self._request("POST", "/send/media", json=payload)
        return res is not None

    async def send_ptt(self, number: str, file_url: str, delay: int = 0) -> bool:
        """Envia áudio como PTT (gravado na hora)."""
        clean_number = "".join(filter(str.isdigit, number))
        payload = {
            "number": clean_number,
            "type": "audio",
            "file": file_url,
            "ptt": True,
            "delay": str(delay)
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
