"""[ARQ-04] Testes da quota de LLM."""
import pytest
from unittest.mock import AsyncMock, patch

from src.services import llm_quota


@pytest.mark.asyncio
async def test_empresa_invalida_nega():
    ok, reason = await llm_quota.check_and_reserve_llm_call(0, estimated_tokens=1000)
    assert ok is False
    assert reason == "empresa_id_invalido"


@pytest.mark.asyncio
async def test_rpm_cap_nega():
    with patch.object(llm_quota, "redis_client") as mock_r:
        # Simula ja ter passado do RPM cap (default 60/min)
        mock_r.incr = AsyncMock(return_value=61)
        mock_r.expire = AsyncMock()
        mock_r.get = AsyncMock(return_value=b"0")
        ok, reason = await llm_quota.check_and_reserve_llm_call(1, estimated_tokens=1000)
        assert ok is False
        assert "rpm_cap" in reason


@pytest.mark.asyncio
async def test_redis_down_fail_open():
    with patch.object(llm_quota, "redis_client") as mock_r:
        mock_r.incr = AsyncMock(side_effect=RuntimeError("redis down"))
        ok, reason = await llm_quota.check_and_reserve_llm_call(1, estimated_tokens=1000)
        assert ok is True  # Fail-open
        assert reason == ""
