"""[MKT-01] Testes do lead_scoring."""
import pytest
from src.services.lead_scoring import (
    tier_from_score, _tem_keyword, _KEYWORDS_PRECO, _KEYWORDS_VISITA,
)


class TestTierFromScore:
    def test_tier_a(self):
        assert tier_from_score(85) == "A"
        assert tier_from_score(80) == "A"
        assert tier_from_score(100) == "A"

    def test_tier_b(self):
        assert tier_from_score(75) == "B"
        assert tier_from_score(60) == "B"

    def test_tier_c(self):
        assert tier_from_score(45) == "C"
        assert tier_from_score(30) == "C"

    def test_tier_d(self):
        assert tier_from_score(15) == "D"
        assert tier_from_score(0) == "D"


class TestKeywords:
    def test_detecta_preco(self):
        assert _tem_keyword("Quanto custa o plano?", _KEYWORDS_PRECO)
        assert _tem_keyword("Qual a mensalidade?", _KEYWORDS_PRECO)
        assert _tem_keyword("R$150 é muito caro", _KEYWORDS_PRECO)

    def test_nao_falso_positivo_preco(self):
        assert not _tem_keyword("Bom dia, tudo bem?", _KEYWORDS_PRECO)

    def test_detecta_visita(self):
        assert _tem_keyword("Quero fazer uma aula experimental", _KEYWORDS_VISITA)
        assert _tem_keyword("Posso passar aí pra conhecer?", _KEYWORDS_VISITA)

    def test_keyword_vazia(self):
        assert not _tem_keyword("", _KEYWORDS_PRECO)
        assert not _tem_keyword(None, _KEYWORDS_PRECO)
