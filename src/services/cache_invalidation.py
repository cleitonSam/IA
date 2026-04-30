"""
[CACHE-01] Invalidação centralizada de cache por empresa.

Todo endpoint que MUTA dados (PUT/POST/DELETE em personalidade, FAQ, KB, integração,
unidades, planos, fluxo, menu) deve chamar a função correspondente daqui. Isso garante
que a próxima mensagem do cliente use o conteúdo atualizado IMEDIATAMENTE, sem esperar
TTL de 5 minutos.

Estrutura dos caches mapeados (prefixo `cfg:`):

  cfg:pers:empresa:{empresa_id}                        → personalidade (TTL 300s)
  cfg:faq:{empresa_id}:{slug}:v5                       → FAQ formatado (TTL 300s)
  cfg:faq_raw:v2:{empresa_id}:{slug}                   → FAQ cru para fast-match (TTL 300s)
  cfg:menu_triagem:{empresa_id}:u:{unidade|global}     → menu triagem (TTL 120s)
  cfg:fluxo_triagem:{empresa_id}:u:{unidade|global}    → fluxo visual (TTL 120s)
  cfg:integracao:{empresa_id}:{tipo}:{unidade|global}  → chatwoot/uazapi/evo (TTL 300s)
  cfg:unidade:{empresa_id}:{slug}:v2                   → unidade por slug (TTL 60s)
  cfg:unidades:lista:empresa:{empresa_id}              → lista de unidades (TTL 60s)
  cfg:planos:{empresa_id}:...                          → planos ativos (TTL 60s)
  cfg:global:empresa:{empresa_id}                      → config global (TTL 3600s)
  {empresa_id}:rag_cache:*                             → cache de respostas RAG (TTL 300s)

Uso:
    from src.services.cache_invalidation import invalidate_faq, flush_empresa

    # No PUT /faq/{id}:
    await invalidate_faq(empresa_id)

    # No endpoint admin "limpar tudo":
    await flush_empresa(empresa_id)
"""

from __future__ import annotations

from typing import List, Optional

from src.core.config import logger
from src.core.redis_client import redis_client


# ============================================================
# Helpers
# ============================================================

async def _delete_keys(keys: List[str]) -> int:
    """Deleta uma lista de keys Redis. Retorna quantas foram apagadas."""
    if not keys:
        return 0
    try:
        n = await redis_client.delete(*keys)
        return int(n or 0)
    except Exception as e:
        logger.warning(f"[CACHE-01] delete_keys falhou: {e}")
        return 0


async def _delete_by_pattern(pattern: str, batch: int = 200) -> int:
    """Deleta keys que batem um pattern (SCAN + DEL em lotes). Seguro em prod."""
    deleted = 0
    try:
        async for key in redis_client.scan_iter(pattern, count=batch):
            try:
                await redis_client.delete(key)
                deleted += 1
            except Exception:
                pass
        return deleted
    except Exception as e:
        logger.warning(f"[CACHE-01] delete_by_pattern '{pattern}' falhou: {e}")
        return deleted


# ============================================================
# Invalidadores específicos
# ============================================================

async def invalidate_personalidade(empresa_id: int) -> int:
    """Limpa cache da personalidade (texto, tom, menu, fluxo — tudo que está em personalidade_ia).
    Tambem limpa menu/fluxo/global porque menu_triagem e fluxo_triagem VIVEM na personalidade.

    [RESET-FLOW] Ao salvar personalidade (inclui horario da IA), tambem reseta
    TODOS os estados de fluxo em andamento — assim mudanca de horario afeta
    conversas ativas imediatamente, sem precisar esperar TTL.
    """
    n = 0
    n += await _delete_keys([f"cfg:pers:empresa:{empresa_id}"])
    n += await _delete_by_pattern(f"cfg:menu_triagem:{empresa_id}:*")
    n += await _delete_by_pattern(f"cfg:fluxo_triagem:{empresa_id}:*")
    n += await _delete_keys([f"cfg:global:empresa:{empresa_id}"])
    # [RESET-FLOW] Forca todas conversas a reiniciar
    n += await reset_all_flow_states(empresa_id)
    logger.info(f"[CACHE-01] personalidade empresa={empresa_id} invalidada ({n} keys total incl. flow states)")
    return n


async def invalidate_faq(empresa_id: int, slug: Optional[str] = None) -> int:
    """Limpa cache de FAQ. Se slug não for dado, limpa de TODAS as unidades da empresa."""
    n = 0
    if slug:
        n += await _delete_keys([
            f"cfg:faq:{empresa_id}:{slug}:v5",
            f"cfg:faq_raw:v2:{empresa_id}:{slug}",
        ])
    else:
        n += await _delete_by_pattern(f"cfg:faq:{empresa_id}:*")
        n += await _delete_by_pattern(f"cfg:faq_raw:v2:{empresa_id}:*")
    # Limpa também o cache de respostas RAG porque FAQ pode influenciar (se FAQ mudou, resposta anterior pode estar errada)
    n += await _delete_by_pattern(f"{empresa_id}:rag_cache:*")
    logger.info(f"[CACHE-01] FAQ empresa={empresa_id} slug={slug or '*'} invalidado ({n} keys)")
    return n


async def invalidate_kb(empresa_id: int) -> int:
    """Limpa cache do knowledge base / RAG. Use após adicionar/editar/deletar item de KB."""
    n = await _delete_by_pattern(f"{empresa_id}:rag_cache:*")
    logger.info(f"[CACHE-01] KB/RAG empresa={empresa_id} invalidada ({n} keys)")
    return n


async def invalidate_menu_triagem(empresa_id: int) -> int:
    n = await _delete_by_pattern(f"cfg:menu_triagem:{empresa_id}:*")
    logger.info(f"[CACHE-01] menu_triagem empresa={empresa_id} invalidado ({n} keys)")
    return n


async def invalidate_fluxo_triagem(empresa_id: int) -> int:
    """[RESET-FLOW] Ao salvar fluxo, reseta states em andamento pra aplicar imediato."""
    n = await _delete_by_pattern(f"cfg:fluxo_triagem:{empresa_id}:*")
    n += await reset_all_flow_states(empresa_id)
    logger.info(f"[CACHE-01] fluxo_triagem empresa={empresa_id} invalidado ({n} keys total)")
    return n


async def invalidate_integracao(empresa_id: int, tipo: Optional[str] = None) -> int:
    """Limpa cache de integração. Se tipo não for dado, limpa todas (chatwoot + uazapi + evo).

    IMPORTANTE: o codebase usa DOIS formatos de key:
      - cfg:integracao:{empresa_id}:{tipo}             (global, main.py carregar_integracao)
      - cfg:integracao:{empresa_id}:{tipo}:{unidade}   (por unidade, quando aplicavel)
    Precisamos limpar AMBOS os formatos, senao o token antigo fica ate o TTL expirar.
    """
    n = 0
    if tipo:
        # Deleta a key global exata (sem sufixo) e tambem as por-unidade (com sufixo)
        n += await _delete_keys([f"cfg:integracao:{empresa_id}:{tipo}"])
        n += await _delete_by_pattern(f"cfg:integracao:{empresa_id}:{tipo}:*")
    else:
        # Sem tipo: limpa tudo de integracao da empresa (pattern pega ambos formatos)
        n += await _delete_by_pattern(f"cfg:integracao:{empresa_id}:*")
    logger.info(f"[CACHE-01] integracao empresa={empresa_id} tipo={tipo or '*'} invalidada ({n} keys)")
    return n


async def invalidate_unidades(empresa_id: int) -> int:
    """Limpa cache de unidades (lista + individual por slug)."""
    n = 0
    n += await _delete_keys([f"cfg:unidades:lista:empresa:{empresa_id}"])
    n += await _delete_by_pattern(f"cfg:unidade:{empresa_id}:*")
    # Se unidade mudou, FAQ por slug também pode precisar re-carregar
    n += await _delete_by_pattern(f"cfg:faq:{empresa_id}:*")
    n += await _delete_by_pattern(f"cfg:faq_raw:v2:{empresa_id}:*")
    logger.info(f"[CACHE-01] unidades empresa={empresa_id} invalidadas ({n} keys)")
    return n


async def invalidate_planos(empresa_id: int) -> int:
    n = await _delete_by_pattern(f"cfg:planos:{empresa_id}*")
    # Limpa também padrões alternativos que o codebase possa usar
    n += await _delete_by_pattern(f"planos:{empresa_id}*")
    logger.info(f"[CACHE-01] planos empresa={empresa_id} invalidados ({n} keys)")
    return n


async def invalidate_global(empresa_id: int) -> int:
    n = await _delete_keys([f"cfg:global:empresa:{empresa_id}"])
    logger.info(f"[CACHE-01] global empresa={empresa_id} invalidado ({n} keys)")
    return n


# ============================================================
# Nuclear: apaga TUDO de uma empresa
# ============================================================

async def flush_empresa(empresa_id: int) -> int:
    """
    Apaga TUDO que está em cache para uma empresa. Use como botão de "resetar memória"
    no dashboard. Força o sistema a recarregar tudo do banco na próxima request.

    NÃO apaga:
      - memoria_cliente (tabela — são fatos durable dos clientes)
      - conversas/mensagens (dados operacionais)
      - locks de worker (race condition)
    """
    n = 0
    # Configs centralizadas
    n += await invalidate_personalidade(empresa_id)
    n += await invalidate_faq(empresa_id)
    n += await invalidate_kb(empresa_id)
    n += await invalidate_menu_triagem(empresa_id)
    n += await invalidate_fluxo_triagem(empresa_id)
    n += await invalidate_integracao(empresa_id)
    n += await invalidate_unidades(empresa_id)
    n += await invalidate_planos(empresa_id)
    n += await invalidate_global(empresa_id)

    # Buffers / semanticos que possam ter ficado
    n += await _delete_by_pattern(f"{empresa_id}:semantic_cache:*")
    n += await _delete_by_pattern(f"{empresa_id}:intent_cache:*")
    n += await _delete_by_pattern(f"lead_score:{empresa_id}:*")
    n += await _delete_by_pattern(f"{empresa_id}:lead_score:*")

    # Cache de respostas IA (padrões reais usados pelo bot_core)
    n += await _delete_by_pattern(f"cache:intent:{empresa_id}:*")
    n += await _delete_by_pattern(f"cache:ia:{empresa_id}:*")
    n += await _delete_by_pattern(f"cache:sem:{empresa_id}:*")

    logger.warning(f"[CACHE-01] FLUSH TOTAL empresa={empresa_id}: {n} keys apagadas")
    return n


async def flush_all() -> int:
    """
    NUCLEAR: apaga TODO o cache de todas as empresas. Use com muito cuidado.

    [H-05] Protecao: exige confirm_token que mude a cada dia.
    Uso: await flush_all(confirm_token=os.getenv("FLUSH_ALL_TOKEN"))
    Default: FLUSH_YYYYMMDD (data de hoje em UTC)
    """
    import datetime as _dt
    import os as _os
    # Requer que alguem passe o token via kwarg OU que FLUSH_ALL_TOKEN env seja ativado
    _raise_without_token = True
    return 0


async def flush_all_confirmed(confirm_token: str) -> int:
    """Versao que realmente flushes — exige token valido."""
    import datetime as _dt
    import os as _os
    expected = _os.getenv("FLUSH_ALL_TOKEN") or _dt.datetime.utcnow().strftime("FLUSH_%Y%m%d")
    if confirm_token != expected:
        logger.error(f"[H-05] flush_all_confirmed BLOQUEADO — token invalido. Esperado: {expected}")
        raise PermissionError("flush_all_confirmed requer token valido")
    n = 0
    n += await _delete_by_pattern("cfg:*")
    n += await _delete_by_pattern("*:rag_cache:*")
    n += await _delete_by_pattern("*:semantic_cache:*")
    n += await _delete_by_pattern("*:intent_cache:*")
    n += await _delete_by_pattern("planos:*")
    n += await _delete_by_pattern("lead_score:*")
    logger.warning(f"[CACHE-01] FLUSH GLOBAL (autorizado): {n} keys apagadas")
    return n



async def reset_all_flow_states(empresa_id: int) -> int:
    """
    Limpa TODOS os estados de fluxo em andamento da empresa.
    Usado quando admin salva mudanca de horario/fluxo — forca todas as conversas
    a reiniciar do start na proxima msg, pegando a config nova.
    """
    n = 0
    # States e vars do flow_executor (por phone)
    n += await _delete_by_pattern(f"fluxo_state:{empresa_id}:*")
    n += await _delete_by_pattern(f"fluxo_vars:{empresa_id}:*")
    # Cooldowns / contadores (pra nao ficarem com valores antigos)
    n += await _delete_by_pattern(f"fluxo_ended:{empresa_id}:*")
    n += await _delete_by_pattern(f"fluxo_restarts:{empresa_id}:*")
    n += await _