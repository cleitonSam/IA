"""
Helpers padronizados para respostas da API.

Uso:
    from src.api.response import api_response, api_error, api_paginated

    return api_response({"id": 1, "nome": "Teste"})
    return api_paginated(items, total=100, offset=0, limit=20)
    return api_error("NOT_FOUND", "Recurso não encontrado", status=404)
"""

from typing import Any, Optional
from fastapi.responses import JSONResponse


def api_response(data: Any, status: int = 200) -> JSONResponse:
    """Resposta de sucesso padronizada."""
    return JSONResponse({"data": data}, status_code=status)


def api_paginated(data: list, total: int, offset: int, limit: int) -> JSONResponse:
    """Resposta paginada padronizada."""
    return JSONResponse({
        "data": data,
        "meta": {
            "total": total,
            "offset": offset,
            "limit": limit,
        }
    })


def api_error(
    code: str,
    message: str,
    details: Optional[list] = None,
    status: int = 400,
) -> JSONResponse:
    """Resposta de erro padronizada."""
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if details:
        body["error"]["details"] = details
    return JSONResponse(body, status_code=status)
