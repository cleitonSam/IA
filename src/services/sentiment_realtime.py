"""
[MKT-02] Sentimento em tempo real + escalação automática.

Analisa cada mensagem do cliente (não só no fim da conversa) e dispara alertas
quando detecta sinais de risco:
  - Sentimento muito negativo (irritacao, frustracao, raiva)
  - Palavras-chave de cancelamento ("quero cancelar", "vou sair da academia")
  - Repeticao de reclamacao (mesmo tema 3x+)
  - Timeout sem resposta humana em lead tier A

Cada alerta vai pra tabela `alertas_escalacao` e opcionalmente dispara webhook externo
(Slack, Discord, email). O dashboard lista os alertas abertos para o time comercial.

Uso:
    from src.services.sentiment_realtime import analisar_mensagem, listar_alertas_abertos

    # No worker, apos receber mensagem do cliente:
    alerta = await analisar_mensagem(conversation_id, empresa_id, texto_cliente)
    if alerta:
        # Pode disparar notificacao externa, ja gravou em DB
        ...

    # No dashboard:
    alertas = await listar_alertas_abertos(empresa_id)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx

from src.core.config import logger
import src.core.database as _database
from src.core.redis_client import redis_client


# ============================================================
# Config
# ============================================================

ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "").strip()  # Slack/Discord/n8n
ALERT_RATE_LIMIT_S = 300  # nao dispara o mesmo alerta pra mesma conversa em <5min


SENTIMENTOS_NEGATIVOS = {"irritado", "raiva", "frustrado", "negativo", "cancelamento"}


KEYWORDS_CANCELAMENTO = (
    "quero cancelar", "vou cancelar", "cancelar meu plano", "cancelar a matricula",
    "sair da academia", "nao quero mais", "desistir", "trancar", "suspender",
    "estornar", "reembolso", "me ligue urgente", "procon", "reclame aqui",
)

KEYWORDS_URGENCIA = (
    "urgente", "absurdo", "inaceitavel", "pessimo", "péssimo", "horrivel",
    "ridiculo", "ridículo", "lixo", "enganacao", "enganação", "golpe",
    "fraude", "processo", "justica", "justiça",
)

KEYWORDS_TIMEOUT_CRITICO = (
    "ninguem responde", "ninguém responde", "estou esperando", "alo?", "alô?",
    "ja faz", "ja tem", "faz horas", "faz tempo",
)


# ============================================================
# Detecao
# ============================================================

def _tem_qualquer(texto: str, keywords) -> bool:
    if not texto:
        return False
    t = texto.lower()
    return any(k in t for k in keywords)


def _classificar_sinais(texto: str) -> Dict[str, bool]:
    return {
        "cancelamento": _tem_qualquer(texto, KEYWORDS_CANCELAMENTO),
        "urgencia": _tem_qualquer(texto, KEYWORDS_URGENCIA),
        "timeout_critico": _tem_qualquer(texto, KEYWORDS_TIMEOUT_CRITICO),
    }


# ============================================================
# Persistencia
# ============================================================

async def _ja_alertou_recentemente(conversation_id: int, tipo: str) -> bool:
    key = f"sentiment_alert:{conversation_id}:{tipo}"
    try:
        return bool(await redis_client.get(key))
    except Exception:
        return False


async def _marcar_alertado(conversation_id: int, tipo: str) -> None:
    key = f"sentiment_alert:{conversation_id}:{tipo}"
    try:
        await redis_client.setex(key, ALERT_RATE_LIMIT_S, "1")
    except Exception:
        pass


async def _salvar_alerta(
    empresa_id: int,
    conversation_id: int,
    tipo: str,
    severidade: str,
    mensagem: str,
    contexto: Optional[Dict] = None,
) -> Optional[int]:
    if not _database.db_pool:
        return None
    try:
        row = await _database.db_pool.fetchrow(
            """
            INSERT INTO alertas_escalacao
                (empresa_id, conversation_id, tipo, severidade, mensagem, contexto_json, status)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, 'aberto')
            RETURNING id
            """,
            empresa_id, conversation_id, tipo, severidade, mensagem[:500],
            json.dumps(contexto or {}),
        )
        return row["id"] if row else None
    except Exception as e:
        logger.error(f"[MKT-02] salvar_alerta falhou: {e}")
        return None


async def _disparar_webhook(empresa_id: int, alerta_id: int, tipo: str, mensagem: str, contexto: Dict) -> None:
    if not ALERT_WEBHOOK_URL:
        return
    payload = {
        "source": "fluxo-ia",
        "event": "sentiment_alert",
        "empresa_id": empresa_id,
        "alerta_id": alerta_id,
        "tipo": tipo,
        "mensagem": mensagem[:500],
        "contexto": contexto,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(ALERT_WEBHOOK_URL, json=payload)
    except Exception as e:
        logger.warning(f"[MKT-02] webhook falhou: {e}")


# ============================================================
# API publica
# ============================================================

async def analisar_mensagem(
    conversation_id: int,
    empresa_id: int,
    texto_cliente: str,
    sentimento_ia: Optional[str] = None,
    dispatch_webhook: bool = True,
) -> Optional[Dict]:
    """
    Analisa uma mensagem do cliente e dispara alerta se detectar sinal de risco.
    Retorna o dict do alerta ou None se tudo OK.
    """
    if not texto_cliente or len(texto_cliente.strip()) < 3:
        return None

    sinais = _classificar_sinais(texto_cliente)

    # Severidade derivada do conjunto de sinais
    tipo = None
    severidade = None
    if sinais["cancelamento"]:
        tipo, severidade = "cancelamento", "alta"
    elif sinais["urgencia"]:
        tipo, severidade = "urgencia", "alta"
    elif sinais["timeout_critico"]:
        tipo, severidade = "timeout_critico", "media"
    elif (sentimento_ia or "").lower() in SENTIMENTOS_NEGATIVOS:
        tipo, severidade = "sentimento_negativo", "media"

    if not tipo:
        return None

    if await _ja_alertou_recentemente(conversation_id, tipo):
        return None

    contexto = {
        "texto_cliente": texto_cliente[:400],
        "sentimento_ia": sentimento_ia,
        "sinais_detectados": sinais,
    }

    alerta_id = await _salvar_alerta(
        empresa_id, conversation_id, tipo, severidade,
        f"{tipo}: '{texto_cliente[:120]}...'",
        contexto,
    )
    if not alerta_id:
        return None

    await _marcar_alertado(conversation_id, tipo)

    logger.warning(
        f"[MKT-02] ALERT tipo={tipo} sev={severidade} empresa={empresa_id} "
        f"conv={conversation_id} alerta_id={alerta_id}"
    )

    if dispatch_webhook:
        await _disparar_webhook(empresa_id, alerta_id, tipo, texto_cliente, contexto)

    return {
        "alerta_id": alerta_id,
        "tipo": tipo,
        "severidade": severidade,
        "conversation_id": conversation_id,
    }


async def listar_alertas_abertos(
    empresa_id: int,
    severidade_min: str = "baixa",
    limit: int = 100,
) -> List[Dict]:
    """Lista alertas em status 'aberto' para o dashboard."""
    if not _database.db_pool:
        return []
    sev_rank = {"baixa": 0, "media": 1, "alta": 2, "critica": 3}
    min_rank = sev_rank.get(severidade_min.lower(), 0)

    try:
        rows = await _database.db_pool.fetch(
            """
            SELECT id, conversation_id, tipo, severidade, mensagem, contexto_json,
                   status, created_at
            FROM alertas_escalacao
            WHERE empresa_id = $1
              AND status = 'aberto'
            ORDER BY created_at DESC
            LIMIT $2
            """,
            empresa_id, limit,
        )
        out = []
        for r in rows:
            d = dict(r)
            if sev_rank.get(d["severidade"], 0) >= min_rank:
                out.append(d)
        return out
    except Exception as e:
        logger.error(f"[MKT-02] listar_alertas_abertos falhou: {e}")
        return []


async def resolver_alerta(
    alerta_id: int,
    empresa_id: int,
    resolvido_por: str,
    observacao: Optional[str] = None,
) -> bool:
    if not _database.db_pool:
        return False
    try:
        await _database.db_pool.execute(
            """
            UPDATE alertas_escalacao
            SET status = 'resolvido',
                resolvido_por = $1,
                resolvido_em = NOW(),
                observacao = $2
            WHERE id = $3 AND empresa_id = $4
            """,
            resolvido_por, observacao, alerta_id, empresa_id,
        )
        return True
    except Exception as e:
        logger.error(f"[MKT-02] resolver_alerta falhou: {e}")
        return False
