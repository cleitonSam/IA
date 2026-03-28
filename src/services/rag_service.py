"""
RAG Service — Retrieval Augmented Generation
Busca conhecimento relevante na base de dados (knowledge_base) usando
similaridade de cosseno com embeddings.

Fluxo:
1. Cliente envia pergunta
2. Gera embedding da pergunta via API
3. Busca chunks mais similares no PostgreSQL
4. Retorna os top_k trechos mais relevantes para injetar no prompt

Storage: JSONB no PostgreSQL (funciona sem pgvector)
Similaridade: Computada em Python (cosine similarity)
Cache: Redis com TTL 5min para evitar recomputar buscas idênticas
"""
import json
import hashlib
from typing import Optional, List, Dict

from src.core.config import logger
from src.core.redis_client import redis_client
from src.services.db_queries import _database
from src.services.ia_processor import _get_embedding, _cosine_sim


# ── Busca de Conhecimento ───────────────────────────────────────────

async def buscar_conhecimento(
    query: str,
    empresa_id: int,
    top_k: int = 3,
    threshold: float = 0.72,
    categoria: str = None
) -> List[Dict]:
    """
    Busca os chunks mais relevantes da knowledge_base para a query.
    Retorna lista de dicts com titulo, conteudo e score.

    Usa cache Redis para queries idênticas (5min TTL).
    """
    if not query or len(query.strip()) < 10:
        return []

    # 1. Verifica cache
    query_hash = hashlib.md5(f"{query}:{empresa_id}:{categoria}".encode()).hexdigest()
    cache_key = f"{empresa_id}:rag_cache:{query_hash}"
    cached = await redis_client.get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except (json.JSONDecodeError, TypeError):
            pass

    # 2. Gera embedding da query
    query_embedding = await _get_embedding(query)
    if not query_embedding:
        return []  # API indisponível

    # 3. Busca chunks com embedding no PostgreSQL
    try:
        conditions = ["kb.empresa_id = $1", "kb.ativo = true", "kb.embedding IS NOT NULL"]
        params: list = [empresa_id]

        if categoria:
            params.append(categoria)
            conditions.append(f"kb.categoria = ${len(params)}")

        where = " AND ".join(conditions)

        rows = await _database.db_pool.fetch(f"""
            SELECT kb.id, kb.titulo, kb.conteudo, kb.categoria, kb.embedding
            FROM knowledge_base kb
            WHERE {where}
            ORDER BY kb.id
            LIMIT 200
        """, *params)

        if not rows:
            return []

        # 4. Computa similaridade em Python
        resultados = []
        for row in rows:
            try:
                emb_stored = row["embedding"]
                if isinstance(emb_stored, str):
                    emb_stored = json.loads(emb_stored)
                if not isinstance(emb_stored, list):
                    continue

                score = _cosine_sim(query_embedding, emb_stored)
                if score >= threshold:
                    resultados.append({
                        "id": row["id"],
                        "titulo": row["titulo"],
                        "conteudo": row["conteudo"],
                        "categoria": row["categoria"],
                        "score": round(score, 4),
                    })
            except (json.JSONDecodeError, TypeError, KeyError):
                continue

        # 5. Ordena por score e retorna top_k
        resultados.sort(key=lambda x: x["score"], reverse=True)
        top_results = resultados[:top_k]

        # 6. Salva no cache
        if top_results:
            await redis_client.setex(cache_key, 300, json.dumps(top_results))

        return top_results

    except Exception as e:
        logger.error(f"Erro ao buscar conhecimento RAG: {e}")
        return []


def formatar_rag_para_prompt(resultados: List[Dict]) -> str:
    """
    Formata os resultados do RAG para injeção no prompt do LLM.
    """
    if not resultados:
        return ""

    linhas = ["[BASE DE CONHECIMENTO — Informações relevantes encontradas]"]
    for i, r in enumerate(resultados, 1):
        linhas.append(f"\n--- Trecho {i} ({r.get('categoria', 'geral')}) ---")
        if r.get("titulo"):
            linhas.append(f"Título: {r['titulo']}")
        linhas.append(r["conteudo"])

    return "\n".join(linhas)


# ── Indexação de Documentos ─────────────────────────────────────────

async def indexar_documento(
    empresa_id: int,
    titulo: str,
    conteudo: str,
    categoria: str = "geral",
    source_file: str = None,
    chunk_size: int = 500,
    chunk_overlap: int = 50
) -> int:
    """
    Indexa um documento na knowledge_base.
    Divide o conteúdo em chunks, gera embeddings e salva no PostgreSQL.
    Retorna o número de chunks indexados.
    """
    if not conteudo or not conteudo.strip():
        return 0

    # Divide em chunks com overlap
    chunks = _chunk_text(conteudo, chunk_size, chunk_overlap)
    indexed = 0

    for i, chunk in enumerate(chunks):
        # Gera embedding do chunk
        embedding = await _get_embedding(chunk)

        try:
            await _database.db_pool.execute("""
                INSERT INTO knowledge_base
                    (empresa_id, titulo, conteudo, categoria, embedding, chunk_index, source_file)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
                empresa_id,
                f"{titulo} (parte {i + 1})" if len(chunks) > 1 else titulo,
                chunk,
                categoria,
                json.dumps(embedding) if embedding else None,
                i,
                source_file
            )
            indexed += 1
        except Exception as e:
            logger.error(f"Erro ao indexar chunk {i} de '{titulo}': {e}")

    # Invalida cache RAG da empresa
    async for key in redis_client.scan_iter(f"{empresa_id}:rag_cache:*", count=100):
        await redis_client.delete(key)

    logger.info(f"📚 RAG: Indexados {indexed}/{len(chunks)} chunks de '{titulo}' para empresa {empresa_id}")
    return indexed


async def reindexar_embeddings(empresa_id: int) -> int:
    """
    Reprocessa embeddings de todos os chunks da empresa que não têm embedding.
    Útil quando a API estava indisponível durante a indexação inicial.
    """
    try:
        rows = await _database.db_pool.fetch("""
            SELECT id, conteudo FROM knowledge_base
            WHERE empresa_id = $1 AND ativo = true AND embedding IS NULL
            ORDER BY id
            LIMIT 100
        """, empresa_id)

        updated = 0
        for row in rows:
            embedding = await _get_embedding(row["conteudo"])
            if embedding:
                await _database.db_pool.execute("""
                    UPDATE knowledge_base SET embedding = $1, updated_at = NOW()
                    WHERE id = $2
                """, json.dumps(embedding), row["id"])
                updated += 1

        logger.info(f"📚 RAG: Reindexados {updated}/{len(rows)} embeddings para empresa {empresa_id}")
        return updated
    except Exception as e:
        logger.error(f"Erro ao reindexar embeddings: {e}")
        return 0


async def listar_conhecimento(empresa_id: int, categoria: str = None) -> List[Dict]:
    """Lista documentos da base de conhecimento."""
    try:
        conditions = ["empresa_id = $1", "ativo = true"]
        params: list = [empresa_id]

        if categoria:
            params.append(categoria)
            conditions.append(f"categoria = ${len(params)}")

        where = " AND ".join(conditions)

        rows = await _database.db_pool.fetch(f"""
            SELECT id, titulo, categoria, chunk_index, source_file,
                   LENGTH(conteudo) AS tamanho,
                   embedding IS NOT NULL AS tem_embedding,
                   created_at
            FROM knowledge_base
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT 500
        """, *params)

        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Erro ao listar knowledge base: {e}")
        return []


async def deletar_conhecimento(empresa_id: int, kb_id: int) -> bool:
    """Desativa um item da knowledge base (soft delete)."""
    try:
        await _database.db_pool.execute("""
            UPDATE knowledge_base SET ativo = false, updated_at = NOW()
            WHERE id = $1 AND empresa_id = $2
        """, kb_id, empresa_id)

        # Invalida cache
        async for key in redis_client.scan_iter(f"{empresa_id}:rag_cache:*", count=100):
            await redis_client.delete(key)

        return True
    except Exception as e:
        logger.error(f"Erro ao deletar knowledge base item {kb_id}: {e}")
        return False


# ── Helpers ─────────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    Divide texto em chunks com overlap.
    Tenta quebrar em parágrafos ou sentenças para manter coerência.
    """
    if len(text) <= chunk_size:
        return [text.strip()]

    chunks = []
    # Primeiro tenta dividir por parágrafos
    paragraphs = text.split("\n\n")
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current_chunk) + len(para) + 2 <= chunk_size:
            current_chunk = f"{current_chunk}\n\n{para}" if current_chunk else para
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            # Se o parágrafo é maior que chunk_size, divide por sentenças
            if len(para) > chunk_size:
                sentences = para.replace(". ", ".\n").split("\n")
                sub_chunk = ""
                for sent in sentences:
                    sent = sent.strip()
                    if not sent:
                        continue
                    if len(sub_chunk) + len(sent) + 1 <= chunk_size:
                        sub_chunk = f"{sub_chunk} {sent}" if sub_chunk else sent
                    else:
                        if sub_chunk:
                            chunks.append(sub_chunk.strip())
                        sub_chunk = sent
                current_chunk = sub_chunk
            else:
                current_chunk = para

    if current_chunk:
        chunks.append(current_chunk.strip())

    # Adiciona overlap entre chunks
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_text = chunks[i - 1]
            overlap_text = prev_text[-overlap:] if len(prev_text) > overlap else prev_text
            overlapped.append(f"{overlap_text}... {chunks[i]}")
        chunks = overlapped

    return [c for c in chunks if c.strip()]
