import asyncio
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List

from src.core.config import logger, OPENAI_API_KEY
import src.core.database as _database
from src.core.redis_client import redis_client
from src.utils.redis_helper import (
    get_tenant_cache, set_tenant_cache, delete_tenant_cache, exists_tenant_cache
)
from src.services.llm_service import cliente_ia
from src.services.db_queries import (
    carregar_integracao, sincronizar_planos_evo,
    _is_worker_leader, _coletar_metricas_unidade, bd_salvar_resumo_ia
)
from src.services.chatwoot_client import enviar_mensagem_chatwoot
from src.utils.text_helpers import randomizar_mensagem


def _render_followup_template(template: str, nome_contato: str, nome_unidade: str) -> str:
    texto = template or ""

    nome = (nome_contato or "").strip() or "você"
    unidade = (nome_unidade or "").strip()

    for token in ("{{nome}}", "{nome}"):
        texto = texto.replace(token, nome)

    for token in ("{{unidade}}", "{unidade}"):
        texto = texto.replace(token, unidade)

    if not unidade:
        # Limpa trechos comuns que ficariam quebrados sem o nome da unidade
        texto = re.sub(r"\bsobre\s+a\s*\.?", "", texto, flags=re.IGNORECASE)
        texto = re.sub(r"\s{2,}", " ", texto).strip()

    return texto

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
                OR conversation_id = $1
            ) AND empresa_id = $2 AND status = 'pendente'
        """, conversation_id, empresa_id)

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
                    (SELECT id FROM conversas WHERE conversation_id = $1 AND empresa_id = $2),
                    $1,
                    $9,
                    $2,
                    (SELECT id FROM unidades WHERE slug = $3 AND empresa_id = $2),
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
                        await get_tenant_cache(emp_id, f"atend_manual:{conv_id}") == "1"
                        or await get_tenant_cache(emp_id, f"pause_ia:{conv_id}") == "1"
                    ):
                        await _database.db_pool.execute("UPDATE followups SET status = 'cancelado', updated_at = NOW() WHERE id = $1", f['id'])
                        continue

                    respondeu = await _database.db_pool.fetchval("""
                        SELECT 1 FROM mensagens m
                        JOIN conversas c ON c.id = m.conversa_id
                        WHERE c.conversation_id = $1 AND m.role = 'user'
                          AND m.created_at > NOW() - interval '5 minutes'
                    """, conv_id)
                    if respondeu:
                        await _database.db_pool.execute("UPDATE followups SET status = 'cancelado', updated_at = NOW() WHERE id = $1", f['id'])
                        continue

                    integracao = await carregar_integracao(emp_id, 'chatwoot')
                    if not integracao:
                        await _database.db_pool.execute(
                            "UPDATE followups SET status = 'erro', erro_log = 'Sem integração' WHERE id = $1", f['id']
                        )
                        continue

                    if not cliente_ia:
                        await _database.db_pool.execute(
                            "UPDATE followups SET status = 'erro', erro_log = 'Cliente IA não configurado' WHERE id = $1", f['id']
                        )
                        continue
                    
                    nome_contato = (f['contato_nome'] or '').split()[0] if f['contato_nome'] else 'você'
                    nome_unidade = (f['nome_unidade'] or '').strip()
                    if not nome_unidade and f.get('slug'):
                        nome_unidade = str(f['slug']).replace('-', ' ').replace('_', ' ').title()
                    template_base = _render_followup_template(f['mensagem'] or '', nome_contato, nome_unidade)
                    
                    # Carrega personalidade para usar modelo escolhido pelo cliente
                    from src.services.db_queries import carregar_personalidade
                    pers = await carregar_personalidade(emp_id)
                    modelo_followup = pers.get("model_name") or "gpt-4o-mini"
                    temp_followup = float(pers.get("temperature") or 0.7)
                    usar_emoji = pers.get("usar_emoji", True)

                    # ── Lógica do Score e Geração IA ────────────────────────
                    eventos = await _database.db_pool.fetch("SELECT tipo_evento, score_incremento FROM eventos_funil WHERE conversa_id = $1", f['conversa_id'])
                    score_total = sum((e['score_incremento'] or 1) for e in eventos)

                    if score_total >= 4:
                        contexto_lead = "Este lead é QUENTE (Alta intenção). Já interagiu bem ou pediu link de matrícula. Faça um remarketing direto, focando em urgência e conversão, mostre proximidade."
                    elif score_total >= 2:
                        contexto_lead = "Este lead é MORNO. Fez algumas perguntas mas esfriou. Mande uma mensagem amigável de benefício, sem pressão excessiva."
                    else:
                        contexto_lead = "Este lead é FRIO. Falou pouco. Mande apenas uma lembrança gentil de que estamos à disposição."

                    regra_emoji = "Use no máximo 2 emojis." if usar_emoji else "Não use emojis."
                    prompt_sistema = (
                        f"Você é um excelente assistente de vendas da academia {nome_unidade}.\n"
                        f"Sua missão é reescrever este template de recarga/follow-up de forma natural, humana e curtinha de WhatsApp.\n"
                        f"{contexto_lead}\n\n"
                        f"Template Original: '{template_base}'\n"
                        f"Regras: Não pareça um robô. {regra_emoji} Seja breve."
                    )
                    
                    try:
                        resp_llm = await cliente_ia.chat.completions.create(
                            model=modelo_followup,
                            messages=[{"role": "system", "content": prompt_sistema}],
                            temperature=temp_followup,
                            max_tokens=250
                        )
                        mensagem_final = resp_llm.choices[0].message.content.strip()
                    except Exception as e_llm:
                        logger.error(f"Erro no LLM do follow-up (fallback para template estático): {e_llm}")
                        mensagem_final = template_base

                    await enviar_mensagem_chatwoot(
                        f['account_id'], f['conversation_id'], randomizar_mensagem(mensagem_final), integracao, emp_id, nome_ia="Assistente Virtual", evitar_prefixo_nome=True
                    )
                    await _database.db_pool.execute(
                        "UPDATE followups SET status = 'enviado', enviado_em = NOW() WHERE id = $1", f['id']
                    )

            except Exception as e:
                logger.error(f"Erro no worker de follow-up: {e}")
    except asyncio.CancelledError:
        logger.info("🛑 worker_followup cancelado")
        raise


# Modelo econômico via OpenRouter para tarefas de resumo
_RESUMO_MODEL = "google/gemini-2.0-flash-lite-001"
_RESUMO_BATCH = 10   # conversas por ciclo
_RESUMO_INTERVAL = 600  # segundos entre ciclos (10 min)


async def gerar_resumo_conversa(conversa_id_db: int, conversation_id_ext: int, empresa_id: int):
    """
    Gera o Resumo Neural para uma conversa específica.
    """
    from src.services.llm_service import cliente_ia
    
    if not _database.db_pool or not cliente_ia:
        return None

    try:
        msgs = await _database.db_pool.fetch("""
            SELECT role, conteudo FROM mensagens
            WHERE conversa_id = $1
            ORDER BY created_at ASC
            LIMIT 40
        """, conversa_id_db)

        if not msgs:
            return "Nenhuma mensagem encontrada para resumir."

        historico = "\n".join(
            f"{'Lead' if m['role'] == 'user' else 'IA'}: {(m['conteudo'] or '').strip()}"
            for m in msgs
        )

        prompt = (
            "Analise a conversa abaixo entre um lead e uma IA de vendas de academia. "
            "Responda em português com no máximo 3 frases cobrindo: "
            "1) o que o lead quer, 2) nível de interesse (quente/morno/frio), "
            "3) próximo passo sugerido. Seja direto e objetivo.\n\n"
            f"Conversa:\n{historico}"
        )

        resp = await cliente_ia.chat.completions.create(
            model=_RESUMO_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3,
        )
        resumo = resp.choices[0].message.content.strip()
        await bd_salvar_resumo_ia(conversation_id_ext, empresa_id, resumo)
        logger.info(f"Resumo Neural manual gerado para conversa {conversation_id_ext}")
        return resumo
    except Exception as e:
        logger.error(f"Erro ao gerar resumo manual para conversa {conversation_id_ext}: {e}")
        return f"Erro ao gerar resumo: {str(e)}"


async def worker_resumo_ia():
    """
    Worker que gerava o Resumo Neural automaticamente.
    DESATIVADO: Agora o resumo é gerado manualmente via Dashboard.
    """
    return
    # Mantido apenas como referência do que era feito
    try:
        while True:
            await asyncio.sleep(_RESUMO_INTERVAL)
            # ... rest of the logic ...
    except asyncio.CancelledError:
        logger.info("🛑 worker_resumo_ia cancelado")
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
