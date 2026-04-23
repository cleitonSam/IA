"""[MKT-07] Testes conceituais do roi_attribution."""
import pytest
from unittest.mock import AsyncMock, patch

from src.services import roi_attribution


@pytest.mark.asyncio
async def test_compute_roi_sem_db_retorna_error():
    with patch.object(roi_attribution, "_database") as mock_db:
        mock_db.db_pool = None
        result = await roi_attribution.compute_roi(empresa_id=1)
        assert "error" in result


@pytest.mark.asyncio
async def test_compute_roi_calcula_ratio():
    with patch.object(roi_attribution, "_database") as mock_db:
        fake_pool = AsyncMock()
        fake_pool.fetchval = AsyncMock(return_value=100)  # 100 leads
        fake_pool.fetchrow = AsyncMock(return_value={
            "total_matriculas": 20,
            "matriculas_bot": 12,
            "receita_bot_brl": 3000.0,
            "receita_total_brl": 5000.0,
        })
        mock_db.db_pool = fake_pool

        result = await roi_attribution.compute_roi(
            empresa_id=1, periodo_dias=30, custo_mensal_bot_brl=500.0,
        )
        assert result["leads_qualificados"] == 100
        assert result["matriculas_atribuidas_bot"] == 12
        assert result["receita_atribuida_brl"] == 3000.0
        # ratio = 3000 / 500 = 6.0
        assert result["roi_ratio"] == 6.0
        # conv = 12 / 100 * 100 = 12%
        assert result["taxa_conversao_lead_matricula_pct"] == 12.0
