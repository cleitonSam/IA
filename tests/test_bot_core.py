"""
Tests for the refactored bot_core modules:
- src/services/prompt_builder.py
- src/services/message_formatter.py
- src/services/conversation_handler.py
"""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.services.message_formatter import (
    dividir_em_blocos,
    extrair_json,
    corrigir_json,
    garantir_frase_completa,
    limpar_resposta_llm,
)
from src.services.prompt_builder import (
    filtrar_planos_por_contexto,
    resumo_unidade,
)


# ─── message_formatter tests ──────────────────────────────────

class TestDividirEmBlocos:
    def test_short_text_single_block(self):
        blocks = dividir_em_blocos("Olá, tudo bem?", max_chars=100)
        assert len(blocks) == 1
        assert blocks[0] == "Olá, tudo bem?"

    def test_long_text_splits(self):
        text = "Primeira frase. " * 50
        blocks = dividir_em_blocos(text, max_chars=200)
        assert len(blocks) > 1
        for b in blocks:
            assert len(b) <= 250  # allows some slack

    def test_empty_text(self):
        blocks = dividir_em_blocos("", max_chars=100)
        assert blocks == [] or blocks == [""]


class TestExtrairJson:
    def test_extracts_json_from_text(self):
        text = 'Aqui vai: {"key": "value"} fim'
        result = extrair_json(text)
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_extracts_plain_json(self):
        text = '{"status": "ok"}'
        result = extrair_json(text)
        parsed = json.loads(result)
        assert parsed["status"] == "ok"

    def test_no_json_returns_original(self):
        result = extrair_json("não é json nenhum")
        assert result == "não é json nenhum"


class TestCorrigirJson:
    def test_strips_markdown_fences(self):
        text = '```json\n{"key": "value"}\n```'
        result = corrigir_json(text)
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_handles_valid_json(self):
        text = '{"key": "value"}'
        result = corrigir_json(text)
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_garbage_returns_cleaned(self):
        result = corrigir_json("completamente inválido sem json")
        assert isinstance(result, str)


class TestGarantirFraseCompleta:
    def test_complete_sentence_untouched(self):
        text = "Olá, como posso ajudar?"
        assert garantir_frase_completa(text) == text

    def test_truncated_sentence_fixed(self):
        text = "Olá, como posso ajudar? Vou te explicar sobre os planos que"
        result = garantir_frase_completa(text)
        # Should keep at least the first complete sentence
        assert "Olá, como posso ajudar?" in result

    def test_preserves_send_video_tag(self):
        text = "Confira nosso tour! <SEND_VIDEO>https://video.com/tour</SEND_VIDEO>"
        result = garantir_frase_completa(text)
        assert "<SEND_VIDEO>" in result
        assert "https://video.com/tour" in result

    def test_preserves_send_image_tag(self):
        text = "Veja a foto! <SEND_IMAGE>https://img.com/pic.jpg</SEND_IMAGE>"
        result = garantir_frase_completa(text)
        assert "<SEND_IMAGE>" in result


class TestLimparRespostaLlm:
    def test_basic_cleanup(self):
        result = limpar_resposta_llm("  Olá, tudo bem?  ", "normal")
        assert result["resposta_texto"].strip() == "Olá, tudo bem?"

    def test_detects_emotional_state(self):
        result = limpar_resposta_llm("Que maravilha! Vamos fechar!", "normal")
        # The function should return a novo_estado
        assert "novo_estado" in result

    def test_preserves_media_tags(self):
        text = "Veja! <SEND_VIDEO>https://video.com</SEND_VIDEO> Legal né?"
        result = limpar_resposta_llm(text, "normal")
        assert "<SEND_VIDEO>" in result["resposta_texto"]


# ─── prompt_builder tests ─────────────────────────────────────

class TestResumoUnidade:
    def test_basic_resumo(self):
        unidade = {
            "nome": "Unidade Centro",
            "endereco": "Rua A, 123",
            "cidade": "São Paulo",
            "bairro": "Centro",
        }
        result = resumo_unidade(unidade)
        assert "Unidade Centro" in result
        assert "Rua A" in result or "Centro" in result

    def test_empty_unidade(self):
        result = resumo_unidade({})
        assert isinstance(result, str)


class TestFiltrarPlanosPorContexto:
    def test_filters_by_intent(self):
        planos = [
            {"id": 1, "nome": "Plano Musculação", "descricao": "Musculação livre"},
            {"id": 2, "nome": "Plano Aulas Coletivas", "descricao": "Fit dance, zumba, pilates"},
            {"id": 3, "nome": "Plano Completo", "descricao": "Acesso completo"},
        ]
        result = filtrar_planos_por_contexto("quero aulas coletivas", planos)
        assert len(result) > 0
        # Should prioritize planos matching the intent

    def test_empty_text_returns_all(self):
        planos = [
            {"id": 1, "nome": "Plano A"},
            {"id": 2, "nome": "Plano B"},
        ]
        result = filtrar_planos_por_contexto("", planos)
        assert len(result) == 2

    def test_empty_planos(self):
        result = filtrar_planos_por_contexto("musculação", [])
        assert result == []


# ─── conversation_handler tests ───────────────────────────────

class TestConversationHandler:
    @pytest.mark.asyncio
    async def test_coletar_mensagens_buffer(self, fake_redis):
        """Tests that buffer collection works with FakeRedis."""
        from tests.conftest import FakeRedis

        with patch("src.services.conversation_handler.redis_client", fake_redis):
            from src.services.conversation_handler import coletar_mensagens_buffer

            # Pre-populate the buffer
            key = "1:buffet:100"
            await fake_redis.rpush(key, json.dumps({"text": "oi", "files": []}))
            await fake_redis.rpush(key, json.dumps({"text": "tudo bem?", "files": []}))

            msgs = await coletar_mensagens_buffer(100, 1)
            assert len(msgs) >= 2

    @pytest.mark.asyncio
    async def test_persistir_mensagens_usuario(self):
        with patch("src.services.conversation_handler.bd_salvar_mensagem_local", new_callable=AsyncMock) as mock_save:
            from src.services.conversation_handler import persistir_mensagens_usuario
            await persistir_mensagens_usuario(100, 1, ["oi", "tudo bem?"], ["audio transcrito"])
            assert mock_save.call_count == 3  # 2 textos + 1 áudio
