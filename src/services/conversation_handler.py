"""
conversation_handler.py — Conversation state management and buffering.

Manages:
- Message buffer collection (WhatsApp burst coalescing)
- Unit selection monitoring
- Context resolution (unit detection)
- Message persistence
- Lock renewal for distributed processing
"""
import asyncio
import json
import time
from typing import List, Dict, Any

from src.core.config import logger
from src.core.redis_client import redis_client
from src.utils.redis_helper import (
    get_tenant_cache, set_tenant_cache, delete_tenant_cache,
    exists_tenant_cache, get_tenant_key,
)
from src.services.db_queries import (
    carregar_integracao, carregar_personalidade,
    bd_salvar_mensagem_local, bd_registrar_evento_funil,
)
from src.services.chatwoot_client import enviar_mensagem_chatwoot
from src.services.ia_processor import resolver_contexto_unidade
import src.core.database as _database
import src.services.chatwoot_client as _chatwoot_module


async def renovar_lock(chave: str, valor: str, intervalo: int = 40):
    """Renova lock distribuído periodicamente para evitar expiração durante processamento."""
    try:
        while True:
            await asyncio.sleep(intervalo)
            res = await redis_client.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], 180) else return 0 end",
                1, chave, valor
            )
            if not res:
                break
    except asyncio.CancelledError:
        pass


async def coletar_mensagens_buffer(conversation_id: int, empresa_id: int) -> List[str]:
    """Coleta mensagens do buffer e limpa a fila da conversa.

    Faz uma coalescência curta para agrupar rajadas (2-4 mensagens seguidas)
    em uma única resposta, reduzindo respostas duplicadas e melhorando fluidez.
    """
    chave_buffet = f"{empresa_id}:buffet:{conversation_id}"

    mensagens_acumuladas: List[str] = []
    deadline = time.time() + 3.0  # janela de 3s para juntar rajada WhatsApp
    _checks_vazios = 0

    while True:
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.lrange(chave_buffet, 0, -1)
            pipe.delete(chave_buffet)
            resultado = await pipe.execute()
        lote = resultado[0] or []
        if lote:
            mensagens_acumuladas.extend(lote)
            _checks_vazios = 0
            if len(mensagens_acumuladas) >= 8 or time.time() >= deadline:
                break
            await asyncio.sleep(0.5)
            continue
        # Buffer vazio
        _checks_vazios += 1
        if time.time() >= deadline:
            break
        if mensagens_acumuladas and _checks_vazios >= 4:
            # Já tem msgs e buffer ficou vazio 4x seguidas — rajada acabou
            break
        await asyncio.sleep(0.5)

    logger.info(f"📦 Buffer tem {len(mensagens_acumuladas)} mensagens para conv {conversation_id}")
    return mensagens_acumuladas


async def aguardar_escolha_unidade_ou_reencaminhar(
    conversation_id: int, empresa_id: int, mensagens_acumuladas: List[str]
) -> bool:
    """Reencaminha buffer quando conversa ainda está aguardando escolha de unidade."""
    if not await exists_tenant_cache(empresa_id, f"esperando_unidade:{conversation_id}"):
        return False

    logger.info(f"⏳ Conv {conversation_id} [E:{empresa_id}] aguardando escolha de unidade — IA pausada")
    _buffet_key = f"{empresa_id}:buffet:{conversation_id}"
    async with redis_client.pipeline(transaction=False) as pipe:
        for m_json in mensagens_acumuladas:
            pipe.rpush(_buffet_key, m_json)
        pipe.expire(_buffet_key, 300)
        await pipe.execute()
    return True


async def resolver_contexto_atendimento(
    conversation_id: int,
    textos: List[str],
    transcricoes: List[str],
    slug: str,
    empresa_id: int,
) -> Dict[str, Any]:
    """Resolve slug da unidade para o atendimento atual e registra mudança de contexto."""
    primeira_mensagem = textos[0] if textos else ""
    mudou_unidade = False
    texto_unificado = " ".join([t for t in (textos + transcricoes) if t]).strip()

    if texto_unificado:
        ctx_unidade = await resolver_contexto_unidade(
            conversation_id=conversation_id,
            texto=texto_unificado,
            empresa_id=empresa_id,
            slug_atual=slug,
        )
        novo_slug = ctx_unidade.get("slug")
        if novo_slug and novo_slug != slug:
            logger.info(f"🔄 Contexto de unidade atualizado para {novo_slug}")
            slug = novo_slug
            mudou_unidade = True
            await bd_registrar_evento_funil(
                conversation_id, empresa_id, "mudanca_unidade", f"Contexto alterado para {slug}", score_incremento=1
            )

    return {"slug": slug, "mudou_unidade": mudou_unidade, "primeira_mensagem": primeira_mensagem}


async def persistir_mensagens_usuario(
    conversation_id: int, empresa_id: int, textos: List[str], transcricoes: List[str]
):
    """Persiste histórico de mensagens do usuário (texto e áudio transcrito)."""
    logger.debug(f"💾 Persistindo {len(textos)} textos e {len(transcricoes)} áudios para conv {conversation_id}")
    for txt in textos:
        await bd_salvar_mensagem_local(conversation_id, empresa_id, "user", txt)
    for transc in transcricoes:
        await bd_salvar_mensagem_local(conversation_id, empresa_id, "user", f"[Áudio] {transc}")


async def monitorar_escolha_unidade(account_id: int, conversation_id: int, empresa_id: int):
    """Monitora se o cliente escolheu uma unidade e envia lembretes/encerra se não responder."""
    await asyncio.sleep(120)
    if not await exists_tenant_cache(empresa_id, f"esperando_unidade:{conversation_id}"):
        return
    if await exists_tenant_cache(empresa_id, f"unidade_escolhida:{conversation_id}"):
        return

    integracao = await carregar_integracao(empresa_id, 'chatwoot')
    if not integracao:
        return

    # Lembrete amigável — pergunta de novo sem listar todas as unidades
    _pers_monit = await carregar_personalidade(empresa_id) or {}
    _nome_ia_monit = _pers_monit.get('nome_ia') or 'Assistente'
    await enviar_mensagem_chatwoot(
        account_id, conversation_id,
        "Só pra eu não te perder de vista 😊\n\nQual cidade ou bairro você prefere para treinar?",
        integracao, empresa_id, nome_ia=_nome_ia_monit
    )

    await asyncio.sleep(480)
    if not await exists_tenant_cache(empresa_id, f"esperando_unidade:{conversation_id}"):
        return
    if await exists_tenant_cache(empresa_id, f"unidade_escolhida:{conversation_id}"):
        return

    # Sem resposta após 8 min — encerra conversa
    await delete_tenant_cache(empresa_id, f"esperando_unidade:{conversation_id}")
    url_c = f"{integracao['url']}/api/v1/accounts/{account_id}/conversations/{conversation_id}"
    try:
        await _chatwoot_module.http_client.put(
            url_c, json={"status": "resolved"},
            headers={"api_access_token": integracao['token']}
        )
    except Exception as e:
        logger.warning(f"Erro ao encerrar conversa {conversation_id}: {e}")
