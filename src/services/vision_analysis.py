"""
[MKT-08] Analise multimodal de imagens — fotos do aluno, avaliacoes fisicas, documentos.

Casos de uso em academias:
  1. Avaliacao fisica por foto — aluno manda foto frontal/lateral, IA sugere objetivo
     de treino (hipertrofia, definicao, mobilidade) com base em postura e aparencia.
  2. Foto de ficha de avaliacao preenchida a mao -> extrair dados estruturados.
  3. Foto de carteirinha/RG para preencher cadastro.
  4. Foto de caixa de remedios -> detecta restricoes medicas (IMPORTANTE: requer LGPD).
  5. Foto de equipamento/ambiente -> responder "que exercicio faco aqui".

Usa Gemini 2.5 Pro (multimodal nativo) atraves do OpenRouter (cliente_ia ja configurado).

IMPORTANTE:
  - Foto de pessoa pode conter dados sensiveis (saude, religiao). Aplicar LGPD:
    consentimento explicito antes de analisar; nao armazenar foto original; apagar
    apos processamento.
  - Nunca tirar conclusoes medicas. Disclaimer sempre presente.

Uso:
    from src.services.vision_analysis import analisar_foto_avaliacao, extrair_dados_ficha

    resultado = await analisar_foto_avaliacao(
        empresa_id=1,
        image_url="https://ik.imagekit.io/...", # ou base64
        contexto="Aluno homem 32 anos, objetivo emagrecer",
    )
    # {"objetivo_sugerido": "emagrecimento", "observacoes": [...], "exercicios_recomendados": [...]}
"""

from __future__ import annotations

from typing import Dict, Optional

from src.core.config import logger
from src.services.llm_service import cliente_ia


VISION_MODEL = "google/gemini-2.5-pro"  # multimodal nativo, state-of-art Google


DISCLAIMER_MEDICO = (
    "Esta analise foi feita por IA e NAO substitui avaliacao profissional. "
    "Para duvidas medicas, consulte um medico ou educador fisico presencialmente."
)


PROMPT_AVALIACAO = """Voce e uma educadora fisica experiente analisando uma foto de aluno para
indicar ponto de partida de treino. Analise aspectos VISUAIS observaveis:
  - Postura geral (inclinacao de ombros, curvatura da coluna visivel)
  - Composicao corporal aparente (compativel com objetivo: hipertrofia, emagrecimento, definicao)
  - Nivel de condicionamento aparente (iniciante vs avancado)

NAO faca:
  - Diagnostico medico
  - Estimativa de peso ou idade com precisao
  - Comentarios sobre aparencia estetica

Retorne JSON:
{
  "objetivo_sugerido": "emagrecimento|hipertrofia|definicao|mobilidade|saude_geral",
  "nivel_sugerido": "iniciante|intermediario|avancado",
  "observacoes_posturais": ["obs1", "obs2"],
  "exercicios_sugeridos_iniciais": ["exercicio1", "exercicio2", "exercicio3"],
  "recomenda_consulta_profissional": true|false,
  "disclaimer_visivel": "texto a mostrar pro aluno"
}
"""


PROMPT_FICHA = """Voce e um OCR especializado em fichas de avaliacao fisica de academia.
Extraia os campos preenchidos a mao ou por computador na imagem.

Retorne JSON com os campos que conseguiu extrair:
{
  "nome": "string",
  "data_nascimento": "YYYY-MM-DD ou null",
  "peso_kg": numero,
  "altura_m": numero,
  "objetivo": "string",
  "restricoes_medicas": ["string"],
  "observacoes": "string",
  "confianca_geral": 0.0-1.0
}

So preencha campos com confianca >= 0.6. Use null para os demais.
"""


async def _call_vision(prompt: str, image_url: str, image_b64: Optional[str] = None) -> Optional[Dict]:
    """Chama o modelo de visao. Aceita URL publica OU base64 data URL."""
    if not cliente_ia:
        logger.error("[MKT-08] cliente_ia nao disponivel")
        return None

    import json as _json

    image_payload = (
        {"type": "image_url", "image_url": {"url": image_url}}
        if image_url else
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
    )

    try:
        resp = await cliente_ia.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        image_payload,
                    ],
                }
            ],
            temperature=0.1,
            max_tokens=800,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        return _json.loads(raw)
    except Exception as e:
        logger.error(f"[MKT-08] vision call falhou: {e}")
        return None


async def analisar_foto_avaliacao(
    empresa_id: int,
    image_url: Optional[str] = None,
    image_b64: Optional[str] = None,
    contexto: str = "",
) -> Optional[Dict]:
    """Analisa foto de avaliacao fisica. Retorna sugestao de objetivo e exercicios iniciais."""
    if not (image_url or image_b64):
        return None

    prompt = PROMPT_AVALIACAO
    if contexto:
        prompt += f"\n\nContexto adicional: {contexto}"

    result = await _call_vision(prompt, image_url or "", image_b64)
    if not result:
        return None

    # Garante disclaimer sempre presente
    if "disclaimer_visivel" not in result or not result.get("disclaimer_visivel"):
        result["disclaimer_visivel"] = DISCLAIMER_MEDICO
    result["empresa_id"] = empresa_id
    return result


async def extrair_dados_ficha(
    empresa_id: int,
    image_url: Optional[str] = None,
    image_b64: Optional[str] = None,
) -> Optional[Dict]:
    """Extrai dados estruturados de uma foto de ficha preenchida."""
    result = await _call_vision(PROMPT_FICHA, image_url or "", image_b64)
    if result:
        result["empresa_id"] = empresa_id
    return result


async def descrever_imagem_generica(
    empresa_id: int,
    image_url: str,
    pergunta_cliente: str = "",
) -> Optional[str]:
    """Fallback para imagens sem contexto especifico (ex: aluno manda foto de
    equipamento perguntando como usar)."""
    prompt = (
        "Descreva a imagem e responda a pergunta do aluno de forma breve e util. "
        "Se for um equipamento de academia, diga que exercicios pode fazer ali. "
        "Se for alimento, diga uma caracteristica nutricional simples. "
        "Se nao souber, responda 'nao sei identificar com seguranca, me pergunte em palavras'."
    )
    if pergunta_cliente:
        prompt += f"\n\nPergunta do aluno: {pergunta_cliente}"

    if not cliente_ia:
        return None

    try:
        resp = await cliente_ia.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            temperature=0.3,
            max_tokens=300,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error(f"[MKT-08] descrever_imagem falhou: {e}")
        return None
