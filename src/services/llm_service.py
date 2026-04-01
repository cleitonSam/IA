import os
from openai import AsyncOpenAI
import logging
from src.core.config import OPENROUTER_API_KEY, OPENAI_API_KEY, logger

# Inicialização global dos clientes LLM
cliente_ia = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY) if OPENROUTER_API_KEY else None
cliente_whisper = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

def is_provider_unavailable_error(err: Exception) -> bool:
    """Detecta indisponibilidade de provedor LLM para acionar modo degradado."""
    from src.utils.text_helpers import normalizar
    msg = normalizar(str(err) or "")
    sinais = [
        "key limit exceeded", "limit exceeded", "quota", "insufficient credits",
        "credit", "rate limit", "error code: 403", "error code: 402",
    ]
    return any(s in msg for s in sinais)


def is_openrouter_auth_error(err: Exception) -> bool:
    """Detecta erro de credencial/autorização da OPENROUTER_API_KEY."""
    from src.utils.text_helpers import normalizar
    msg = normalizar(str(err) or "")
    sinais = ["401", "unauthorized", "invalid api key", "authentication", "forbidden"]
    return any(s in msg for s in sinais)
