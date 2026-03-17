import asyncio
import json
import base64
import uuid
import re
import httpx
import asyncpg
import redis.asyncio as redis
from decimal import Decimal
from typing import Optional, List, Dict, Any

from src.core.config import logger, PROMETHEUS_OK, METRIC_ERROS_TOTAL
import src.core.database as _database
from src.core.redis_client import redis_client, redis_get_json, redis_set_json
from src.utils.intent_helpers import classificar_intencao, _faq_compativel_com_intencao
from src.utils.text_helpers import normalizar
from rapidfuzz import fuzz
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

_WORKER_ID = str(uuid.uuid4())  # ID único deste processo

# is_shutting_down is imported from workers to avoid circular imports at call time
def _get_is_shutting_down() -> bool:
    try:
        import src.services.workers as _wm
        return _wm.is_shutting_down
    except Exception:
        return False


async def buscar_empresa_por_account_id(account_id: int) -> Optional[int]:
    """
    Retorna o ID da empresa associada ao account_id do Chatwoot.
    """
    if not _database.db_pool:
        return None

    cache_key = f"map:account:{account_id}"
    cached = await redis_client.get(cache_key)
    if cached:
        return int(cached)

    try:
        query = """
            SELECT empresa_id FROM integracoes
            WHERE tipo = 'chatwoot'
              AND ativo = true
              AND config->>'account_id' = $1::text
            LIMIT 1
        """
        row = await _database.db_pool.fetchrow(query, str(account_id))
        if row:
            empresa_id = row['empresa_id']
            await redis_client.setex(cache_key, 3600, str(empresa_id))
            return empresa_id
        return None
    except asyncpg.PostgresError as e:
        logger.error(f"Erro PostgreSQL ao buscar empresa por account_id {account_id}: {e}")
        if PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="db_empresa_lookup").inc()
        return None
    except Exception as e:
        logger.error(f"Erro inesperado ao buscar empresa por account_id {account_id}: {e}")
        return None


async def carregar_integracao(
    empresa_id: int, 
    tipo: str = 'chatwoot', 
    unidade_id: Optional[int] = None,
    bypass_cache: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Carrega a configuração de integração ativa de uma empresa.
    Tenta primeiro por unidade, se não houver, busca a global da empresa.
    """
    if not _database.db_pool:
        return None

    cache_key = f"cfg:integracao:{empresa_id}:{tipo}:{unidade_id or 'global'}"
    if not bypass_cache:
        cache = await redis_get_json(cache_key)
        if cache is not None:
            return cache

    try:
        if unidade_id:
            # Tenta unidade específica primeiro
            row = await _database.db_pool.fetchrow("""
                SELECT config FROM integracoes
                WHERE empresa_id = $1 AND tipo = $2 AND unidade_id = $3 AND ativo = true
                LIMIT 1
            """, empresa_id, tipo, unidade_id)
            if row:
                config = row['config']
                try:
                    if isinstance(config, str): config = json.loads(config)
                    await redis_set_json(cache_key, config, 300)
                    return config
                except Exception as e:
                    logger.error(f"Erro ao parsear config de integração {tipo} da unidade {unidade_id}: {e}")

        # Fallback para global
        row = await _database.db_pool.fetchrow("""
            SELECT config FROM integracoes
            WHERE empresa_id = $1 AND tipo = $2 AND unidade_id IS NULL AND ativo = true
            LIMIT 1
        """, empresa_id, tipo)
        
        if row:
            config = row['config']
            if isinstance(config, str): config = json.loads(config)
            # Auto-normaliza config aninhado legado: {"token": {"url":..., "access_token":...}}
            if isinstance(config.get('token'), dict):
                logger.warning(f"Config {tipo} da empresa {empresa_id} está aninhada — normalizando automaticamente")
                config = config['token']
                await _database.db_pool.execute(
                    "UPDATE integracoes SET config = $1 WHERE empresa_id = $2 AND tipo = $3 AND unidade_id IS NULL",
                    json.dumps(config), empresa_id, tipo
                )
            await redis_set_json(cache_key, config, 300)
            return config

        return None
    except asyncpg.PostgresError as e:
        logger.error(f"Erro PostgreSQL ao carregar integração {tipo} da empresa {empresa_id}: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"JSON inválido na integração {tipo} da empresa {empresa_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Erro inesperado ao carregar integração {tipo} da empresa {empresa_id}: {e}")
        return None


async def bd_salvar_resumo_ia(conversation_id: int, empresa_id: int, resumo: str):
    """
    Salva o resumo gerado pela IA para uma conversa específica.
    """
    if not _database.db_pool:
        return
    try:
        await _database.db_pool.execute(
            "UPDATE conversas SET resumo_ia = $1, updated_at = NOW() WHERE conversation_id = $2 AND empresa_id = $3",
            resumo, conversation_id, empresa_id
        )
    except Exception as e:
        logger.error(f"Erro ao salvar resumo IA para conversa {conversation_id} (emp={empresa_id}): {e}")

# --- FUNÇÕES PARA INTEGRAÇÃO EVO ---

async def buscar_planos_evo_da_api(
    empresa_id: int, 
    unidade_id: Optional[int] = None,
    bypass_cache: bool = False
) -> Optional[List[Dict]]:
    """
    Busca os planos (memberships) da academia via API Evo diretamente.
    """
    if not _database.db_pool:
        return None

    integracao = await carregar_integracao(empresa_id, 'evo', unidade_id=unidade_id, bypass_cache=bypass_cache)
    if not integracao:
        logger.info(f"ℹ️ Empresa {empresa_id} (Unid {unidade_id}) não tem integração Evo ativa")
        return None

    dns = integracao.get('dns')
    secret_key = integracao.get('secret_key')
    if not dns or not secret_key:
        logger.error(f"Integração Evo da empresa {empresa_id} incompleta: DNS ou Secret Key ausentes")
        return None

    api_base = integracao.get('api_url', 'https://evo-integracao-api.w12app.com.br/api/v2')
    url = (
        f"{api_base}/membership?take=100&skip=0&active=true"
        "&showAccessBranches=false&showOnlineSalesObservation=false"
        "&showActivitiesGroups=false"
    )
    
    # Se houver idBranch na config (multilocation), filtramos por ele
    id_branch = integracao.get('idBranch')
    if id_branch:
        url += f"&idBranch={id_branch}"

    auth = base64.b64encode(f"{dns}:{secret_key}".encode()).decode()
    headers = {'Authorization': f'Basic {auth}', 'accept': 'application/json'}

    data = None
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Forçamos HTTP/1.1 para evitar erros de chunked read comuns
            async with httpx.AsyncClient(http1=True) as client:
                logger.info(f"🔄 Chamando API Evo (Unid {unidade_id}, Tentativa {attempt+1}/{max_retries}): {url}")
                resp = await client.get(url, headers=headers, timeout=30.0)
                logger.info(f"💾 Status API Evo: {resp.status_code}")
                resp.raise_for_status()
                data = resp.json()
                # Logamos as chaves e o início da resposta para depuração (nível INFO para o usuário ver)
                logger.info(f"📦 Resposta EVO (Unid {unidade_id}) - Chaves: {list(data.keys()) if isinstance(data, dict) else 'Lista'}")
                if isinstance(data, dict) and 'data' in data:
                    logger.info(f"📊 Total de items na chave 'data': {len(data['data'])}")
                break # Sucesso
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError) as e:
            if attempt == max_retries - 1:
                logger.error(f"❌ Falha definitiva após {max_retries} tentativas: {e}")
                return None
            logger.warning(f"⚠️ Erro de conexão/protocolo ({e}). Tentando novamente em 1s...")
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Erro inesperado ao buscar planos Evo: {e}")
            return None
    
    if data is None:
        return None

    try:
        items = None
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            possible_keys = ['data', 'items', 'results', 'memberships', 'planos', 'lista', 'list']
            for key in possible_keys:
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    break
            if items is None:
                logger.error(f"Resposta da API Evo sem lista reconhecida. Chaves: {list(data.keys())}")
                return None
        else:
            logger.error(f"Formato inesperado da API Evo: {type(data)}")
            return None

        planos = []
        for item in items:
            if not isinstance(item, dict):
                continue
            diferenciais = item.get('differentials', [])
            if isinstance(diferenciais, list):
                diffs = [d.get('title') for d in diferenciais if isinstance(d, dict) and d.get('title')]
            else:
                diffs = []

            valor_total = item.get('value')
            valor_mensal = (valor_total / 12) if valor_total else 0

            valor_promo_total = item.get('valuePromotionalPeriod')
            valor_promo_mensal = (valor_promo_total / 12) if valor_promo_total else None

            plano = {
                'id': item.get('idMembership'),
                'nome': item.get('displayName') or item.get('nameMembership', 'Plano'),
                'valor': round(valor_mensal, 2) if valor_mensal else 0,
                'valor_promocional': round(valor_promo_mensal, 2) if valor_promo_mensal else None,
                'meses_promocionais': item.get('monthsPromotionalPeriod'),
                'descricao': item.get('description'),
                'diferenciais': diffs,
                'link_venda': item.get('urlSale'),
            }
            planos.append(plano)

        return planos

    except Exception as e:
        logger.error(f"Erro ao buscar planos Evo da API para empresa {empresa_id}: {e}")
        return None


async def sincronizar_planos_evo(
    empresa_id: int, 
    unidade_id: Optional[int] = None,
    bypass_cache: bool = False
) -> int:
    """
    Busca planos da API Evo e insere/atualiza na tabela planos.
    """
    if not _database.db_pool:
        return 0

    planos_api = await buscar_planos_evo_da_api(empresa_id, unidade_id=unidade_id, bypass_cache=bypass_cache)
    if not planos_api:
        return 0

    logger.info(f"✨ Encontrados {len(planos_api)} planos na API para empresa {empresa_id}")
    count = 0
    for p in planos_api:
        # Removida exigência de link_venda para permitir que a IA conheça todos os planos ativos

        # Se estamos sincronizando para uma unidade específica, o plano deve ser vinculado a ela.
        # Caso contrário, se for global, unidade_id no banco fica nulo.
        
        existing = await _database.db_pool.fetchval("""
            SELECT id FROM planos 
            WHERE empresa_id = $1 AND id_externo = $2 
              AND (unidade_id = $3 OR (unidade_id IS NULL AND $3 IS NULL))
        """, empresa_id, p['id'], unidade_id)

        if existing:
            await _database.db_pool.execute("""
                UPDATE planos SET
                    nome = $1, valor = $2, valor_promocional = $3, meses_promocionais = $4,
                    descricao = $5, diferenciais = $6, link_venda = $7, updated_at = NOW()
                WHERE id = $8
            """, p['nome'], p['valor'], p['valor_promocional'], p['meses_promocionais'],
               p['descricao'], p['diferenciais'], p['link_venda'], existing)
        else:
            await _database.db_pool.execute("""
                INSERT INTO planos
                    (empresa_id, unidade_id, id_externo, nome, valor, valor_promocional, meses_promocionais,
                     descricao, diferenciais, link_venda, ativo, ordem)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, true, 0)
            """, empresa_id, unidade_id, p['id'], p['nome'], p['valor'], p['valor_promocional'],
               p['meses_promocionais'], p['descricao'], p['diferenciais'], p['link_venda'])
            count += 1

    await redis_client.delete(f"planos:ativos:{empresa_id}:{unidade_id or 'todos'}")
    logger.info(f"✅ Sincronizados {count} novos planos para empresa {empresa_id} (Unid {unidade_id})")
    return count


async def buscar_planos_ativos(empresa_id: int, unidade_id: int = None, force_sync: bool = False) -> List[Dict]:
    """
    Retorna planos ativos da empresa, ordenados por ordem e nome.
    """
    if not _database.db_pool:
        return []

    cache_key = f"planos:ativos:{empresa_id}:{unidade_id or 'todos'}"
    cached = await redis_get_json(cache_key)
    if cached is not None:
        return cached

    query = """
        SELECT * FROM planos
        WHERE empresa_id = $1 AND ativo = true
          AND link_venda IS NOT NULL AND link_venda != ''
    """
    params = [empresa_id]
    if unidade_id:
        query += " AND (unidade_id = $2 OR unidade_id IS NULL)"
        params.append(unidade_id)
    query += " ORDER BY ordem, nome"

    rows = await _database.db_pool.fetch(query, *params)
    planos = [dict(r) for r in rows]

    if not planos and force_sync:
        logger.info(f"🔄 Nenhum plano ativo no banco para empresa {empresa_id}. Tentando sincronizar da API...")
        await sincronizar_planos_evo(empresa_id)
        rows = await _database.db_pool.fetch(query, *params)
        planos = [dict(r) for r in rows]

        await redis_set_json(cache_key, planos, 60)
    return planos


def formatar_planos_para_prompt(planos: List[Dict]) -> str:
    """
    Formata planos para inserção no prompt da IA (texto técnico, sem markdown decorativo).
    """
    if not planos:
        return "Nenhum plano disponível no momento."

    linhas = []
    for p in planos:
        nome = p.get('nome', 'Plano')
        link = p.get('link_venda', '')
        if not link or link.strip() == '':
            continue

        try:
            valor_float = float(p['valor']) if p.get('valor') is not None else None
        except (TypeError, ValueError):
            valor_float = None

        try:
            promocao_float = float(p['valor_promocional']) if p.get('valor_promocional') is not None else None
        except (TypeError, ValueError):
            promocao_float = None

        meses_promo = p.get('meses_promocionais')
        diferenciais = p.get('diferenciais', [])

        linha = f"- {nome}"
        if valor_float and valor_float > 0:
            linha += f": R$ {valor_float:.2f}/mes"
        if promocao_float and meses_promo and promocao_float > 0:
            linha += f" (promocao {meses_promo} mes(es) por R$ {promocao_float:.2f})"
        if diferenciais:
            diffs_str = ", ".join(diferenciais) if isinstance(diferenciais, list) else str(diferenciais)
            linha += f" | Diferenciais: {diffs_str}"
        linha += f" | Link: {link}"
        linhas.append(linha)

    return "\n".join(linhas) if linhas else "Nenhum plano disponível no momento."


# ── Distributed Leader Election ──────────────────────────────────────────────
# Garante que apenas UM processo (worker uvicorn) execute cada worker periódico.
# Sem isso, `uvicorn --workers 4` rodaria 4 instâncias de cada worker.
# Mecanismo: SET NX EX no Redis — quem grava a chave vira líder por `ttl` segundos.
# O líder renova a cada ciclo; os outros ficam dormindo e tentam novamente.

async def _is_worker_leader(nome: str, ttl: int) -> bool:
    """
    Tenta assumir a liderança para o worker `nome`.
    Retorna True se este processo é o líder (ou renovou a liderança).
    Retorna False se outro processo já é líder.
    ttl deve ser ligeiramente maior que o intervalo do worker.
    """
    chave = f"worker_leader:{nome}"
    # Tenta criar (NX = only if Not eXists)
    try:
        ganhou = await redis_client.set(chave, _WORKER_ID, nx=True, ex=ttl)
        if ganhou:
            return True
        # Verifica se JÁ é o líder atual (renovação)
        lider_atual = await redis_client.get(chave)
        if lider_atual == _WORKER_ID:
            await redis_client.expire(chave, ttl)  # renova TTL
            return True
        return False
    except asyncio.CancelledError:
        raise
    except redis.RedisError as e:
        if not _get_is_shutting_down():
            logger.warning(f"⚠️ Falha ao verificar liderança do worker '{nome}': {e}")
        return False


async def listar_unidades_ativas(empresa_id: int) -> List[Dict[str, Any]]:
    if not _database.db_pool:
        return []

    try:
        empresa_id = int(empresa_id)
    except (ValueError, TypeError):
        logger.error(f"❌ empresa_id inválido: {empresa_id} (tipo: {type(empresa_id)})")
        return []

    cache_key = f"cfg:unidades:lista:empresa:{empresa_id}"
    cache = await redis_get_json(cache_key)
    if cache is not None:
        return cache

    try:
        query = """
            SELECT
                u.id,
                u.uuid,
                u.slug,
                u.nome,
                u.nome_abreviado,
                u.cidade,
                u.bairro,
                u.estado,
                CASE WHEN u.numero IS NOT NULL AND TRIM(u.numero) <> ''
                    THEN u.endereco || ', ' || u.numero
                    ELSE u.endereco
                END as endereco_completo,
                u.telefone_principal as telefone,
                u.whatsapp,
                u.horarios,
                u.modalidades,
                u.planos,
                u.formas_pagamento,
                u.convenios,
                u.infraestrutura,
                u.servicos,
                u.palavras_chave,
                u.link_matricula,
                u.foto_grade,
                u.link_tour_virtual,
                u.site,
                u.instagram,
                e.nome as nome_empresa
            FROM unidades u
            JOIN empresas e ON e.id = u.empresa_id
            WHERE u.ativa = true AND u.empresa_id = $1
            ORDER BY u.ordem_exibicao, u.nome
        """
        rows = await _database.db_pool.fetch(query, empresa_id)
        data = [dict(r) for r in rows]
        await redis_set_json(cache_key, data, 60)
        return data
    except asyncpg.PostgresError as e:
        logger.error(f"Erro PostgreSQL ao listar unidades para empresa {empresa_id}: {e}")
        if PROMETHEUS_OK:
            METRIC_ERROS_TOTAL.labels(tipo="db_unidades_lista").inc()
        return []
    except Exception as e:
        logger.error(f"Erro inesperado ao listar unidades: {e}")
        return []


async def buscar_unidade_na_pergunta(texto: str, empresa_id: int, fuzzy_threshold: int = 90) -> Optional[str]:
    """
    Tenta identificar uma unidade mencionada na pergunta do cliente.
    Estratégia em 4 camadas:
      1. Função SQL customizada (se existir)
      2. Correspondência exata/parcial em nome, cidade, bairro e palavras-chave
      3. Correspondência por partes (tokens) — suporta nomes compostos e abreviações
      4. Fuzzy matching conservador (threshold ajustável)
    """
    if not _database.db_pool or not texto:
        return None

    from src.utils.intent_helpers import eh_saudacao
    # Ignora saudações genéricas mas NÃO ignora nomes de bairros de 1 palavra (Itaquera, Paulista...)
    if eh_saudacao(texto):
        return None

    # 1. Função SQL customizada (mais precisa, se disponível no banco)
    try:
        query = "SELECT unidade_slug FROM buscar_unidades_por_texto($1, $2) LIMIT 1"
        row = await _database.db_pool.fetchrow(query, empresa_id, texto)
        if row:
            return row['unidade_slug']
    except asyncpg.UndefinedFunctionError:
        pass  # Função não existe no banco — usa fallback Python
    except asyncpg.PostgresError as e:
        logger.error(f"Erro SQL ao buscar unidade: {e}")

    # 2. Busca por palavras-chave, nome, cidade e bairro
    unidades = await listar_unidades_ativas(empresa_id)
    texto_norm = normalizar(texto)
    tokens_texto = set(texto_norm.split())

    # Pré-lista de slugs candidatos com pontuação
    candidatos = []

    for u in unidades:
        slug = u['slug']
        nome_u = normalizar(u.get('nome', ''))
        cidade_u = normalizar(u.get('cidade', '') or '')
        bairro_u = normalizar(u.get('bairro', '') or '')
        palavras_chave = [normalizar(p) for p in (u.get('palavras_chave') or []) if p]

        # Camada A: Match exato do nome da unidade ou cidade/bairro específicos
        if nome_u and nome_u in texto_norm:
            candidatos.append((slug, 100))
            continue
        
        # Cidades/Bairros só contam se tiverem tamanho mínimo ou forem tokens exatos
        if (cidade_u and len(cidade_u) >= 4 and cidade_u in texto_norm) or (cidade_u in tokens_texto):
            candidatos.append((slug, 90))
            continue
        if (bairro_u and len(bairro_u) >= 4 and bairro_u in texto_norm) or (bairro_u in tokens_texto):
            candidatos.append((slug, 90))
            continue

        for p in palavras_chave:
            if (len(p) >= 4 and p in texto_norm) or (p in tokens_texto):
                candidatos.append((slug, 85))
                break

        # Camada B: Token matching (ex: "Ourinhos")
        tokens_nome = {t for t in nome_u.split() if len(t) >= 4 and t not in {"red", "fitness", "academia", "unidade"}}
        tokens_sig_texto = {t for t in tokens_texto if len(t) >= 4}
        
        interseccao = tokens_sig_texto & tokens_nome
        if interseccao:
            # Se o token for exatamente o nome da cidade ou bairro, alta confiança
            if any(t in {cidade_u, bairro_u} for t in interseccao):
                candidatos.append((slug, 95))
            else:
                candidatos.append((slug, 70 + (len(interseccao) * 10)))

    if candidatos:
        # Retorna o slug com maior pontuação
        candidatos.sort(key=lambda x: x[1], reverse=True)
        return candidatos[0][0]

    # 3. Fuzzy matching conservador
    melhor_slug = None
    maior_score = 0
    for u in unidades:
        nome_norm = normalizar(u.get('nome', ''))
        for campo in filter(None, [nome_norm, normalizar(u.get('cidade', '')), normalizar(u.get('bairro', ''))]):
            score = fuzz.partial_ratio(campo, texto_norm)
            if score > maior_score:
                maior_score = score
                melhor_slug = u['slug']

    if maior_score >= fuzzy_threshold:
        return melhor_slug
    return None


async def carregar_unidade(slug: str, empresa_id: int) -> Dict[str, Any]:
    if not _database.db_pool:
        return {}

    cache_key = f"cfg:unidade:{empresa_id}:{slug}:v2"
    cache = await redis_get_json(cache_key)
    if cache is not None:
        return cache

    try:
        query = """
            SELECT
                u.*,
                e.nome as nome_empresa,
                e.config as config_empresa
            FROM unidades u
            JOIN empresas e ON e.id = u.empresa_id
            WHERE u.slug = $1 AND u.ativa = true AND u.empresa_id = $2
        """
        row = await _database.db_pool.fetchrow(query, slug, empresa_id)
        if row:
            dados = dict(row)
            await redis_set_json(cache_key, dados, 60)
            return dados
        return {}
    except Exception as e:
        logger.error(f"Erro ao carregar unidade {slug}: {e}")
        return {}


async def buscar_resposta_faq(pergunta: str, slug: str, empresa_id: int) -> Optional[str]:
    """
    Tenta encontrar uma resposta direta no FAQ sem precisar chamar a IA.
    Usa sobreposição de tokens (palavras significativas) entre a pergunta do
    cliente e as perguntas cadastradas no FAQ.
    Retorna a resposta do FAQ se similaridade >= threshold, senão None.
    """
    if not _database.db_pool or not slug or not pergunta:
        return None

    cache_key = f"cfg:faq_raw:v2:{empresa_id}:{slug}"
    raw = await redis_client.get(cache_key)
    if raw:
        try:
            faq_rows = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            faq_rows = []
    else:
        try:
            faq_rows_db = await _database.db_pool.fetch("""
                SELECT f.pergunta, f.resposta
                FROM faq f
                WHERE f.empresa_id = $2 AND f.ativo = true
                  AND (
                      f.todas_unidades = true
                      OR f.unidade_id = (SELECT id FROM unidades WHERE slug = $1 AND empresa_id = $2)
                      OR (SELECT id FROM unidades WHERE slug = $1 AND empresa_id = $2) = ANY(f.unidades_ids)
                  )
                ORDER BY f.prioridade DESC NULLS LAST
                LIMIT 50
            """, slug, empresa_id)
            faq_rows = [{"pergunta": r["pergunta"], "resposta": r["resposta"]} for r in faq_rows_db]
            await redis_client.setex(cache_key, 300, json.dumps(faq_rows, ensure_ascii=False))
        except Exception:
            return None

    if not faq_rows:
        return None

    # Tokeniza a pergunta do cliente (palavras com >= 3 chars)
    pergunta_norm = normalizar(pergunta)
    tokens_cliente = {t for t in pergunta_norm.split() if len(t) >= 3}
    if not tokens_cliente:
        return None

    intencao_cliente = classificar_intencao(pergunta)

    melhor_score = 0.0
    melhor_resposta = None

    for item in faq_rows:
        if not _faq_compativel_com_intencao(intencao_cliente, item.get("pergunta", "")):
            continue
        tokens_faq = {t for t in normalizar(item["pergunta"]).split() if len(t) >= 3}
        if not tokens_faq:
            continue
        # Jaccard: intersecção / união
        intersecao = tokens_cliente & tokens_faq
        uniao = tokens_cliente | tokens_faq
        score = len(intersecao) / len(uniao) if uniao else 0.0
        if score > melhor_score:
            melhor_score = score
            melhor_resposta = item["resposta"]

    # Threshold dinâmico: intents factuais exigem match mais forte para evitar respostas erradas.
    threshold = 0.55 if intencao_cliente in {"modalidades", "planos", "horario", "endereco"} else 0.40
    if melhor_score >= threshold and melhor_resposta:
        logger.info(f"✅ FAQ fast-match (score={melhor_score:.2f}): '{pergunta[:50]}' → FAQ direto")
        return melhor_resposta.strip()

    return None


async def carregar_faq_unidade(slug: str, empresa_id: int) -> str:
    """
    Carrega as perguntas frequentes da unidade e retorna formatadas para o prompt da IA.
    Tenta duas queries: com prioridade+visualizacoes, e fallback sem visualizacoes
    (caso a coluna ainda não exista no banco).
    Loga aviso quando FAQ está vazio para facilitar diagnóstico.
    """
    if not _database.db_pool:
        return ""

    cache_key = f"cfg:faq:{empresa_id}:{slug}:v5"
    cache = await redis_client.get(cache_key)
    if cache:
        return cache

    rows = []
    try:
        # Query principal — unidade específica, múltiplas unidades ou todas
        rows = await _database.db_pool.fetch("""
            SELECT f.pergunta, f.resposta
            FROM faq f
            WHERE f.empresa_id = $2 AND f.ativo = true
              AND (
                  f.todas_unidades = true
                  OR f.unidade_id = (SELECT id FROM unidades WHERE slug = $1 AND empresa_id = $2)
                  OR (SELECT id FROM unidades WHERE slug = $1 AND empresa_id = $2) = ANY(f.unidades_ids)
              )
            ORDER BY f.prioridade DESC NULLS LAST, f.visualizacoes DESC NULLS LAST
            LIMIT 30
        """, slug, empresa_id)
    except asyncpg.UndefinedColumnError:
        # Fallback: sem a coluna visualizacoes
        try:
            rows = await _database.db_pool.fetch("""
                SELECT f.pergunta, f.resposta
                FROM faq f
                WHERE f.empresa_id = $2 AND f.ativo = true
                  AND (
                      f.todas_unidades = true
                      OR f.unidade_id = (SELECT id FROM unidades WHERE slug = $1 AND empresa_id = $2)
                      OR (SELECT id FROM unidades WHERE slug = $1 AND empresa_id = $2) = ANY(f.unidades_ids)
                  )
                ORDER BY f.prioridade DESC NULLS LAST
                LIMIT 30
            """, slug, empresa_id)
        except asyncpg.UndefinedTableError:
            logger.warning(f"⚠️ Tabela 'faq' não existe no banco — FAQ desativado para {slug}")
            return ""
    except asyncpg.UndefinedTableError:
        logger.warning(f"⚠️ Tabela 'faq' não existe no banco — crie com CREATE TABLE faq (...)")
        return ""
    except asyncpg.PostgresError as e:
        logger.error(f"Erro PostgreSQL ao carregar FAQ de {slug}: {e}")
        return ""

    if not rows:
        logger.warning(f"⚠️ FAQ vazio para slug='{slug}' empresa_id={empresa_id} — verifique ativo=true e unidade_id")
        return ""

    faq_formatado = "\n\n".join([
        f"P: {r['pergunta']}\nR: {r['resposta']}"
        for r in rows
    ])
    await redis_client.setex(cache_key, 300, faq_formatado)
    logger.info(f"✅ FAQ carregado: {len(rows)} perguntas para {slug}")
    return faq_formatado


async def carregar_personalidade(empresa_id: int) -> Dict[str, Any]:
    if not _database.db_pool:
        return {}

    cache_key = f"cfg:pers:empresa:{empresa_id}"
    dados_cache = await redis_get_json(cache_key)
    if dados_cache is not None:
        if dados_cache.get('ativo') is True:
            return dados_cache
        else:
            await redis_client.delete(cache_key)

    try:
        query = """
            SELECT p.*
            FROM personalidade_ia p
            WHERE p.empresa_id = $1 AND p.ativo = true
            LIMIT 1
        """
        row = await _database.db_pool.fetchrow(query, empresa_id)
        if row:
            dados = dict(row)
            for key, value in dados.items():
                if isinstance(value, Decimal):
                    dados[key] = float(value)
            await redis_set_json(cache_key, dados, 300)
            return dados
        else:
            await redis_set_json(cache_key, {}, 60)
            return {}
    except Exception as e:
        logger.error(f"Erro ao carregar personalidade da empresa {empresa_id}: {e}")
        return {}


async def carregar_configuracao_global(empresa_id: int) -> Dict[str, Any]:
    if not _database.db_pool:
        return {}

    cache_key = f"cfg:global:empresa:{empresa_id}"
    cache = await redis_get_json(cache_key)
    if cache is not None:
        return cache

    try:
        query = "SELECT config, nome, plano FROM empresas WHERE id = $1"
        row = await _database.db_pool.fetchrow(query, empresa_id)
        if row:
            config_data = row['config']
            if config_data is None:
                config = {}
            elif isinstance(config_data, str):
                try:
                    config = json.loads(config_data)
                except json.JSONDecodeError:
                    config = {}
            else:
                config = config_data
            config['nome_empresa'] = row['nome']
            config['plano'] = row['plano']
            await redis_client.setex(cache_key, 3600, json.dumps(config, default=str))
            return config
        return {}
    except Exception as e:
        logger.error(f"Erro ao carregar config global: {e}")
        return {}


# --- AUXILIARES BANCO DE DADOS ---

def log_db_error(retry_state):
    logger.error(f"Erro BD após {retry_state.attempt_number} tentativas: {retry_state.outcome.exception()}")
    return None


@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_iniciar_conversa(
    conversation_id: int, slug: str, account_id: int,
    contato_id: int = None, contato_nome: str = None, empresa_id: int = None,
    contato_fone: str = None, canal: str = "WhatsApp"
):
    if not _database.db_pool:
        return
    try:
        unidade_id = None
        if slug and slug != "uazapi":
            unidade = await _database.db_pool.fetchrow(
                "SELECT id FROM unidades WHERE slug = $1 AND empresa_id = $2", slug, empresa_id
            )
            if unidade:
                unidade_id = unidade['id']
            else:
                logger.warning(f"Unidade {slug} não encontrada para empresa {empresa_id}. Prosseguindo sem unidade_id.")
        await _database.db_pool.execute("""
            INSERT INTO conversas (conversation_id, account_id, contato_id, contato_nome, contato_fone, empresa_id, unidade_id, canal, primeira_mensagem, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), 'ativa')
            ON CONFLICT (conversation_id, empresa_id) DO UPDATE SET
                contato_nome = COALESCE(NULLIF(EXCLUDED.contato_nome, ''), conversas.contato_nome),
                contato_fone = COALESCE(NULLIF(EXCLUDED.contato_fone, ''), conversas.contato_fone),
                contato_telefone = COALESCE(NULLIF(EXCLUDED.contato_fone, ''), conversas.contato_telefone),
                canal = COALESCE(conversas.canal, EXCLUDED.canal),
                unidade_id = EXCLUDED.unidade_id,
                status = 'ativa',
                updated_at = NOW()
        """, conversation_id, account_id, contato_id, contato_nome, contato_fone, empresa_id, unidade_id, canal)
    except Exception as e:
        logger.error(f"❌ Erro ao iniciar conversa {conversation_id} (emp={empresa_id}): {e}")


@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_salvar_mensagem_local(
    conversation_id: int, empresa_id: int, role: str, content: str,
    tipo: str = 'texto', url_midia: str = None
):
    if not _database.db_pool:
        return
    try:
        conversa = await _database.db_pool.fetchrow(
            "SELECT id FROM conversas WHERE conversation_id = $1 AND empresa_id = $2", conversation_id, empresa_id
        )
        if not conversa:
            logger.error(f"Conversa {conversation_id} não encontrada para empresa {empresa_id}.")
            return
        await _database.db_pool.execute("""
            INSERT INTO mensagens (conversa_id, empresa_id, role, tipo, conteudo, url_midia, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
        """, conversa['id'], empresa_id, role, tipo, content, url_midia)
        logger.info(f"✅ Mensagem {role} salva para conversa {conversation_id} (id_db={conversa['id']}, emp={empresa_id})")
    except Exception as e:
        logger.error(f"Erro ao salvar mensagem para conversa {conversation_id} (emp={empresa_id}): {e}")


async def buscar_conversa_por_fone(contato_fone: str, empresa_id: int) -> Optional[Dict]:
    """
    Busca uma conversa ativa pelo número de telefone e empresa.
    Útil para integração direta com WhatsApp (UazAPI).
    """
    if not _database.db_pool or not contato_fone:
        return None

    cache_key = f"conv:fone:{contato_fone}:{empresa_id}"
    cached = await redis_get_json(cache_key)
    if cached:
        return cached

    try:
        query = """
            SELECT c.*, u.slug as unidade_slug
            FROM conversas c
            JOIN unidades u ON u.id = c.unidade_id
            WHERE c.contato_fone = $1 AND c.empresa_id = $2
            ORDER BY c.updated_at DESC
            LIMIT 1
        """
        row = await _database.db_pool.fetchrow(query, contato_fone, empresa_id)
        if row:
            dados = dict(row)
            await redis_set_json(cache_key, dados, 300)
            return dados
        return None
    except Exception as e:
        logger.error(f"Erro ao buscar conversa por fone {contato_fone}: {e}")
        return None


async def bd_obter_historico_local(conversation_id: int, empresa_id: int, limit: int = 12) -> Optional[str]:
    if not _database.db_pool:
        return None
    try:
        rows = await _database.db_pool.fetch("""
            SELECT m.role, m.conteudo
            FROM mensagens m
            JOIN conversas c ON c.id = m.conversa_id
            WHERE c.conversation_id = $1 AND c.empresa_id = $2
            ORDER BY m.created_at DESC
            LIMIT $3
        """, conversation_id, empresa_id, limit)
        msgs = list(reversed(rows))
        return "\n".join([
            f"{'Cliente' if r['role'] == 'user' else 'Atendente'}: {r['conteudo']}"
            for r in msgs
        ])
    except Exception as e:
        logger.error(f"Erro ao obter histórico para conv {conversation_id} (emp={empresa_id}): {e}")
        return None


@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_atualizar_msg_cliente(conversation_id: int, empresa_id: int):
    if not _database.db_pool:
        return
    try:
        await _database.db_pool.execute("""
            UPDATE conversas
            SET total_mensagens_cliente = total_mensagens_cliente + 1,
                ultima_mensagem = NOW(), updated_at = NOW()
            WHERE conversation_id = $1 AND empresa_id = $2
        """, conversation_id, empresa_id)
    except Exception as e:
        logger.error(f"Erro ao atualizar msg cliente {conversation_id} (emp={empresa_id}): {e}")


@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_atualizar_msg_ia(conversation_id: int, empresa_id: int):
    if not _database.db_pool:
        return
    try:
        await _database.db_pool.execute("""
            UPDATE conversas
            SET total_mensagens_ia = total_mensagens_ia + 1,
                ultima_mensagem = NOW(), updated_at = NOW()
            WHERE conversation_id = $1 AND empresa_id = $2
        """, conversation_id, empresa_id)
    except Exception as e:
        logger.error(f"Erro ao atualizar msg ia {conversation_id} (emp={empresa_id}): {e}")


@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_registrar_primeira_resposta(conversation_id: int, empresa_id: int):
    if not _database.db_pool:
        return
    try:
        await _database.db_pool.execute("""
            UPDATE conversas
            SET primeira_resposta_em = NOW(), updated_at = NOW()
            WHERE conversation_id = $1 AND empresa_id = $2 AND primeira_resposta_em IS NULL
        """, conversation_id, empresa_id)
    except Exception as e:
        logger.error(f"Erro ao registrar primeira resposta {conversation_id} (emp={empresa_id}): {e}")


@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_registrar_evento_funil(
    conversation_id: int, empresa_id: int, tipo_evento: str,
    descricao: str, score_incremento: int = 5
):
    if not _database.db_pool:
        return
    try:
        conversa = await _database.db_pool.fetchrow(
            "SELECT id FROM conversas WHERE conversation_id = $1 AND empresa_id = $2", conversation_id, empresa_id
        )
        if not conversa:
            return
        conversa_id = conversa['id']
        empresa_id = conversa['empresa_id']

        # Deduplicação: Garante que cada tipo de evento seja registrado apenas UMA vez por conversa
        existe = await _database.db_pool.fetchval("""
            SELECT 1 FROM eventos_funil
            WHERE conversa_id = $1 AND tipo_evento = $2
        """, conversa_id, tipo_evento)
        
        if existe:
            return

        await _database.db_pool.execute("""
            INSERT INTO eventos_funil (conversa_id, empresa_id, tipo_evento, descricao, score_incremento, created_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
        """, conversa_id, empresa_id, tipo_evento, descricao, score_incremento)

        await _database.db_pool.execute("""
            UPDATE conversas
            SET score_interesse = COALESCE(score_interesse, 0) + $2,
                score_lead = LEAST(5, COALESCE(score_lead, 0) + $2),
                updated_at = NOW()
            WHERE id = $1
        """, conversa_id, score_incremento)

        if tipo_evento == "interesse_detectado":
            await _database.db_pool.execute(
                "UPDATE conversas SET lead_qualificado = TRUE WHERE id = $1", conversa_id
            )
    except Exception as e:
        logger.error(f"Erro ao registrar evento funil {conversation_id}: {e}")


@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_finalizar_conversa(conversation_id: int, empresa_id: int):
    if not _database.db_pool:
        return
    try:
        conversa = await _database.db_pool.fetchrow(
            "SELECT id FROM conversas WHERE conversation_id = $1 AND empresa_id = $2", conversation_id, empresa_id
        )
        if not conversa:
            return

        await _database.db_pool.execute("""
            UPDATE conversas
            SET status = 'encerrada', encerrada_em = NOW(), updated_at = NOW()
            WHERE id = $1
        """, conversa['id'])

        await _database.db_pool.execute("""
            UPDATE followups SET status = 'cancelado', updated_at = NOW()
            WHERE conversa_id = $1 AND status = 'pendente'
        """, conversa['id'])

        logger.info(f"✅ Conversa {conversation_id} finalizada (emp={empresa_id})")
    except Exception as e:
        logger.error(f"Erro ao finalizar conversa {conversation_id} (emp={empresa_id}): {e}")


# --- WORKER DE MÉTRICAS DIÁRIAS ---

async def _coletar_metricas_unidade(empresa_id: int, unidade_id: int, hoje) -> Dict:
    """
    Coleta TODAS as métricas para uma unidade em determinada data.
    Retorna dict pronto para inserção em metricas_diarias.
    Cada query usa COALESCE para nunca retornar NULL.
    """
    # ── Conversas ──────────────────────────────────────────────────────
    total_conversas = await _database.db_pool.fetchval("""
        SELECT COUNT(DISTINCT contato_telefone) FROM conversas
        WHERE empresa_id = $1 AND unidade_id = $2
          AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0

    conversas_encerradas = await _database.db_pool.fetchval("""
        SELECT COUNT(DISTINCT contato_telefone) FROM conversas
        WHERE empresa_id = $1 AND unidade_id = $2
          AND status IN ('encerrada', 'resolved', 'closed')
          AND DATE(updated_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0

    conversas_sem_resposta = await _database.db_pool.fetchval("""
        SELECT COUNT(*) FROM conversas
        WHERE empresa_id = $1 AND unidade_id = $2
          AND primeira_resposta_em IS NULL
          AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0

    novos_contatos = await _database.db_pool.fetchval("""
        SELECT COUNT(DISTINCT contato_telefone) FROM conversas
        WHERE empresa_id = $1 AND unidade_id = $2
          AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
          AND NOT EXISTS (
              SELECT 1 FROM conversas c2
              WHERE c2.empresa_id = $1
                AND c2.contato_telefone = conversas.contato_telefone
                AND c2.created_at < conversas.created_at
          )
    """, empresa_id, unidade_id, hoje) or 0

    # ── Mensagens ──────────────────────────────────────────────────────
    total_mensagens = await _database.db_pool.fetchval("""
        SELECT COUNT(*) FROM mensagens m
        JOIN conversas c ON c.id = m.conversa_id
        WHERE c.empresa_id = $1 AND c.unidade_id = $2
          AND DATE(m.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
          AND m.role = 'user'
    """, empresa_id, unidade_id, hoje) or 0

    total_mensagens_ia = await _database.db_pool.fetchval("""
        SELECT COUNT(*) FROM mensagens m
        JOIN conversas c ON c.id = m.conversa_id
        WHERE c.empresa_id = $1 AND c.unidade_id = $2
          AND DATE(m.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
          AND m.role = 'assistant'
    """, empresa_id, unidade_id, hoje) or 0

    # ── Leads & Conversão ──────────────────────────────────────────────
    leads_qualificados = await _database.db_pool.fetchval("""
        SELECT COUNT(DISTINCT contato_telefone) FROM conversas
        WHERE empresa_id = $1 AND unidade_id = $2
          AND lead_qualificado = true
          AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0

    # taxa_conversao = leads / total_conversas (0.0 se sem conversas)
    taxa_conversao = round(leads_qualificados / total_conversas, 4) if total_conversas > 0 else 0.0

    # ── Tempo de Resposta ──────────────────────────────────────────────
    tempo_medio_resposta = await _database.db_pool.fetchval("""
        SELECT COALESCE(
            AVG(EXTRACT(EPOCH FROM (primeira_resposta_em - primeira_mensagem))),
            0
        )
        FROM conversas
        WHERE empresa_id = $1 AND unidade_id = $2
          AND primeira_resposta_em IS NOT NULL
          AND primeira_mensagem IS NOT NULL
          AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0.0

    # ── Eventos do Funil ───────────────────────────────────────────────
    total_solicitacoes_telefone = await _database.db_pool.fetchval("""
        SELECT COUNT(*) FROM eventos_funil ef
        JOIN conversas c ON c.id = ef.conversa_id
        WHERE c.empresa_id = $1 AND c.unidade_id = $2
          AND ef.tipo_evento = 'solicitacao_telefone'
          AND DATE(ef.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0

    total_links_enviados = await _database.db_pool.fetchval("""
        SELECT COUNT(*) FROM eventos_funil ef
        JOIN conversas c ON c.id = ef.conversa_id
        WHERE c.empresa_id = $1 AND c.unidade_id = $2
          AND ef.tipo_evento = 'link_matricula_enviado'
          AND DATE(ef.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0

    total_planos_enviados = await _database.db_pool.fetchval("""
        SELECT COUNT(*) FROM eventos_funil ef
        JOIN conversas c ON c.id = ef.conversa_id
        WHERE c.empresa_id = $1 AND c.unidade_id = $2
          AND ef.tipo_evento = 'plano_exibido'
          AND DATE(ef.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0

    total_matriculas = await _database.db_pool.fetchval("""
        SELECT COUNT(*) FROM eventos_funil ef
        JOIN conversas c ON c.id = ef.conversa_id
        WHERE c.empresa_id = $1 AND c.unidade_id = $2
          AND ef.tipo_evento IN ('matricula_realizada', 'checkout_concluido')
          AND DATE(ef.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
    """, empresa_id, unidade_id, hoje) or 0

    # ── Horário de Pico ────────────────────────────────────────────────
    # Hora com maior volume de mensagens recebidas
    pico_row = await _database.db_pool.fetchrow("""
        SELECT EXTRACT(HOUR FROM m.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo')::int AS hora,
               COUNT(*) AS qtd
        FROM mensagens m
        JOIN conversas c ON c.id = m.conversa_id
        WHERE c.empresa_id = $1 AND c.unidade_id = $2
          AND m.role = 'user'
          AND DATE(m.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
        GROUP BY hora
        ORDER BY qtd DESC
        LIMIT 1
    """, empresa_id, unidade_id, hoje)
    pico_hora = int(pico_row['hora']) if pico_row else None

    # ── Satisfação Média ──────────────────────────────────────────────
    # Tenta buscar da tabela `avaliacoes` se existir; senão mantém NULL
    satisfacao_media = None
    try:
        satisfacao_media = await _database.db_pool.fetchval("""
            SELECT COALESCE(AVG(nota), NULL)
            FROM avaliacoes av
            JOIN conversas c ON c.id = av.conversa_id
            WHERE c.empresa_id = $1 AND c.unidade_id = $2
              AND DATE(av.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
        """, empresa_id, unidade_id, hoje)
    except Exception:
        satisfacao_media = None  # tabela ainda não existe

    # ── Tokens / Custo IA ─────────────────────────────────────────────
    tokens_consumidos = None
    custo_estimado_usd = None
    try:
        row_tokens = await _database.db_pool.fetchrow("""
            SELECT COALESCE(SUM(tokens_prompt + tokens_completion), 0) AS total_tokens,
                   COALESCE(SUM(custo_usd), 0.0) AS custo
            FROM uso_ia ui
            JOIN conversas c ON c.id = ui.conversa_id
            WHERE c.empresa_id = $1 AND c.unidade_id = $2
              AND DATE(ui.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = $3
        """, empresa_id, unidade_id, hoje)
        if row_tokens:
            tokens_consumidos = int(row_tokens['total_tokens'])
            custo_estimado_usd = float(row_tokens['custo'])
    except Exception:
        pass  # tabela uso_ia pode não existir

    return {
        "total_conversas": total_conversas,
        "conversas_encerradas": conversas_encerradas,
        "conversas_sem_resposta": conversas_sem_resposta,
        "novos_contatos": novos_contatos,
        "total_mensagens": total_mensagens,
        "total_mensagens_ia": total_mensagens_ia,
        "leads_qualificados": leads_qualificados,
        "taxa_conversao": taxa_conversao,
        "tempo_medio_resposta": float(tempo_medio_resposta),
        "total_solicitacoes_telefone": total_solicitacoes_telefone,
        "total_links_enviados": total_links_enviados,
        "total_planos_enviados": total_planos_enviados,
        "total_matriculas": total_matriculas,
        "pico_hora": pico_hora,
        "satisfacao_media": satisfacao_media,
        "tokens_consumidos": tokens_consumidos,
        "custo_estimado_usd": custo_estimado_usd,
    }


async def bd_atualizar_metricas_venda(conversation_id: int, empresa_id: int, link_venda_enviado: bool = False, intencao_de_compra: bool = False):
    """Atualiza as métricas de venda na tabela conversas, caso a IA demonstre intenção ou envie um link de venda."""
    if not _database.db_pool:
        return
        
    try:
        if link_venda_enviado or intencao_de_compra:
            update_queries = []
            if link_venda_enviado:
                update_queries.append("link_venda_enviado = TRUE")
            if intencao_de_compra:
                update_queries.append("intencao_de_compra = TRUE")
                
            set_clause = ", ".join(update_queries)
            
            await _database.db_pool.execute(f"""
                UPDATE conversas
                SET {set_clause}
                WHERE conversation_id = $1 AND empresa_id = $2
            """, conversation_id, empresa_id)
            logger.info(f"📊 Métricas atualizadas para conv={conversation_id} (emp={empresa_id}): link_enviado={link_venda_enviado}, intencao={intencao_de_compra}")
    except Exception as e:
        logger.error(f"❌ Erro ao atualizar métricas de venda para conv {conversation_id} (emp={empresa_id}): {e}")

# --- USUÁRIOS & DASHBOARD ---

async def buscar_usuario_por_email(email: str) -> Optional[Dict[str, Any]]:
    if not _database.db_pool:
        return None

    email_norm = (email or "").strip().lower()
    if not email_norm:
        return None

    try:
        row = await _database.db_pool.fetchrow(
            """
            SELECT *
            FROM usuarios
            WHERE lower(trim(email)) = $1
              AND COALESCE(ativo, true) = true
            LIMIT 1
            """,
            email_norm,
        )
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Erro ao buscar usuário {email_norm}: {e}")
        return None

async def criar_usuario(nome: str, email: str, senha_hash: str, empresa_id: int, perfil: str = 'atendente'):
    if not _database.db_pool:
        return None
    try:
        await _database.db_pool.execute("""
            INSERT INTO usuarios (nome, email, senha_hash, empresa_id, perfil)
            VALUES ($1, $2, $3, $4, $5)
        """, nome, email, senha_hash, empresa_id, perfil)
        return True
    except Exception as e:
        logger.error(f"Erro ao criar usuário {email}: {e}")
        return False
