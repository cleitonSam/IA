"""
TTS Service — Converte texto da IA em áudio para WhatsApp.
Usa Gemini TTS (Google) — tier grátis disponível.
Saída: PCM 24kHz 16-bit mono → WAV em memória.

Vozes: 30 vozes neurais, todas suportam PT-BR (GA).
Modelo: gemini-2.5-flash-preview-tts
"""
import asyncio
import io
import re
import wave
from typing import Optional

from src.core.config import GOOGLE_API_KEY, logger

# ──────────────────────────────────────────────
# Cliente Gemini (lazy init para não crashar se
# google-genai não estiver instalado)
# ──────────────────────────────────────────────
_gemini_client = None


def _get_gemini_client():
    """Inicializa o cliente Gemini sob demanda."""
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client
    if not GOOGLE_API_KEY:
        logger.warning("⚠️ TTS indisponível: GOOGLE_API_KEY não configurada")
        return None
    try:
        from google import genai
        _gemini_client = genai.Client(api_key=GOOGLE_API_KEY)
        logger.info("🔊 Cliente Gemini TTS inicializado")
        return _gemini_client
    except Exception as e:
        logger.error(f"❌ Falha ao inicializar Gemini TTS: {e}")
        return None


# ──────────────────────────────────────────────
# Vozes disponíveis (todas suportam PT-BR GA)
# ──────────────────────────────────────────────
VOZES = {
    # Femininas
    "Kore":         {"genero": "feminina", "descricao": "Clara e natural",   "tag": "padrão"},
    "Aoede":        {"genero": "feminina", "descricao": "Suave e acolhedora", "tag": "suave"},
    "Leda":         {"genero": "feminina", "descricao": "Serena e elegante", "tag": "elegante"},
    "Zephyr":       {"genero": "feminina", "descricao": "Expressiva e jovem", "tag": "jovem"},
    "Achernar":     {"genero": "feminina", "descricao": "Firme e profissional", "tag": "profissional"},
    "Despina":      {"genero": "feminina", "descricao": "Amigável e calorosa", "tag": "amigável"},
    "Erinome":      {"genero": "feminina", "descricao": "Dinâmica e enérgica", "tag": "enérgica"},
    "Gacrux":       {"genero": "feminina", "descricao": "Madura e confiante", "tag": "madura"},
    "Laomedeia":    {"genero": "feminina", "descricao": "Calma e ponderada", "tag": "calma"},
    "Pulcherrima":  {"genero": "feminina", "descricao": "Refinada e sofisticada", "tag": "sofisticada"},
    "Sulafat":      {"genero": "feminina", "descricao": "Leve e melodiosa", "tag": "melodiosa"},
    "Vindemiatrix": {"genero": "feminina", "descricao": "Calorosa e empática", "tag": "empática"},
    "Autonoe":      {"genero": "feminina", "descricao": "Objetiva e clara", "tag": "objetiva"},
    "Callirrhoe":   {"genero": "feminina", "descricao": "Gentil e atenciosa", "tag": "gentil"},
    # Masculinas
    "Orus":         {"genero": "masculina", "descricao": "Profissional e seguro", "tag": "profissional"},
    "Charon":       {"genero": "masculina", "descricao": "Grave e autoritário", "tag": "grave"},
    "Puck":         {"genero": "masculina", "descricao": "Jovem e descontraído", "tag": "jovem"},
    "Fenrir":       {"genero": "masculina", "descricao": "Forte e decidido", "tag": "forte"},
    "Enceladus":    {"genero": "masculina", "descricao": "Calmo e confiável", "tag": "calmo"},
    "Iapetus":      {"genero": "masculina", "descricao": "Sóbrio e equilibrado", "tag": "sóbrio"},
    "Umbriel":      {"genero": "masculina", "descricao": "Neutro e versátil", "tag": "neutro"},
    "Algieba":      {"genero": "masculina", "descricao": "Energético e animado", "tag": "energético"},
    "Achird":       {"genero": "masculina", "descricao": "Acolhedor e simpático", "tag": "acolhedor"},
    "Algenib":      {"genero": "masculina", "descricao": "Formal e direto", "tag": "formal"},
    "Alnilam":      {"genero": "masculina", "descricao": "Robusto e profundo", "tag": "profundo"},
    "Rasalgethi":   {"genero": "masculina", "descricao": "Amigável e natural", "tag": "amigável"},
    "Sadachbia":    {"genero": "masculina", "descricao": "Leve e agradável", "tag": "leve"},
    "Sadaltager":   {"genero": "masculina", "descricao": "Maduro e respeitoso", "tag": "maduro"},
    "Schedar":      {"genero": "masculina", "descricao": "Articulado e claro", "tag": "articulado"},
    "Zubenelgenubi": {"genero": "masculina", "descricao": "Tranquilo e receptivo", "tag": "tranquilo"},
}

# Atalhos para seleção rápida
VOZES_ATALHOS = {
    "feminina": "Kore",
    "masculina": "Orus",
}

VOZ_PADRAO = "Kore"

# Texto de preview para cada gênero
PREVIEW_TEXTO = {
    "feminina": "Olá! Eu sou a assistente virtual da sua empresa. Estou aqui para te ajudar com tudo que precisar. Como posso te ajudar hoje?",
    "masculina": "Olá! Eu sou o assistente virtual da sua empresa. Estou aqui para te ajudar com tudo que precisar. Como posso te ajudar hoje?",
}


# ──────────────────────────────────────────────
# Geração de áudio
# ──────────────────────────────────────────────
async def gerar_audio_resposta(
    texto: str,
    voz: str = None,
) -> Optional[bytes]:
    """
    Converte texto em áudio WAV usando Gemini TTS.

    Args:
        texto: Texto para converter (max ~2000 chars recomendado).
        voz: Nome da voz Gemini (ex: 'Kore') ou atalho ('feminina'/'masculina').

    Returns:
        Bytes do WAV ou None se falhar.
    """
    client = _get_gemini_client()
    if not client:
        return None

    if not texto or len(texto.strip()) < 3:
        return None

    # Resolve nome da voz
    voz_final = VOZES_ATALHOS.get(voz, voz) if voz else VOZ_PADRAO
    if voz_final not in VOZES:
        voz_final = VOZ_PADRAO

    # Limpa texto para TTS
    texto_limpo = _limpar_texto_para_tts(texto)
    if not texto_limpo:
        return None

    # Limita tamanho (evita áudios >2min)
    if len(texto_limpo) > 2000:
        texto_limpo = texto_limpo[:2000] + "..."

    # Retry com backoff para rate limits (429)
    max_tentativas = 3
    for tentativa in range(max_tentativas):
        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voz_final,
                        )
                    )
                ),
            )

            # generate_content é síncrono — roda em thread para não bloquear
            response = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-2.5-flash-preview-tts",
                contents=texto_limpo,
                config=config,
            )

            # Extrai PCM raw
            pcm_data = response.candidates[0].content.parts[0].inline_data.data
            if not pcm_data or len(pcm_data) < 100:
                logger.warning("⚠️ TTS retornou áudio vazio/muito curto")
                return None

            # Converte PCM → WAV em memória (24kHz, 16-bit, mono)
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)       # 16-bit
                wf.setframerate(24000)   # 24kHz
                wf.writeframes(pcm_data)

            wav_bytes = wav_buffer.getvalue()
            logger.info(f"🔊 TTS Gemini OK: {len(wav_bytes)} bytes, voz={voz_final}")
            return wav_bytes

        except Exception as e:
            erro_str = str(e)
            if "429" in erro_str or "RESOURCE_EXHAUSTED" in erro_str:
                if tentativa < max_tentativas - 1:
                    wait_time = (tentativa + 1) * 5  # 5s, 10s
                    logger.warning(f"⚠️ TTS rate limit (tentativa {tentativa+1}/{max_tentativas}), aguardando {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"❌ TTS rate limit esgotado após {max_tentativas} tentativas")
                    return None
            logger.error(f"❌ Erro Gemini TTS: {e}")
            return None

    return None


async def gerar_preview_voz(voz: str) -> Optional[bytes]:
    """Gera áudio preview para uma voz específica."""
    info = VOZES.get(voz)
    if not info:
        return None
    genero = info["genero"]
    texto = PREVIEW_TEXTO.get(genero, PREVIEW_TEXTO["feminina"])
    return await gerar_audio_resposta(texto, voz=voz)


def listar_vozes() -> list[dict]:
    """Retorna lista de vozes disponíveis para o frontend."""
    resultado = []
    for nome, info in VOZES.items():
        resultado.append({
            "nome": nome,
            "genero": info["genero"],
            "descricao": info["descricao"],
            "tag": info["tag"],
        })
    return resultado


# ──────────────────────────────────────────────
# Limpeza de texto para TTS
# ──────────────────────────────────────────────
def _limpar_texto_para_tts(texto: str) -> str:
    """Remove formatação WhatsApp e emojis para TTS mais limpo."""
    # Remove emojis
    texto = re.sub(
        r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF'
        r'\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF'
        r'\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002600-\U000026FF'
        r'\U0000FE00-\U0000FE0F\U0000200D]+', '', texto
    )
    # Remove formatação WhatsApp (*bold*, _italic_, ~strike~)
    texto = re.sub(r'\*(.+?)\*', r'\1', texto)
    texto = re.sub(r'_(.+?)_', r'\1', texto)
    texto = re.sub(r'~(.+?)~', r'\1', texto)
    # Remove bullets
    texto = texto.replace('•', ',')
    # Remove URLs
    texto = re.sub(r'https?://\S+', '', texto)
    # Limpa espaços múltiplos
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto
