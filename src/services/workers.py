import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List

from src.core.config import logger, OPENAI_API_KEY
import src.core.database as _database
from src.core.redis_client import redis_client
from src.services.db_queries import (
    carregar_integracao, sincronizar_planos_evo,
    _is_worker_leader, _coletar_metricas_unidade
)
from src.services.chatwoot_client import enviar_mensagem_chatwoot

# Global flag — set to True by bot_core shutdown_event
is_shutting_down: bool = False


def _log_worker_task_result(task: asyncio.Task):
    """Evita 'Task exception was never retrieved' e registra falhas de workers."""
    try:
        _ = task.exception()
    except asyncio.CancelledError:
        return
    except Exception as e:
        nome = task.get_name() if hasattr(task, 'get_name') else 'worker'
        if not is_shutting_down:
            logger.error(f"❌ {nome} finalizou com erro não tratado: {e}")


async def worker_sync_planos():
    try:
        while True:
            if not _database.db_pool:
                await asyncio.sleep(60)
                continue
            if not await _is_worker_leader("sync_planos", ttl=22000):
                logger.debug("⏭️ worker_sync_planos: não é líder, pulando ciclo")
                await asyncio.sleep(10)
                continue
            try:
                empresas = await _database.db_pool.fetch("SELECT id FROM empresas WHERE status = 'active'")
                for emp in empresas:
                    emp_id = emp['id']
                    # Sincroniza Global (fallback/caso geral)
                    await sincronizar_planos_evo(emp_id)
                    
                    # Sincroniza Unidades Específicas
                    unidades = await _database.db_pool.fetch(
                        "SELECT id FROM unidades WHERE empresa_id = $1 AND ativa = true", emp_id
                    )
                    for unid in unidades:
                        await sincronizar_planos_evo(emp_id, unidade_id=unid['id'])
                logger.info("✅ worker_sync_planos executado pelo líder")
            except Exception as e:
                logger.error(f"Erro no worker de sincronização de planos: {e}")
            await asyncio.sleep(21600)  # 6 horas
    except asyncio.CancelledError:
        logger.info("🛑 worker_sync_planos cancelado")
        raise


async def sync_planos_manual(empresa_id: int):
    # Sincroniza Global
    count = await sincronizar_planos_evo(empresa_id)
    
    # Sincroniza Unidades
    unidades = await _database.db_pool.fetch(
        "SELECT id FROM unidades WHERE empresa_id = $1 AND ativa = true", empresa_id
    )
    for unid in unidades:
        count += await sincronizar_planos_evo(empresa_id, unidade_id=unid['id'])
        
    return {"status": "ok", "total_sincronizados": count}


async def agendar_followups(conversation_id: int, account_id: int, slug: str, empresa_id: int):
    if not _database.db_pool:
        return
    try:
        await _database.db_pool.execute("""
            UPDATE followups SET status = 'cancelado'
            WHERE (
                conversa_id = (SELECT id FROM conversas WHERE conversation_id = $1)
                OR conversation_id = $1
            ) AND status = 'pendente'
        """, conversation_id)

        templates = await _database.db_pool.fetch("""
            SELECT t.*
            FROM templates_followup t
            LEFT JOIN unidades u ON u.id = t.unidade_id
            WHERE t.empresa_id = $1
              AND t.ativo = true
              AND (t.unidade_id IS NULL OR u.slug = $2)
            ORDER BY t.unidade_id NULLS LAST, t.ordem
        """, empresa_id, slug)

        agora = datetime.now(ZoneInfo("America/Sao_Paulo")).replace(tzinfo=None)
        for t in templates:
            agendado_para = agora + timedelta(minutes=t["delay_minutos"])
            await _database.db_pool.execute("""
                INSERT INTO followups
                    (conversa_id, conversation_id, account_id, empresa_id, unidade_id, template_id, tipo, mensagem, ordem, agendado_para, status)
                VALUES (
                    (SELECT id FROM conversas WHERE conversation_id = $1),
                    $1,
                    $9,
                    $2,
                    (SELECT id FROM unidades WHERE slug = $3),
                    $4, $5, $6, $7, $8, 'pendente'
                )
            """, conversation_id, empresa_id, slug, t["id"], t["tipo"], t["mensagem"], t["ordem"], agendado_para, account_id)

        logger.info(f"📅 {len(templates)} follow-ups agendados para conversa {conversation_id}")
    except Exception as e:
        logger.error(f"Erro ao agendar followups: {e}")


async def worker_followup():
    try:
        while True:
            await asyncio.sleep(30)
            # Garante que apenas 1 worker processe follow-ups em ambiente multi-processo
            if not await _is_worker_leader("followup", ttl=40):
                continue
            if not _database.db_pool:
                continue
            try:
                agora = datetime.now(ZoneInfo("America/Sao_Paulo")).replace(tzinfo=None)

                pendentes = await _database.db_pool.fetch("""
                    SELECT f.*, c.conversation_id, c.account_id, u.slug, c.empresa_id,
                           u.nome AS nome_unidade, c.contato_nome
                    FROM followups f
                    JOIN conversas c ON c.id = f.conversa_id
                    JOIN unidades u ON u.id = f.unidade_id
                    WHERE f.status = 'pendente' AND f.agendado_para <= $1
                """, agora)

                for f in pendentes:
                    conv_id = f['conversation_id']
                    acc_id = f['account_id']
                    emp_id = f['empresa_id']

                    if not conv_id or not acc_id:
                        await _database.db_pool.execute(
                            "UPDATE followups SET status = 'erro', erro_log = 'conversation_id ou account_id ausente' WHERE id = $1", f['id']
                        )
                        continue

                    if (
                        await redis_client.get(f"atend_manual:{conv_id}") == "1"
                        or await redis_client.get(f"pause_ia:{conv_id}") == "1"
                    ):
                        await _database.db_pool.execute("UPDATE followups SET status = 'cancelado' WHERE id = $1", f['id'])
                        continue

                    respondeu = await _database.db_pool.fetchval("""
                        SELECT 1 FROM mensagens m
                        JOIN conversas c ON c.id = m.conversa_id
                        WHERE c.conversation_id = $1 AND m.role = 'user'
                          AND m.created_at > NOW() - interval '5 minutes'
                    """, conv_id)
                    if respondeu:
                        await _database.db_pool.execute("UPDATE followups SET status = 'cancelado' WHERE id = $1", f['id'])
                        continue

                    integracao = await carregar_integracao(emp_id, 'chatwoot')
                    if not integracao:
                        await _database.db_pool.execute(
                            "UPDATE followups SET status = 'erro', erro_log = 'Sem integração' WHERE id = $1", f['id']
                        )
                        continue

                    from openai import AsyncOpenAI
                    cliente_llm = AsyncOpenAI(api_key=OPENAI_API_KEY)
                    
                    nome_contato = (f['contato_nome'] or '').split()[0] if f['contato_nome'] else 'você'
                    nome_unidade = f['nome_unidade'] or ''
                    template_base = (f['mensagem'] or '').replace('{{nome}}', nome_contato).replace('{{unidade}}', nome_unidade)
                    
                    # ── Lógica do Score e Geração IA ────────────────────────
                    eventos = await _database.db_pool.fetch("SELECT tipo_evento, score_incremento FROM eventos_funil WHERE conversa_id = $1", f['conversa_id'])
                    score_total = sum((e['score_incremento'] or 1) for e in eventos)
                    
                    if score_total >= 4:
                        contexto_lead = "Este lead é QUENTE (Alta intenção). Já interagiu bem ou pediu link de matrícula. Faça um remarketing direto, focando em urgência e conversão, mostre proximidade."
                    elif score_total >= 2:
                        contexto_lead = "Este lead é MORNO. Fez algumas perguntas mas esfriou. Mande uma mensagem amigável de benefício, sem pressão excessiva."
                    else:
                        contexto_lead = "Este lead é FRIO. Falou pouco. Mande apenas uma lembrança gentil de que estamos à disposição."

                    prompt_sistema = (
                        f"Você é um excelente assistente de vendas da academia {nome_unidade}.\n"
                        f"Sua missão é reescrever este template de recarga/follow-up de forma natural, humana e curtinha de WhatsApp.\n"
                        f"{contexto_lead}\n\n"
                        f"Template Original: '{template_base}'\n"
                        f"Regras: Não pareça um robô. Use no máximo 2 emojis. Seja breve."
                    )
                    
                    try:
                        resp_llm = await cliente_llm.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[{"role": "system", "content": prompt_sistema}],
                            temperature=0.7,
                            max_tokens=150
                        )
                        mensagem_final = resp_llm.choices[0].message.content.strip()
                    except Exception as e_llm:
                        logger.error(f"Erro no LLM do follow-up (fallback para template estático): {e_llm}")
                        mensagem_final = template_base

                    await enviar_mensagem_chatwoot(
                        f['account_id'], f['conversation_id'], mensagem_final, "Assistente Virtual", integracao, evitar_prefixo_nome=True
                    )
                    await _database.db_pool.execute(
                        "UPDATE followups SET status = 'enviado', enviado_em = NOW() WHERE id = $1", f['id']
                    )

            except Exception as e:
                logger.error(f"Erro no worker de follow-up: {e}")
    except asyncio.CancelledError:
        logger.info("🛑 worker_followup cancelado")
        raise


async def worker_metricas_diarias():
    """
    Worker que roda a cada hora e persiste todas as métricas diárias.
    Usa ON CONFLICT para atualizar registros existentes (idempotente).
    Colunas opcionais (satisfacao_media, tokens, custo) são ignoradas com
    graceful fallback se a coluna ainda não existir no banco.
    """
    try:
        while True:
            if not _database.db_pool:
                await asyncio.sleep(60)
                continue
            if not await _is_worker_leader("metricas_diarias", ttl=3700):
                logger.debug("⏭️ worker_metricas_diarias: não é líder, pulando ciclo")
                await asyncio.sleep(3600)
                continue
            try:
                import asyncpg
                hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
                empresas = await _database.db_pool.fetch("SELECT id FROM empresas WHERE status = 'active'")

                total_unidades = 0
                for emp in empresas:
                    empresa_id = emp['id']
                    unidades = await _database.db_pool.fetch(
                        "SELECT id FROM unidades WHERE empresa_id = $1 AND ativa = true",
                        empresa_id
                    )

                    for unid in unidades:
                        unidade_id = unid['id']
                        total_unidades += 1

                        m = await _coletar_metricas_unidade(empresa_id, unidade_id, hoje)

                        # ── Upsert principal (colunas garantidas) ─────────────
                        await _database.db_pool.execute("""
                            INSERT INTO metricas_diarias (
                                empresa_id, unidade_id, data,
                                total_conversas, conversas_encerradas, conversas_sem_resposta,
                                novos_contatos,
                                total_mensagens, total_mensagens_ia,
                                leads_qualificados, taxa_conversao,
                                tempo_medio_resposta,
                                total_solicitacoes_telefone, total_links_enviados,
                                total_planos_enviados, total_matriculas,
                                pico_hora,
                                satisfacao_media,
                                updated_at
                            )
                            VALUES (
                                $1, $2, $3,
                                $4, $5, $6,
                                $7,
                                $8, $9,
                                $10, $11,
                                $12,
                                $13, $14,
                                $15, $16,
                                $17,
                                $18,
                                NOW()
                            )
                            ON CONFLICT (empresa_id, unidade_id, data) DO UPDATE SET
                                total_conversas            = EXCLUDED.total_conversas,
                                conversas_encerradas       = EXCLUDED.conversas_encerradas,
                                conversas_sem_resposta     = EXCLUDED.conversas_sem_resposta,
                                novos_contatos             = EXCLUDED.novos_contatos,
                                total_mensagens            = EXCLUDED.total_mensagens,
                                total_mensagens_ia         = EXCLUDED.total_mensagens_ia,
                                leads_qualificados         = EXCLUDED.leads_qualificados,
                                taxa_conversao             = EXCLUDED.taxa_conversao,
                                tempo_medio_resposta       = EXCLUDED.tempo_medio_resposta,
                                total_solicitacoes_telefone = EXCLUDED.total_solicitacoes_telefone,
                                total_links_enviados       = EXCLUDED.total_links_enviados,
                                total_planos_enviados      = EXCLUDED.total_planos_enviados,
                                total_matriculas           = EXCLUDED.total_matriculas,
                                pico_hora                  = EXCLUDED.pico_hora,
                                satisfacao_media           = EXCLUDED.satisfacao_media,
                                updated_at                 = NOW()
                        """,
                            empresa_id, unidade_id, hoje,
                            m["total_conversas"], m["conversas_encerradas"], m["conversas_sem_resposta"],
                            m["novos_contatos"],
                            m["total_mensagens"], m["total_mensagens_ia"],
                            m["leads_qualificados"], m["taxa_conversao"],
                            m["tempo_medio_resposta"],
                            m["total_solicitacoes_telefone"], m["total_links_enviados"],
                            m["total_planos_enviados"], m["total_matriculas"],
                            m["pico_hora"],
                            m["satisfacao_media"],
                        )

                        # ── Colunas opcionais (tokens/custo) — graceful fallback ──
                        if m["tokens_consumidos"] is not None:
                            try:
                                await _database.db_pool.execute("""
                                    UPDATE metricas_diarias
                                    SET tokens_consumidos  = $4,
                                        custo_estimado_usd = $5,
                                        updated_at         = NOW()
                                    WHERE empresa_id = $1 AND unidade_id = $2 AND data = $3
                                """, empresa_id, unidade_id, hoje,
                                    m["tokens_consumidos"], m["custo_estimado_usd"])
                            except Exception:
                                pass  # colunas ainda não existem no banco

                logger.info(f"✅ Métricas diárias atualizadas — {total_unidades} unidades / {hoje}")

            except asyncpg.PostgresError as e:
                logger.error(f"❌ Erro PostgreSQL no worker de métricas: {e}")
            except Exception as e:
                logger.error(f"❌ Erro inesperado no worker de métricas: {e}", exc_info=True)
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("🛑 worker_metricas_diarias cancelado")
        raise
