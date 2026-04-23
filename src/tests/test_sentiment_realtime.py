"""[MKT-02] Testes do sentiment_realtime."""
import pytest
from unittest.mock import AsyncMock, patch
from src.services import sentiment_realtime


class TestClassificarSinais:
    def test_detecta_cancelamento(self):
        r = sentiment_realtime._classificar_sinais("quero cancelar meu plano agora")
        assert r["cancelamento"] is True

    def test_detecta_urgencia(self):
        r = sentiment_realtime._classificar_sinais("isso é absurdo, vou ao PROCON")
        assert r["urgencia"] is True

    def test_nao_detecta_positivo(self):
        r = sentiment_realtime._classificar_sinais("obrigada pela atencao, gostei muito")
        assert not any(r.values())


@pytest.mark.asyncio
async def test_analisar_msg_positiva_retorna_none():
    with patch.object(sentiment_realtime, "_database") as mock_db, \
         patch.object(sentiment_realtime, "redis_client"):
        mock_db.db_pool = AsyncMock()
        out = await sentiment_realtime.analisar_mensagem(
            conversation_id=1, empresa_id=1,
            texto_cliente="muito bom, amei a academia!",
            sentimento_ia="positivo",
        )
        assert out is None


@pytest.mark.asyncio
async def test_analisar_msg_curta_ignora():
    out = await sentiment_realtime.analisar_mensagem(
        conversation_id=1, empresa_id=1, texto_cliente="ok",
    )
    assert out is None
