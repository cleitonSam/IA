"""
[SEC-13] Helper para gravar audit log de operacoes administrativas.

Uso:
    from src.core.audit_log import audit

    await audit(
        action="update_empresa",
        entity_type="empresas",
        entity_id=str(empresa_id),
        changes={"nome": {"from": "X", "to": "Y"}},
        user_email=tenant["email"],
        empresa_id=tenant["empresa_id"],
    )

A tabela audit_log tem regras PostgreSQL bloqueando UPDATE e DELETE (append-only).
"""

import json
from typing import Optional
from fastapi import Request

import src.core.database as _database
from src.core.config import logger


async def audit(
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    changes: Optional[dict] = None,
    user_email: Optional[str] = None,
    empresa_id: Optional[int] = None,
    request: Optional[Request] = None,
) -> None:
    """Grava uma linha em audit_log. Nao quebra a operacao em caso de falha (so loga)."""
    if _database.db_pool is None:
        logger.warning(f"audit_log skip db_down action={action} entity={entity_type}#{entity_id}")
        return

    request_ip = None
    request_id = None
    if request is not None:
        request_ip = request.client.host if request.client else None
        request_id = request.headers.get("x-request-id")

    try:
        await _database.db_pool.execute(
            """
            INSERT INTO audit_log
                (user_email, empresa_id, action, entity_type, entity_id, changes_json, request_ip, request_id)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
            """,
            user_email, empresa_id, action, entity_type, entity_id,
            json.dumps(changes) if changes else None,
            request_ip, request_id,
        )
    except Exception as e:
        # Nao falha a operacao de negocio se o audit falhar, mas loga com severidade
        logger.error(f"audit_log_write_failed action={action} entity={entity_type}#{entity_id}: {e}")
