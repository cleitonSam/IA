"""
WebSocket endpoint para métricas em tempo real do Dashboard.
Envia dados atualizados a cada N segundos para o frontend.
"""
import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import JWTError, jwt

from src.core.config import logger, JWT_SECRET_KEY, ALGORITHM
from src.core.redis_client import redis_client
from src.services.db_queries import _database

router = APIRouter(tags=["websocket"])


async def _validate_ws_token(token: str) -> dict | None:
    """Valida JWT para conexão WebSocket."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        if not payload.get("sub"):
            return None
        return payload
    except JWTError:
        return None


async def _get_realtime_metrics(empresa_id: int) -> dict:
    """Coleta métricas em tempo real do Redis + PostgreSQL."""
    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    hoje = agora.date()

    try:
        # 1. Conversas ativas (com IA ativa nas últimas 24h via Redis)
        conversas_ativas = 0
        async for key in redis_client.scan_iter(f"{empresa_id}:estado:*", count=200):
            conversas_ativas += 1

        # 2. Conversas pausadas
        conversas_pausadas = 0
        async for key in redis_client.scan_iter(f"pause_ia:{empresa_id}:*", count=200):
            conversas_pausadas += 1

        # 3. Circuit Breaker status
        cb_state = await redis_client.get("cb:LLM_GLOBAL:state")
        cb_state = cb_state.decode() if isinstance(cb_state, (bytes, bytearray)) else (cb_state or "CLOSED")

        # 4. Métricas do dia do PostgreSQL
        row = await _database.db_pool.fetchrow("""
            SELECT
                COUNT(DISTINCT c.id) AS conversas_hoje,
                COUNT(DISTINCT CASE WHEN c.lead_qualificado THEN c.id END) AS leads_hoje,
                COUNT(DISTINCT CASE WHEN c.intencao_de_compra THEN c.id END) AS intencao_hoje,
                COALESCE(AVG(
                    EXTRACT(EPOCH FROM (c.primeira_resposta_em - c.primeira_mensagem))
                ) FILTER (WHERE c.primeira_resposta_em IS NOT NULL AND c.primeira_mensagem IS NOT NULL), 0) AS tempo_resp_medio
            FROM conversas c
            WHERE c.empresa_id = $1
              AND DATE(c.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $2
        """, empresa_id, hoje)

        # 5. Eventos funil do dia
        row_funil = await _database.db_pool.fetchrow("""
            SELECT
                COUNT(DISTINCT CASE WHEN ef.tipo_evento = 'link_matricula_enviado' THEN ef.conversa_id END) AS links_enviados,
                COUNT(DISTINCT CASE WHEN ef.tipo_evento = 'plano_exibido' THEN ef.conversa_id END) AS planos_exibidos,
                COUNT(DISTINCT CASE WHEN ef.tipo_evento IN ('matricula_realizada','checkout_concluido') THEN ef.conversa_id END) AS matriculas,
                COUNT(DISTINCT CASE WHEN ef.tipo_evento = 'escalacao_sentimento' THEN ef.conversa_id END) AS escalacoes
            FROM eventos_funil ef
            JOIN conversas c ON c.id = ef.conversa_id
            WHERE c.empresa_id = $1
              AND DATE(ef.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $2
        """, empresa_id, hoje)

        # 6. Uso de IA do dia
        row_ia = await _database.db_pool.fetchrow("""
            SELECT
                COALESCE(SUM(tokens_prompt + tokens_completion), 0) AS tokens_hoje,
                COALESCE(SUM(custo_usd), 0) AS custo_hoje,
                COUNT(*) AS chamadas_ia_hoje
            FROM uso_ia
            WHERE empresa_id = $1
              AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $2
        """, empresa_id, hoje)

        # 7. Sentimento médio (do Redis se disponível)
        sentimento_counts = {"positivo": 0, "neutro": 0, "frustrado": 0, "irritado": 0}
        async for key in redis_client.scan_iter(f"{empresa_id}:sentimento_hist:*", count=200):
            val = await redis_client.get(key)
            if val:
                val_str = val.decode() if isinstance(val, bytes) else val
                try:
                    hist = json.loads(val_str)
                    if isinstance(hist, list) and hist:
                        ultimo = hist[-1] if isinstance(hist[-1], str) else "neutro"
                        if ultimo in sentimento_counts:
                            sentimento_counts[ultimo] += 1
                except (json.JSONDecodeError, TypeError):
                    pass

        metrics = dict(row) if row else {}
        funil = dict(row_funil) if row_funil else {}
        ia = dict(row_ia) if row_ia else {}

        return {
            "timestamp": agora.isoformat(),
            "conversas_ativas": conversas_ativas,
            "conversas_pausadas": conversas_pausadas,
            "circuit_breaker": cb_state,
            "hoje": {
                "conversas": metrics.get("conversas_hoje", 0),
                "leads": metrics.get("leads_hoje", 0),
                "intencao": metrics.get("intencao_hoje", 0),
                "tempo_resposta": round(float(metrics.get("tempo_resp_medio", 0)), 1),
                "taxa_conversao": round(
                    (metrics.get("leads_hoje", 0) / max(metrics.get("conversas_hoje", 0), 1)) * 100, 1
                ),
            },
            "funil": {
                "links_enviados": funil.get("links_enviados", 0),
                "planos_exibidos": funil.get("planos_exibidos", 0),
                "matriculas": funil.get("matriculas", 0),
                "escalacoes": funil.get("escalacoes", 0),
            },
            "ia": {
                "tokens": ia.get("tokens_hoje", 0),
                "custo_usd": round(float(ia.get("custo_hoje", 0)), 4),
                "chamadas": ia.get("chamadas_ia_hoje", 0),
            },
            "sentimento": sentimento_counts,
        }
    except Exception as e:
        logger.error(f"Erro ao coletar métricas real-time: {e}")
        return {"error": str(e), "timestamp": agora.isoformat()}


@router.websocket("/ws/dashboard/{empresa_id}")
async def websocket_dashboard(websocket: WebSocket, empresa_id: int, token: str = Query(None)):
    """
    WebSocket para métricas em tempo real.
    Autenticação via query param ?token=JWT
    Push de dados a cada 10 segundos.
    """
    # Validar token JWT
    if not token:
        await websocket.close(code=4001, reason="Token ausente")
        return

    payload = await _validate_ws_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Token inválido")
        return

    # Verificar permissão (empresa_id do token deve bater ou ser admin_master)
    token_empresa = payload.get("empresa_id")
    perfil = payload.get("perfil")
    if perfil != "admin_master" and token_empresa != empresa_id:
        await websocket.close(code=4003, reason="Sem permissão para esta empresa")
        return

    await websocket.accept()
    logger.info(f"📡 WebSocket conectado: empresa={empresa_id} user={payload.get('sub')}")

    try:
        while True:
            # Envia métricas
            metrics = await _get_realtime_metrics(empresa_id)
            await websocket.send_json(metrics)

            # Espera 10s ou recebe mensagem do cliente (ping/pong ou config)
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
                # Cliente pode enviar comandos como {"interval": 5}
                try:
                    cmd = json.loads(msg)
                    if cmd.get("ping"):
                        await websocket.send_json({"pong": True})
                except (json.JSONDecodeError, TypeError):
                    pass
            except asyncio.TimeoutError:
                pass  # Normal — envia na próxima iteração

    except WebSocketDisconnect:
        logger.info(f"📡 WebSocket desconectado: empresa={empresa_id}")
    except Exception as e:
        logger.error(f"❌ Erro WebSocket empresa={empresa_id}: {e}")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
