"""[MKT-10] Testes do followup_engine (business hours)."""
from datetime import datetime, timezone
from src.services.followup_engine import _adjust_to_business_hours


class TestBusinessHours:
    def test_meio_dia_nao_ajusta(self):
        # 15:00 UTC = 12:00 BRT -> dentro
        dt = datetime(2026, 4, 23, 15, 0, 0, tzinfo=timezone.utc)
        result = _adjust_to_business_hours(dt)
        assert result == dt

    def test_madrugada_empurra_pra_manha(self):
        # 05:00 UTC = 02:00 BRT -> antes do 08:00, ajusta para 08:00 BRT = 11:00 UTC
        dt = datetime(2026, 4, 23, 5, 0, 0, tzinfo=timezone.utc)
        result = _adjust_to_business_hours(dt)
        local = result.replace(tzinfo=None)
        # Ajustado para 11:00 UTC (08:00 BRT)
        assert result.hour == 11
        assert result.day == 23

    def test_noite_empurra_pra_dia_seguinte(self):
        # 02:00 UTC dia 24 = 23:00 BRT dia 23 -> apos 21:00, empurra pra dia seguinte 08:00 BRT
        dt = datetime(2026, 4, 24, 2, 0, 0, tzinfo=timezone.utc)
        result = _adjust_to_business_hours(dt)
        # 08:00 BRT dia 24 = 11:00 UTC dia 24
        assert result.hour == 11
        assert result.day == 24
