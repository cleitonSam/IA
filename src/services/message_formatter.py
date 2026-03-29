"""
message_formatter.py — Formatting, transcription, and media processing.

Handles:
- Plan formatting for WhatsApp display
- Text block splitting for message delivery
- Audio transcription (Whisper + Gemini fallback)
- Media download with retry
- LLM response parsing and cleanup
- Attachment processing from buffered messages
"""
import io
import re
import json
import base64
import asyncio
from typing import Optional, List, Dict, Any

import httpx
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

from src.core.config import logger, PROMETHEUS_OK, METRIC_ERROS_TOTAL
from src.utils.text_helpers import normalizar, limpar_markdown
from src.services.llm_service import cliente_ia, cliente_whisper
from src.services.ia_processor import whisper_semaphore
import src.services.chatwoot_client as _chatwoot_module


# ── Formatação de Planos ──────────────────────────────────────────────────────

def formatar_planos_bonito(planos: List[Dict], destacar_melhor_preco: bool = True) -> List[str]:
    """
    Formata os planos de forma bonita para envio ao cliente via WhatsApp/Chatwoot.
    Retorna uma LISTA de strings — cada item = uma mensagem separada no chat.
    """
    if not planos:
        return ["Não temos planos disponíveis no momento. 😕"]

    _EMOJIS_PLANO = ["🏋️", "💪", "⚡", "🔥", "🎯", "🌟"]

    blocos: List[str] = []

    planos_ordenados = list(planos)
    if destacar_melhor_preco:
        def _valor_plano(item: Dict[str, Any]) -> float:
            raw = item.get('valor_promocional') if item.get('valor_promocional') not in (None, "") else item.get('valor')
            try:
                v = float(raw)
                return v if v > 0 else 999999.0
            except (TypeError, ValueError):
                return 999999.0

        planos_ordenados.sort(key=_valor_plano)

    for idx, p in enumerate(planos_ordenados):
        nome = p.get('nome', 'Plano')
        link = p.get('link_venda', '') or ''

        if not link.strip():
            continue

        # ── Valores ──────────────────────────────────────────────────
        try:
            valor_float = float(p['valor']) if p.get('valor') is not None else None
        except (TypeError, ValueError):
            valor_float = None

        try:
            promo_float = float(p['valor_promocional']) if p.get('valor_promocional') is not None else None
        except (TypeError, ValueError):
            promo_float = None

        meses_promo = p.get('meses_promocionais')

        # ── Diferenciais ─────────────────────────────────────────────
        diferenciais = p.get('diferenciais') or []
        if isinstance(diferenciais, str):
            try:
                diferenciais = json.loads(diferenciais)
            except (json.JSONDecodeError, ValueError):
                diferenciais = [d.strip() for d in diferenciais.split(',') if d.strip()]
        if not isinstance(diferenciais, list):
            diferenciais = []

        # ── Pitch/descrição ──────────────────────────────────────────
        _pitch_raw = (
            p.get('descricao') or
            p.get('pitch') or
            p.get('slogan') or
            ""
        )
        _pitch_raw = str(_pitch_raw).strip()
        _e_codigo = (
            _pitch_raw == _pitch_raw.upper()
            or normalizar(_pitch_raw) == normalizar(nome)
            or len(_pitch_raw) < 10
        )
        pitch = None if _e_codigo or not _pitch_raw else _pitch_raw

        emoji = _EMOJIS_PLANO[idx % len(_EMOJIS_PLANO)]

        # ── Montagem do bloco ────────────────────────────────────────
        linhas: List[str] = []

        _selo = " 🏆 *MELHOR CUSTO-BENEFÍCIO*" if destacar_melhor_preco and idx == 0 else ""
        linhas.append(f"{emoji} *{nome}*{_selo}")

        if pitch:
            linhas.append("")
            linhas.append(pitch)

        if diferenciais:
            linhas.append("")
            linhas.append("Você terá acesso a:")
            linhas.append("")
            for dif in diferenciais:
                linhas.append(f"• {str(dif).strip()}")
            linhas.append("")
            linhas.append("Tudo isso por apenas:")
            linhas.append("")
        else:
            linhas.append("")

        if valor_float and valor_float > 0:
            valor_fmt = f"{valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            linhas.append(f"💰 *R${valor_fmt} por mês*")
        else:
            linhas.append("💰 *Consulte o valor*")

        if promo_float and promo_float > 0 and meses_promo:
            promo_fmt = f"{promo_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            linhas.append("")
            linhas.append(f"⚡ *Oferta: {meses_promo}x R${promo_fmt}/mês*")

        linhas.append("")
        linhas.append("👉 Comece agora:")
        linhas.append(link.strip())

        blocos.append("\n".join(linhas))

    if not blocos:
        return ["Não temos planos disponíveis no momento. 😕"]

    blocos[-1] += "\n\nQuer saber mais sobre algum plano ou tirar alguma dúvida? 😊"

    return blocos


# ── Divisão de Texto ──────────────────────────────────────────────────────────

def dividir_em_blocos(texto: str, max_chars: int = 350) -> list:
    """Divide resposta em blocos curtos para enviar como mensagens separadas no WhatsApp.
    1) Separa por parágrafo (\\n\\n)
    2) Blocos longos: quebra por sentença respeitando max_chars
    3) Blocos muito curtos (<40 chars): junta com o anterior
    """
    if not texto:
        return []

    blocos = [p.strip() for p in texto.split('\n\n') if p.strip()]

    resultado = []
    for bloco in blocos:
        if len(bloco) <= max_chars:
            resultado.append(bloco)
        else:
            sentencas = re.split(r'(?<=[.!?])\s+', bloco)
            chunk = ""
            for s in sentencas:
                if chunk and len(chunk) + len(s) + 1 > max_chars:
                    resultado.append(chunk.strip())
                    chunk = s
                else:
                    chunk = f"{chunk} {s}".strip() if chunk else s
            if chunk:
                resultado.append(chunk.strip())

    final = []
    for b in resultado:
        if final and len(b) < 40 and len(final[-1]) < 200:
            final[-1] = f"{final[-1]}\n\n{b}"
        else:
            final.append(b)

    return final if final else [texto.strip()]


# ── JSON Utils ────────────────────────────────────────────────────────────────

def extrair_json(texto: str) -> str:
    """Extrai o primeiro objeto JSON de um texto."""
    texto = texto.strip()
    inicio = texto.find('{')
    fim = texto.rfind('}')
    if inicio != -1 and fim != -1 and fim > inicio:
        return texto[inicio:fim + 1]
    return texto


def corrigir_json(texto: str) -> str:
    """Remove markdown code fences e extrai JSON."""
    texto = texto.strip()
    texto = re.sub(r'^```(?:json)?\s*', '', texto)
    texto = re.sub(r'\s*```$', '', texto)
    texto = extrair_json(texto)
    return texto


# ── Transcrição de Áudio ─────────────────────────────────────────────────────

async def _transcrever_via_gemini(audio_bytes: bytes, mime_type: str = "audio/ogg") -> Optional[str]:
    """
    Fallback: transcreve áudio via Gemini (OpenRouter) quando Whisper não está disponível.
    Usa input_audio (formato OpenRouter) com base64.
    Custo: ~$0.001 por transcrição (gemini-2.0-flash-lite).
    """
    try:
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        fmt_map = {
            "audio/ogg": "ogg", "audio/opus": "ogg", "audio/mpeg": "mp3",
            "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav",
            "audio/mp4": "m4a", "audio/m4a": "m4a", "audio/aac": "aac",
            "audio/flac": "flac", "audio/webm": "ogg",
        }
        fmt = fmt_map.get(mime_type, "ogg")

        result = await cliente_ia.chat.completions.create(
            model="google/gemini-2.0-flash-lite",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": audio_b64, "format": fmt}
                    },
                    {
                        "type": "text",
                        "text": (
                            "Transcreva o áudio acima literalmente em português brasileiro. "
                            "Retorne APENAS o texto falado, sem comentários, descrições ou formatação."
                        )
                    }
                ]
            }],
            max_tokens=500,
            temperature=0.1,
        )

        text = (result.choices[0].message.content or "").strip()
        if text:
            logger.info(f"🎙️ Áudio transcrito via Gemini ({len(text)} chars)")
            return text
        return None
    except Exception as e:
        logger.error(f"❌ Erro transcrição Gemini: {e}")
        return None


async def transcrever_audio(url: str):
    """
    Transcreve áudio com duplo fallback:
    1. OpenAI Whisper (melhor qualidade, requer OPENAI_API_KEY)
    2. Gemini via OpenRouter (funciona sem chave extra)
    """
    try:
        resp = await baixar_midia_com_retry(url, timeout=15.0)
        audio_bytes = resp.content
        content_type = resp.headers.get("content-type", "audio/ogg").split(";")[0].strip()
    except httpx.TimeoutException as e:
        logger.error(f"⏱️ Timeout ao baixar áudio: {e}")
        if PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="audio_download_timeout").inc()
        return "[Erro ao baixar áudio: timeout]"
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ HTTP {e.response.status_code} ao baixar áudio: {e}")
        if PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="audio_download_http").inc()
        return "[Erro ao baixar áudio]"
    except Exception as e:
        logger.error(f"❌ Erro ao baixar áudio: {e}")
        return "[Erro ao baixar áudio]"

    # Tenta Whisper (prioridade)
    if cliente_whisper:
        async with whisper_semaphore:
            try:
                audio_file = io.BytesIO(audio_bytes)
                audio_file.name = "audio.ogg"
                transcription = await cliente_whisper.audio.transcriptions.create(
                    model="whisper-1", file=audio_file
                )
                if transcription.text:
                    logger.info(f"🎙️ Áudio transcrito via Whisper ({len(transcription.text)} chars)")
                    return transcription.text
            except Exception as e:
                logger.warning(f"⚠️ Whisper falhou, tentando Gemini: {e}")
                if PROMETHEUS_OK:
                    METRIC_ERROS_TOTAL.labels(tipo="whisper_error").inc()

    # Fallback Gemini
    gemini_text = await _transcrever_via_gemini(audio_bytes, content_type)
    if gemini_text:
        return gemini_text

    logger.error("❌ Transcrição falhou em todos os métodos (Whisper + Gemini)")
    if PROMETHEUS_OK:
        METRIC_ERROS_TOTAL.labels(tipo="transcricao_total_fail").inc()
    return "[Não foi possível transcrever o áudio]"


@retry(
    wait=wait_exponential(multiplier=0.5, min=1, max=4),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError)),
    reraise=True,
)
async def baixar_midia_com_retry(url: str, timeout: float = 15.0, headers: Optional[Dict[str, str]] = None) -> httpx.Response:
    """Baixa mídia com retry para mitigar falhas transitórias de rede/provedor."""
    resp = await _chatwoot_module.http_client.get(
        url,
        headers=headers,
        follow_redirects=True,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp


# ── Processamento de Anexos ───────────────────────────────────────────────────

async def processar_anexos_mensagens(mensagens_acumuladas: List[str]) -> Dict[str, Any]:
    """Extrai textos, transcrições e imagens a partir das mensagens acumuladas."""
    textos, tasks_audio, imagens_urls = [], [], []
    for m_json in mensagens_acumuladas:
        m = json.loads(m_json)
        if m.get("text"):
            textos.append(m["text"])
        for f in m.get("files", []):
            if f["type"] == "audio":
                tasks_audio.append(transcrever_audio(f["url"]))
            elif f["type"] == "image":
                imagens_urls.append(f["url"])

    transcricoes = await asyncio.gather(*tasks_audio)

    mensagens_lista = []
    for i, txt in enumerate(textos, 1):
        mensagens_lista.append(f"{i}. {txt}")
    for i, transc in enumerate(transcricoes, len(textos) + 1):
        mensagens_lista.append(f"{i}. [Áudio] {transc}")

    return {
        "textos": textos,
        "transcricoes": transcricoes,
        "imagens_urls": imagens_urls,
        "mensagens_formatadas": "\n".join(mensagens_lista) if mensagens_lista else "",
    }


# ── Limpeza de Resposta LLM ──────────────────────────────────────────────────

_TAG_MIDIA_RE = re.compile(r'<SEND_(?:VIDEO|IMAGE)(?::[^>]*)?>')


_ABREVIACOES = {'dr', 'dra', 'sr', 'sra', 'av', 'prof', 'eng', 'arq', 'min', 'máx', 'max', 'tel', 'cel', 'nº', 'etc', 'ex', 'obs', 'ref', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'sab', 'dom', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'}

def garantir_frase_completa(txt: str) -> str:
    """Garante que o texto termina com uma frase completa (sem corte abrupto)."""
    if not txt:
        return txt
    txt = txt.strip()
    if txt[-1] in '.!?😊💪✅🏋🎯✨🔥':
        return txt

    # Busca o último ponto final real (não abreviação) para cortar
    for _sep in ['. ', '! ', '? ', '!\n', '?\n', '.\n']:
        _pos = txt.rfind(_sep)
        if _pos > len(txt) * 0.3:
            # Verifica se o "." é de abreviação (ex: "Av. Dr." não é fim de frase)
            if _sep.startswith('.'):
                _before = txt[:_pos].rstrip()
                _last_word = _before.split()[-1].lower().rstrip('.') if _before.split() else ""
                if _last_word in _ABREVIACOES:
                    # É abreviação — tenta encontrar um ponto anterior
                    _pos2 = txt.rfind(_sep, 0, _pos)
                    if _pos2 > len(txt) * 0.3:
                        _before2 = txt[:_pos2].rstrip()
                        _lw2 = _before2.split()[-1].lower().rstrip('.') if _before2.split() else ""
                        if _lw2 not in _ABREVIACOES:
                            return txt[:_pos2 + 1].strip()
                    continue  # Pula essa posição de abreviação
            return txt[:_pos + 1].strip()
    return txt


def limpar_resposta_llm(resposta_bruta: str, estado_atual: str) -> Dict[str, Any]:
    """
    Limpa a resposta bruta do LLM:
    1. Remove markdown
    2. Parseia formato JSON legado
    3. Extrai tags de mídia (<SEND_VIDEO>, <SEND_IMAGE>)
    4. Garante frase completa
    5. Reanexa tags de mídia
    6. Detecta estado emocional

    Retorna dict com: resposta_texto, novo_estado
    """
    resposta_texto = limpar_markdown(resposta_bruta.strip())

    # Parse JSON legado
    if resposta_texto.startswith('{'):
        try:
            _dados_legado = json.loads(corrigir_json(resposta_texto))
            resposta_texto = limpar_markdown(_dados_legado.get("resposta", resposta_texto))
            estado_atual = _dados_legado.get("estado", estado_atual).strip().lower()
        except (json.JSONDecodeError, ValueError):
            pass

    # Extrai tags de mídia ANTES de cortar frases
    _tags_midia = _TAG_MIDIA_RE.findall(resposta_texto or '')
    if _tags_midia:
        resposta_texto = _TAG_MIDIA_RE.sub('', resposta_texto).strip()

    resposta_texto = garantir_frase_completa(resposta_texto)

    # Reanexa tags de mídia ao final
    if _tags_midia:
        resposta_texto = resposta_texto + ' ' + ' '.join(_tags_midia)

    # Detecta estado emocional da resposta
    _resp_norm = normalizar(resposta_texto)
    if any(w in _resp_norm for w in ("matricula", "matricular", "assinar", "plano", "checkout", "comecar agora")):
        novo_estado = "conversao"
    elif any(w in _resp_norm for w in ("parabens", "que otimo", "incrivel", "adorei", "perfeito")):
        novo_estado = "animado"
    elif any(w in _resp_norm for w in ("entendo", "compreendo", "preocupo", "problema", "dificuldade")):
        novo_estado = "hesitante"
    elif any(w in _resp_norm for w in ("interesse", "quero saber", "me conta", "curioso")):
        novo_estado = "interessado"
    else:
        novo_estado = estado_atual

    return {
        "resposta_texto": resposta_texto,
        "novo_estado": novo_estado,
    }
