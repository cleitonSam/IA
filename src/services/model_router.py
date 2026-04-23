"""
[AI-UPGRADE] Multi-Model Router — roteia perguntas para o melhor modelo custo/qualidade.

Stack Gemini 2.5 (Google) — abril 2026:

  LITE    — gemini-2.5-flash-lite   (saudacao, horario, endereco — rapido e barato)
  PADRAO  — gemini-2.5-flash        (conversacao geral — sweet spot de custo/qualidade)
  POTENTE — gemini-2.5-pro          (objecoes complexas, cancelamento, negociacao)
  VISION  — gemini-2.5-pro          (multimodal nativo, state-of-art em 2026)
  CLASSIFIER — gemini-2.5-flash-lite (classificacao interna: sentiment, intent)

Override por empresa: se a personalidade tem modelo configurado, ele prevalece no PADRAO.
Override por env: MODELO_PADRAO_OVERRIDE=google/gemini-2.5-pro (por exemplo)
"""
from typing import Optional
from datetime import datetime
from zoneinfo import ZoneInfo
import os

from src.core.config import logger


# Intenções que podem usar modelo lite (perguntas factuais simples)
INTENCOES_LITE = {
    "horario", "endereco", "localizacao", "contato",
    "saudacao", "despedida", "agradecimento",
    "funcionamento", "estacionamento",
}

# Intenções que precisam do modelo potente (vendas complexas)
INTENCOES_POTENTES = {
    "planos", "precos", "comparar", "objecao",
    "cancelamento", "reclamacao", "negociacao",
    "matricula", "contrato", "regulamento",
}

# Palavras que indicam complexidade alta
PALAVRAS_COMPLEXIDADE_ALTA = {
    "diferença entre", "comparar", "qual o melhor",
    "por que devo", "vantagem", "desvantagem",
    "não sei se", "estou em dúvida", "não tenho certeza",
    "reclamação", "insatisfeito", "problema",
    "cancelar", "desistir", "trocar de plano",
    "regulamento", "contrato", "multa", "fidelidade",
}

# ============================================================
# Modelos — Gemini 2.5 series (2026)
# ============================================================

MODELO_LITE    = os.getenv("MODELO_LITE",    "google/gemini-2.5-flash-lite")
MODELO_PADRAO  = os.getenv("MODELO_PADRAO",  "google/gemini-2.5-flash")
MODELO_POTENTE = os.getenv("MODELO_POTENTE", "google/gemini-2.5-pro")
MODELO_VISION  = os.getenv("MODELO_VISION",  "google/gemini-2.5-pro")

# Modelo barato para tarefas internas de classificacao (sentimento, intent triage)
# — NAO sao respostas ao cliente, entao usa modelo custo-efetivo.
MODELO_CLASSIFIER = os.getenv("MODELO_CLASSIFIER", "google/gemini-2.5-flash-lite")

# Override por env para urgencia (ex: "forca tudo pra gemini-2.5-pro por 1 dia")
MODELO_PADRAO_OVERRIDE = os.getenv("MODELO_PADRAO_OVERRIDE", "").strip() or None


def _is_horario_economico() -> bool:
    """
    Detecta se estamos no horário econômico (00:00–05:59 BRT).
    Nesse período o custo de API é ~35% menor — podemos usar modelos melhores
    sem impacto significativo no orçamento.
    """
    try:
        hora = datetime.now(ZoneInfo("America/Sao_Paulo")).hour
        return hora < 6
    except Exception:
        return False


def escolher_modelo(
    intencao: Optional[str],
    texto_cliente: str,
    modelo_personalidade: Optional[str] = None,
    tem_imagens: bool = False,
    total_mensagens: int = 0,
) -> str:
    """
    Escolhe o modelo mais eficiente com base na intenção e complexidade.

    Args:
        intencao: Intenção detectada (horario, planos, etc.)
        texto_cliente: Texto completo do cliente para análise
        modelo_personalidade: Modelo configurado na personalidade da IA
        tem_imagens: Se a mensagem contém imagens
        total_mensagens: Total de mensagens na conversa

    Returns:
        Model ID string para OpenRouter
    """
    # Regra 0: Horário econômico (madrugada) — upgrade gratuito para qualidade
    # Custo de API é ~35% menor entre 00:00–05:59 BRT
    if _is_horario_economico() and intencao not in INTENCOES_LITE and not tem_imagens:
        logger.debug("🌙 ModelRouter: horário econômico → upgrade para POTENTE")
        return MODELO_POTENTE

    # Regra 1: Imagens sempre usam o modelo multimodal (Gemini 2.5 Pro em 2026)
    if tem_imagens:
        return MODELO_VISION

    # Regra 2: Intenção conhecida → roteamento direto
    if intencao:
        if intencao in INTENCOES_LITE:
            logger.debug(f"🔀 ModelRouter: {intencao} → LITE")
            return MODELO_LITE

        if intencao in INTENCOES_POTENTES:
            logger.debug(f"🔀 ModelRouter: {intencao} → POTENTE")
            return MODELO_POTENTE

    # Regra 3: Análise de complexidade do texto
    texto_lower = (texto_cliente or "").lower()

    for palavra in PALAVRAS_COMPLEXIDADE_ALTA:
        if palavra in texto_lower:
            logger.debug(f"🔀 ModelRouter: complexidade alta ('{palavra}') → POTENTE")
            return MODELO_POTENTE

    # Regra 4: Mensagens curtas sem intenção clara → lite
    if len(texto_lower.strip()) < 30 and total_mensagens < 3:
        return MODELO_LITE

    # Regra 5: Conversas longas (muitas msgs) → modelo padrão/potente
    if total_mensagens > 15:
        return MODELO_POTENTE

    # Regra 6: Override global (ex: forca todo mundo pra Opus por 1 dia)
    if MODELO_PADRAO_OVERRIDE:
        return MODELO_PADRAO_OVERRIDE

    # Regra 7: Modelo configurado na personalidade (fallback)
    if modelo_personalidade:
        return modelo_personalidade

    # Default: modelo padrao (Gemini 2.5 Flash em 2026)
    return MODELO_PADRAO
