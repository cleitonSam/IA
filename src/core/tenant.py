"""
[SEC-02] Isolamento multi-tenant — dependências FastAPI centralizadas.

Objetivo: garantir que cada empresa cliente só enxergue e altere seus próprios dados.
Regra geral:
  - admin_master (superadmin da plataforma) → vê tudo, pode atuar em qualquer empresa
  - qualquer outro perfil → só vê/atua na propria empresa (token_payload["empresa_id"])

Uso recomendado em routers:

    from fastapi import Depends
    from src.core.tenant import require_tenant, require_tenant_match

    @router.get("/personalidade")
    async def get_personalidade(tenant = Depends(require_tenant)):
        empresa_id = tenant["empresa_id"]
        ...

    @router.put("/unidades/{unidade_id}")
    async def update_unidade(
        unidade_id: int,
        payload: UnidadeUpdate,
        tenant = Depends(require_tenant),
    ):
        # Buscar a unidade e validar:
        await require_tenant_owns(tenant, "unidades", unidade_id)
        ...

Princípios:
  1. NUNCA confiar em empresa_id vindo do body/query/path para autorizar escrita.
  2. Sempre derivar de token_payload["empresa_id"] (JWT assinado).
  3. admin_master pode passar empresa_id explicito via query ?empresa_id=N (quando aplicavel).
"""

from typing import Optional
from fastapi import Depends, HTTPException, Query, status

from src.core.config import logger
from src.core.security import get_current_user_token


ADMIN_MASTER = "admin_master"


def _extract_tenant(token_payload: dict) -> dict:
    """Normaliza o payload do JWT em um dict de tenant."""
    empresa_id = token_payload.get("empresa_id")
    perfil = (token_payload.get("perfil") or "").lower()
    email = token_payload.get("sub")

    if not isinstance(empresa_id, int) or empresa_id <= 0:
        # admin_master pode nao ter empresa_id (super user da plataforma)
        if perfil != ADMIN_MASTER:
            logger.warning(f"[SEC-02] Token sem empresa_id valido: {email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token sem empresa_id válido",
            )
        empresa_id = None

    return {
        "empresa_id": empresa_id,
        "perfil": perfil,
        "email": email,
        "is_admin_master": perfil == ADMIN_MASTER,
    }


async def require_tenant(
    token_payload: dict = Depends(get_current_user_token),
    empresa_id_override: Optional[int] = Query(
        None,
        alias="empresa_id",
        description="Override de empresa_id (apenas admin_master)",
    ),
) -> dict:
    """
    Retorna o contexto do tenant atual.

    Para admin_master: respeita query ?empresa_id=N, senao usa o do token.
    Para outros perfis: IGNORA qualquer override e usa sempre o do token.
    """
    tenant = _extract_tenant(token_payload)

    if tenant["is_admin_master"] and empresa_id_override is not None:
        tenant["empresa_id"] = empresa_id_override
        tenant["override_applied"] = True

    return tenant


async def require_tenant_match(
    empresa_id: int,
    tenant: dict = Depends(require_tenant),
) -> dict:
    """
    Dependência para rotas com {empresa_id} no path.
    Rejeita se o empresa_id do path não bater com o do token
    (admin_master passa livremente).
    """
    if not tenant["is_admin_master"] and tenant["empresa_id"] != empresa_id:
        logger.warning(
            f"[SEC-02] Tenant mismatch: user={tenant['email']} "
            f"token_empresa={tenant['empresa_id']} path_empresa={empresa_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sem permissão para acessar recursos de outra empresa",
        )
    return tenant


async def require_tenant_owns(
    tenant: dict,
    tabela: str,
    recurso_id: int,
    coluna_empresa: str = "empresa_id",
) -> bool:
    """
    Verifica, no banco, se o recurso de {tabela}.{recurso_id} pertence ao tenant.
    Uso: após buscar o recurso, valide antes de retornar/modificar.

    Exemplo:
        await require_tenant_owns(tenant, "unidades", unidade_id)
        # Se nao pertencer, levanta 403.

    admin_master passa sempre (retorna True direto).

    Retorna True se ok, senão levanta HTTPException(403 ou 404).
    """
    if tenant["is_admin_master"]:
        return True

    import src.core.database as _database
    if not _database.db_pool:
        raise HTTPException(status_code=503, detail="Banco indisponível")

    # Whitelist de tabelas para evitar SQL injection via parametro
    _allowed = {
        "unidades", "faqs", "personalidade_ia", "fluxos_triagem", "conversas",
        "mensagens_locais", "followups", "integracoes", "usuarios",
        "eventos_funil", "templates_followup", "ab_tests", "knowledge_base",
    }
    if tabela not in _allowed:
        logger.error(f"[SEC-02] Tabela nao-whitelisted em require_tenant_owns: {tabela}")
        raise HTTPException(status_code=500, detail="Configuração inválida")

    row = await _database.db_pool.fetchrow(
        f"SELECT {coluna_empresa} FROM {tabela} WHERE id = $1",  # noqa: S608 - tabela e whitelist
        recurso_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Recurso não encontrado")

    if row[coluna_empresa] != tenant["empresa_id"]:
        logger.warning(
            f"[SEC-02] Tentativa de acesso cross-tenant: user={tenant['email']} "
            f"empresa_token={tenant['empresa_id']} recurso={tabela}#{recurso_id} "
            f"empresa_do_recurso={row[coluna_empresa]}"
        )
        raise HTTPException(status_code=403, detail="Sem permissão para este recurso")

    return True


def scope_empresa_id(tenant: dict) -> int:
    """
    Retorna o empresa_id efetivo para queries.
    Para perfis normais, é sempre o do token.
    Para admin_master, é o override (se aplicado) ou None (listar tudo).
    """
    return tenant["empresa_id"]


async def require_admin_master(
    token_payload: dict = Depends(get_current_user_token),
) -> dict:
    """Dependência que exige perfil admin_master (superadmin)."""
    tenant = _extract_tenant(token_payload)
    if not tenant["is_admin_master"]:
        logger.warning(f"[SEC-02] Acesso admin_master negado para {tenant['email']}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas admin_master",
        )
    return tenant
