"""
[MKT-01] Lead scoring com ML heuristico evolutivo.

Calcula um score de 0 a 100 para cada conversa/lead indicando probabilidade de fechar matricula.
Mapeia score -> tier (A/B/C/D) para priorizacao do time comercial.

Arquitetura em 2 camadas:
1. Heuristica (inicial, funciona sem dados historicos): combina sinais observaveis com pesos.
2. ML real (quando tiver dados): logistic regression treinada com historico
   conversas -> matriculas. Cruza com o heuristico.

Sinais usados (features):
  - msg_count            numero de mensagens trocadas na conversa
  - perguntou_preco      perguntou sobre plano/valor/mensalidade
  - perguntou_horario    perguntou sobre horarios, agenda, grade de aulas
  - pediu_visita         pediu visita, avaliacao, aula experimental
  - respondeu_nome       deu o nome proprio (lead qualificado minimo)
  - primeira_resposta_ok chegou a primeira_resposta_em em menos de 5 minutos
  - menu_concluido       terminou o fluxo de triagem
  - sentiment_positivo   ultimo sentimento_ia e positivo ou neutro
  - cancelamento_risk    flag cancelamento_detectado = True (NEGATIVO)

Score final:
  - 80-100 -> A (quente, priorizar agora)
  - 60-79  -> B (morno, follow-up 24h)
  - 30-59  -> C (frio, nurture por conteudo)
  - 0-29   -> D (descartar ou re-engajamento longo)

Uso:
    from src.services.lead_scoring import score_conversa, tier_from_score

    score = await score_conversa(conversation_id=123, empresa_id=1)
    tier = tier_from_score(score)
    # score = 84, tier = "A"

Para treinar o modelo real (quando tiver ~500+ conversas com matricula confirmada):
    from src.services.lead_scoring import treinar_modelo
    await treinar_modelo(empresa_id=1)   # salva em data/lead_scoring_empresa_1.json
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

from src.core.config import logger
import src.core.database as _database
from src.core.redis_client import redis_client


# ============================================================
# Constantes
# ============================================================

TIER_THRESHOLDS = {"A": 80, "B": 60, "C": 30}

PESOS_HEURISTICA_DEFAULT = {
    "perguntou_preco": 18,
    "perguntou_horario": 10,
    "pediu_visita": 25,
    "respondeu_nome": 8,
    "primeira_resposta_ok": 6,
    "menu_concluido": 10,
    "sentiment_positivo": 12,
    "msg_count_bonus": 8,          # ate +8 por volume saudavel de msgs
    "cancelamento_penalidade": -40,
    "inativo_bonus_neg": -8,       # sem msgs ha > 48h
}

CACHE_TTL = 300  # 5 min


# ============================================================
# Modelos de dados
# ============================================================

@dataclass
class LeadFeatures:
    conversation_id: int
    empresa_id: int
    msg_count: int = 0
    perguntou_preco: bool = False
    perguntou_horario: bool = False
    pediu_visita: bool = False
    respondeu_nome: bool = False
    primeira_resposta_ok: bool = False
    menu_concluido: bool = False
    sentiment_positivo: bool = False
    cancelamento_risk: bool = False
    horas_desde_ultima_msg: float = 0.0


@dataclass
class LeadScore:
    conversation_id: int
    score: int            # 0-100
    tier: str             # A / B / C / D
    explicacao: List[str] # por que ganhou/perdeu pontos
    features_raw: Dict    # para debugging


# ============================================================
# Extracao de features
# ============================================================

_KEYWORDS_PRECO = (
    "preco", "preço", "valor", "mensalidade", "plano", "quanto", "custa",
    "mensal", "barato", "caro", "r$", "reais", "promocao", "promoção",
)
_KEYWORDS_HORARIO = (
    "horario", "horário", "hora", "abre", "funciona", "funcionamento",
    "manha", "manhã", "tarde", "noite", "madrugada", "aberto", "fechado",
    "final de semana", "sabado", "sábado", "domingo", "grade", "aula",
)
_KEYWORDS_VISITA = (
    "visita", "conhecer", "passar ai", "passar ai", "aula experimental",
    "avaliacao", "avaliação", "tour", "conhecer a unidade", "passar la",
    "passar lá", "ir ai", "ir ai",
)


def _tem_keyword(texto: str, keywords: tuple) -> bool:
    if not texto:
        return False
    t = texto.lower()
    return any(k in t for k in keywords)


async def _extrair_features(conversation_id: int, empresa_id: int) -> Optional[LeadFeatures]:
    """Busca conversa + mensagens e extrai features para scoring."""
    if not _database.db_pool:
        return None

    try:
        conv = await _database.db_pool.fetchrow(
            """
            SELECT id, contato_nome, contato_fone, score_lead, score_interesse,
                   sentimento_ia, cancelamento_detectado, primeira_resposta_em,
                   created_at, updated_at
            FROM conversas
            WHERE conversation_id = $1 AND empresa_id = $2
            """,
            conversation_id, empresa_id,
        )
        if not conv:
            return None

        msgs = await _database.db_pool.fetch(
            """
            SELECT role, conteudo, created_at
            FROM mensagens_locais
            WHERE conversa_id = $1
            ORDER BY created_at
            LIMIT 200
            """,
            conv["id"],
        )

        texto_cliente = " ".join(
            (m["conteudo"] or "") for m in msgs if m["role"] in ("user", "customer", "cliente")
        )

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        primeira = conv.get("primeira_resposta_em")
        primeira_ok = False
        if primeira and conv.get("created_at"):
            try:
                delta = (primeira - conv["created_at"]).total_seconds()
                primeira_ok = 0 < delta < 300  # <5 min
            except Exception:
                primeira_ok = False

        horas_desde = 0.0
        if conv.get("updated_at"):
            try:
                horas_desde = (now - conv["updated_at"]).total_seconds() / 3600.0
            except Exception:
                horas_desde = 0.0

        return LeadFeatures(
            conversation_id=conversation_id,
            empresa_id=empresa_id,
            msg_count=len(msgs),
            perguntou_preco=_tem_keyword(texto_cliente, _KEYWORDS_PRECO),
            perguntou_horario=_tem_keyword(texto_cliente, _KEYWORDS_HORARIO),
            pediu_visita=_tem_keyword(texto_cliente, _KEYWORDS_VISITA),
            respondeu_nome=bool((conv.get("contato_nome") or "").strip()),
            primeira_resposta_ok=primeira_ok,
            menu_concluido=(conv.get("score_interesse") or 0) >= 10,
            sentiment_positivo=(conv.get("sentimento_ia") or "") in ("positivo", "neutro"),
            cancelamento_risk=bool(conv.get("cancelamento_detectado")),
            horas_desde_ultima_msg=horas_desde,
        )
    except Exception as e:
        logger.error(f"[MKT-01] extrair_features falhou conv={conversation_id}: {e}")
        return None


# ============================================================
# Scoring — heuristica
# ============================================================

def _carregar_pesos(empresa_id: int) -> Dict[str, float]:
    """Carrega pesos customizados da empresa (se existirem em disco) ou retorna default."""
    path = f"data/lead_scoring_empresa_{empresa_id}.json"
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
                # Merge com defaults para cobrir novos campos
                return {**PESOS_HEURISTICA_DEFAULT, **saved.get("pesos", {})}
    except Exception as e:
        logger.warning(f"[MKT-01] falha ao carregar pesos empresa={empresa_id}: {e}")
    return dict(PESOS_HEURISTICA_DEFAULT)


def _score_heuristico(f: LeadFeatures, pesos: Dict[str, float]) -> Tuple[int, List[str]]:
    s = 0.0
    exp: List[str] = []

    if f.perguntou_preco:
        s += pesos["perguntou_preco"]
        exp.append(f"+{pesos['perguntou_preco']}: perguntou sobre preco/plano")
    if f.perguntou_horario:
        s += pesos["perguntou_horario"]
        exp.append(f"+{pesos['perguntou_horario']}: perguntou sobre horario/grade")
    if f.pediu_visita:
        s += pesos["pediu_visita"]
        exp.append(f"+{pesos['pediu_visita']}: pediu visita ou aula experimental (FORTE)")
    if f.respondeu_nome:
        s += pesos["respondeu_nome"]
        exp.append(f"+{pesos['respondeu_nome']}: deu o nome")
    if f.primeira_resposta_ok:
        s += pesos["primeira_resposta_ok"]
        exp.append(f"+{pesos['primeira_resposta_ok']}: primeira resposta em <5min")
    if f.menu_concluido:
        s += pesos["menu_concluido"]
        exp.append(f"+{pesos['menu_concluido']}: completou menu de triagem")
    if f.sentiment_positivo:
        s += pesos["sentiment_positivo"]
        exp.append(f"+{pesos['sentiment_positivo']}: sentimento positivo/neutro")

    # msg count — curva logaritmica ate +pesos["msg_count_bonus"]
    if f.msg_count > 0:
        bonus = min(pesos["msg_count_bonus"], math.log(1 + f.msg_count) * 2)
        s += bonus
        exp.append(f"+{bonus:.1f}: {f.msg_count} msgs trocadas")

    if f.cancelamento_risk:
        s += pesos["cancelamento_penalidade"]
        exp.append(f"{pesos['cancelamento_penalidade']}: risco de cancelamento detectado")

    if f.horas_desde_ultima_msg > 48:
        s += pesos["inativo_bonus_neg"]
        exp.append(f"{pesos['inativo_bonus_neg']}: inativo ha {f.horas_desde_ultima_msg:.0f}h")

    # Clamp 0-100
    score = max(0, min(100, int(round(s))))
    return score, exp


# ============================================================
# Scoring — ML (quando houver modelo treinado)
# ============================================================

def _carregar_modelo_ml(empresa_id: int) -> Optional[Dict]:
    """Carrega coeficientes de logistic regression se existirem (data/*.json)."""
    path = f"data/lead_model_empresa_{empresa_id}.json"
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[MKT-01] modelo ML indisponivel empresa={empresa_id}: {e}")
    return None


def _sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def _score_ml(f: LeadFeatures, modelo: Dict) -> Optional[int]:
    """Aplica logistic regression treinado. Retorna score 0-100."""
    try:
        coef = modelo.get("coef", {})
        intercept = float(modelo.get("intercept", 0.0))
        vec = {
            "msg_count": float(f.msg_count),
            "perguntou_preco": 1.0 if f.perguntou_preco else 0.0,
            "perguntou_horario": 1.0 if f.perguntou_horario else 0.0,
            "pediu_visita": 1.0 if f.pediu_visita else 0.0,
            "respondeu_nome": 1.0 if f.respondeu_nome else 0.0,
            "primeira_resposta_ok": 1.0 if f.primeira_resposta_ok else 0.0,
            "menu_concluido": 1.0 if f.menu_concluido else 0.0,
            "sentiment_positivo": 1.0 if f.sentiment_positivo else 0.0,
            "cancelamento_risk": 1.0 if f.cancelamento_risk else 0.0,
        }
        z = intercept + sum(coef.get(k, 0.0) * v for k, v in vec.items())
        prob = _sigmoid(z)
        return int(round(prob * 100))
    except Exception as e:
        logger.warning(f"[MKT-01] score_ml falhou: {e}")
        return None


# ============================================================
# API publica
# ============================================================

def tier_from_score(score: int) -> str:
    if score >= TIER_THRESHOLDS["A"]:
        return "A"
    if score >= TIER_THRESHOLDS["B"]:
        return "B"
    if score >= TIER_THRESHOLDS["C"]:
        return "C"
    return "D"


async def score_conversa(
    conversation_id: int,
    empresa_id: int,
    use_cache: bool = True,
    persist: bool = True,
) -> Optional[LeadScore]:
    """Calcula score de uma conversa. Usa ML se treinado + heuristica sempre."""
    cache_key = f"{empresa_id}:lead_score:{conversation_id}"
    if use_cache:
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                data = json.loads(cached)
                return LeadScore(**data)
        except Exception:
            pass

    features = await _extrair_features(conversation_id, empresa_id)
    if not features:
        return None

    pesos = _carregar_pesos(empresa_id)
    score_h, exp_h = _score_heuristico(features, pesos)

    modelo = _carregar_modelo_ml(empresa_id)
    score_ml = _score_ml(features, modelo) if modelo else None

    # Se tem ML, combina 60% ML + 40% heuristica; senao usa so heuristica
    if score_ml is not None:
        final_score = int(round(0.6 * score_ml + 0.4 * score_h))
        exp_h.insert(0, f"score_combinado = 0.6*ml({score_ml}) + 0.4*heuristica({score_h}) = {final_score}")
    else:
        final_score = score_h

    result = LeadScore(
        conversation_id=conversation_id,
        score=final_score,
        tier=tier_from_score(final_score),
        explicacao=exp_h,
        features_raw=asdict(features),
    )

    # Persiste no banco (tabela conversas.score_lead) + cache
    if persist and _database.db_pool:
        try:
            await _database.db_pool.execute(
                "UPDATE conversas SET score_lead = $1 WHERE conversation_id = $2 AND empresa_id = $3",
                final_score, conversation_id, empresa_id,
            )
        except Exception as e:
            logger.warning(f"[MKT-01] falha ao persistir score: {e}")

    try:
        await redis_client.setex(
            cache_key, CACHE_TTL, json.dumps({
                "conversation_id": result.conversation_id,
                "score": result.score,
                "tier": result.tier,
                "explicacao": result.explicacao,
                "features_raw": result.features_raw,
            })
        )
    except Exception:
        pass

    return result


async def listar_leads_por_tier(
    empresa_id: int,
    tier: str = "A",
    limit: int = 50,
) -> List[Dict]:
    """Lista leads de um tier especifico, ordenados por recencia."""
    if not _database.db_pool:
        return []

    thresholds_min = {"A": 80, "B": 60, "C": 30, "D": 0}
    thresholds_max = {"A": 101, "B": 80, "C": 60, "D": 30}
    tier = tier.upper()
    s_min = thresholds_min.get(tier, 0)
    s_max = thresholds_max.get(tier, 101)

    try:
        rows = await _database.db_pool.fetch(
            """
            SELECT conversation_id, contato_nome, contato_fone,
                   score_lead, sentimento_ia, updated_at
            FROM conversas
            WHERE empresa_id = $1
              AND score_lead >= $2
              AND score_lead < $3
              AND cancelamento_detectado = false
            ORDER BY score_lead DESC, updated_at DESC
            LIMIT $4
            """,
            empresa_id, s_min, s_max, limit,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"[MKT-01] listar_leads_por_tier falhou: {e}")
        return []


async def treinar_modelo(empresa_id: int, min_samples: int = 200) -> Optional[Dict]:
    """Treina logistic regression simples com historico de conversas -> matriculas.
    Requer que a tabela conversas tenha coluna matriculado (bool) ou equivalent.
    Salva em data/lead_model_empresa_<id>.json."""
    # Implementacao minima — produz coeficientes placeholder.
    # Em producao: usar numpy/sklearn; aqui mantemos sem depencencias pesadas.
    if not _database.db_pool:
        return None

    logger.info(f"[MKT-01] Stub: treinar_modelo empresa={empresa_id} requer coluna 'matriculado' em conversas e min {min_samples} samples com outcome conhecido.")

    # Coeficientes razoaveis derivados de intuicao de negocio fitness (baseline)
    modelo = {
        "empresa_id": empresa_id,
        "trained_at": None,
        "n_samples": 0,
        "intercept": -2.0,
        "coef": {
            "msg_count":            0.08,
            "perguntou_preco":      1.2,
            "perguntou_horario":    0.6,
            "pediu_visita":         1.8,
            "respondeu_nome":       0.4,
            "primeira_resposta_ok": 0.35,
            "menu_concluido":       0.7,
            "sentiment_positivo":   0.9,
            "cancelamento_risk":    -3.5,
        },
        "notes": "baseline heuristico — substitua por modelo treinado de verdade quando houver dados de outcome",
    }

    os.makedirs("data", exist_ok=True)
    path = f"data/lead_model_empresa_{empresa_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(modelo, f, indent=2)
    logger.info(f"[MKT-01] modelo baseline salvo em {path}")
    return modelo
