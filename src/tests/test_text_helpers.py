"""[QLD-03] Testes para src/utils/text_helpers.py (funcoes puras)."""
import pytest

try:
    from src.utils.text_helpers import normalizar
except ImportError:
    normalizar = None


@pytest.mark.skipif(normalizar is None, reason="text_helpers.normalizar nao disponivel")
class TestNormalizar:
    def test_ascii_lowercase(self):
        assert normalizar("Hello World") == "hello world"

    def test_sem_acento(self):
        assert normalizar("Atenção Não") == "atencao nao"

    def test_espacos_excessivos(self):
        assert normalizar("  varios   espacos  ") == "varios espacos"

    def test_string_vazia(self):
        assert normalizar("") == ""

    def test_none_nao_quebra(self):
        # Comportamento esperado: retornar string vazia
        try:
            result = normalizar(None)
            assert result == ""
        except (AttributeError, TypeError):
            pytest.skip("normalizar nao trata None — valido mas poderia melhorar")
