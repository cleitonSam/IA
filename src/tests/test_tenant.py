"""[SEC-02] Testes de isolamento multi-tenant."""
import pytest
from fastapi import HTTPException
from src.core.tenant import _extract_tenant, require_tenant_match


class TestExtractTenant:
    def test_admin_master_sem_empresa_id_ok(self):
        t = _extract_tenant({"sub": "x@fluxo.com", "perfil": "admin_master"})
        assert t["is_admin_master"] is True
        assert t["empresa_id"] is None

    def test_admin_normal_sem_empresa_id_falha(self):
        with pytest.raises(HTTPException) as exc:
            _extract_tenant({"sub": "x@empresa.com", "perfil": "admin"})
        assert exc.value.status_code == 401

    def test_admin_normal_com_empresa_id(self):
        t = _extract_tenant({"sub": "x@empresa.com", "perfil": "admin", "empresa_id": 42})
        assert t["is_admin_master"] is False
        assert t["empresa_id"] == 42

    def test_empresa_id_zero_invalido(self):
        with pytest.raises(HTTPException):
            _extract_tenant({"sub": "x@e.com", "perfil": "admin", "empresa_id": 0})


class TestRequireTenantMatch:
    @pytest.mark.asyncio
    async def test_admin_master_passa_em_qualquer_empresa(self):
        tenant = {"empresa_id": None, "is_admin_master": True, "perfil": "admin_master", "email": "x"}
        result = await require_tenant_match(empresa_id=999, tenant=tenant)
        assert result is tenant

    @pytest.mark.asyncio
    async def test_admin_na_sua_empresa_passa(self):
        tenant = {"empresa_id": 5, "is_admin_master": False, "perfil": "admin", "email": "x"}
        result = await require_tenant_match(empresa_id=5, tenant=tenant)
        assert result is tenant

    @pytest.mark.asyncio
    async def test_admin_em_outra_empresa_nega_403(self):
        tenant = {"empresa_id": 5, "is_admin_master": False, "perfil": "admin", "email": "x"}
        with pytest.raises(HTTPException) as exc:
            await require_tenant_match(empresa_id=999, tenant=tenant)
        assert exc.value.status_code == 403
