"""
[MKT-03] Memoria de longo prazo por cliente (estilo Mem0/Zep).

A tabela `memoria_cliente` ja existe no banco (migration l5m6n7o8p9q0) com colunas:
  id, empresa_id, contato_fone, tipo, conteudo, relevancia, created_at, updated_at

Este modulo adiciona:
  1. Extracao automatica de fatos — apos N mensagens do cliente, chama LLM para extrair
     fatos duraveis (preferencia, objecao, horario preferido, objetivo, restricao)
  2. Tipos estruturados — preferencia / objecao / horario / objetivo / restricao / historico
  3. Decay de relevancia — fatos antigos perdem peso; novos fatos sobrescrevem quando conflita
  4. Sumarizacao — se houver muitos fatos do mesmo tipo, consolida em um resumo unico
  5. Recall — monta um prompt compacto com top N fatos para injetar no LLM

Uso:
    from src.services.client_memory import (
        extract_and_store_facts, recall_for_prompt, consolidate_if_needed
    )

    # Apos o cliente mandar N mensagens, extrair fatos e salvar
    await extract_and_store_facts(
        empresa_id=1, contato_fone="5511999...", recent_messages=[...]
    )

    # Ao montar prompt do LLM
    memoria_txt = await recall_for_prompt(empresa_id=1, contato_fone="5511999...")
    # "[MEMORIA DO CLIENTE]\n- prefere treinar de manha\n- objetivo: emagrecer\n..."

    # Periodicamente (worker)
    await consolidate_if_needed(empresa_id=1, contato_fone="5511999...")
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from src.core.config import logger
import src.core.database as _database
from src.services.llm_service import cliente_ia


TIPOS_VALIDOS = {"preferencia", "objecao", "horario", "objetivo", "restricao", "historico"}


PROMPT_EXTRAIR_FATOS = """Voce e um extrator de fatos de conversas de vendas de uma academia.
Dada uma lista de mensagens do CLIENTE, extraia fatos DURAVEIS (coisas que continuam verdadeiras no futuro).

Retorne JSON com a estrutura:
{
  "fatos": [
    {"tipo": "preferencia|objecao|horario|objetivo|restricao|historico", "conteudo": "descricao curta", "confianca": 0.0-1.0}
  ]
}

Exemplos de fatos bons:
- tipo=preferencia, conteudo="gosta de treinar de manha"
- tipo=objetivo, conteudo="quer emagrecer 15kg em 6 meses"
- tipo=objecao, conteudo="acha o preco alto, citou R$ 150"
- tipo=restricao, conteudo="lesao no joelho direito"
- tipo=horario, conteudo="disponivel apos 18h nos dias uteis"
- tipo=historico, conteudo="ja foi aluno por 2 anos em 2023"

NAO extraia:
- Cumprimentos ("oi", "bom dia")
- Perguntas vagas ("tem como?")
- Estados momentaneos ("estou com pressa hoje")

So retorne JSON valido. Sem explicacao fora do JSON.
"""


async def extract_and_store_facts(
    empresa_id: int,
    contato_fone: str,
    recent_messages: List[str],
    min_messages: int = 3,
) -> int:
    """Extrai fatos novos a partir das mensagens recentes do cliente e salva.
    Retorna numero de fatos adicionados."""
    if len(recent_messages) < min_messages:
        return 0
    if not cliente_ia or not _database.db_pool:
        return 0

    texto = "\n".join(f"- {m}" for m in recent_messages if m and len(m) > 2)
    if not texto.strip():
        return 0

    try:
        resp = await cliente_ia.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": PROMPT_EXTRAIR_FATOS},
                {"role": "user", "content": f"Mensagens do cliente:\n{texto}\n\nExtraia os fatos."},
            ],
            temperature=0.1,
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
    except Exception as e:
        logger.warning(f"[MKT-03] LLM extract falhou: {e}")
        return 0

    fatos = data.get("fatos", []) or []
    if not fatos:
        return 0

    count = 0
    for fato in fatos:
        tipo = (fato.get("tipo") or "").lower()
        conteudo = (fato.get("conteudo") or "").strip()
        confianca = float(fato.get("confianca") or 0.5)
        if tipo not in TIPOS_VALIDOS or not conteudo or confianca < 0.4:
            continue

        # Evita duplicata exata
        existe = await _database.db_pool.fetchval(
            """
            SELECT id FROM memoria_cliente
            WHERE empresa_id = $1 AND contato_fone = $2
              AND tipo = $3 AND lower(conteudo) = lower($4)
            LIMIT 1
            """,
            empresa_id, contato_fone, tipo, conteudo,
        )
        if existe:
            # Reforca relevancia de fato ja visto
            await _database.db_pool.execute(
                """
                UPDATE memoria_cliente
                SET relevancia = LEAST(relevancia + 0.2, 3.0),
                    updated_at = NOW()
                WHERE id = $1
                """,
                existe,
            )
            continue

        try:
            await _database.db_pool.execute(
                """
                INSERT INTO memoria_cliente
                    (empresa_id, contato_fone, tipo, conteudo, relevancia)
                VALUES ($1, $2, $3, $4, $5)
                """,
                empresa_id, contato_fone, tipo, conteudo, confianca,
            )
            count += 1
        except Exception as e:
            logger.warning(f"[MKT-03] insert fato falhou: {e}")

    if count:
        logger.info(f"[MKT-03] +{count} fatos fone={contato_fone} empresa={empresa_id}")
    return count


async def recall_for_prompt(
    empresa_id: int,
    contato_fone: str,
    max_fatos: int = 12,
) -> str:
    """Retorna bloco [MEMORIA DO CLIENTE] formatado para injecao no prompt LLM."""
    if not _database.db_pool:
        return ""

    try:
        rows = await _database.db_pool.fetch(
            """
            SELECT tipo, conteudo, relevancia, updated_at
            FROM memoria_cliente
            WHERE empresa_id = $1 AND contato_fone = $2
            ORDER BY relevancia DESC, updated_at DESC
            LIMIT $3
            """,
            empresa_id, contato_fone, max_fatos,
        )
        if not rows:
            return ""

        # Agrupa por tipo
        por_tipo: Dict[str, List[str]] = {}
        for r in rows:
            tipo = r["tipo"]
            por_tipo.setdefault(tipo, []).append(r["conteudo"])

        linhas = ["[MEMORIA DO CLIENTE — use para personalizar a resposta]"]
        ordem = ["objetivo", "preferencia", "horario", "restricao", "objecao", "historico"]
        for tipo in ordem:
            if tipo in por_tipo:
                linhas.append(f"\n{tipo.upper()}:")
                for c in por_tipo[tipo]:
                    linhas.append(f"  - {c}")
        return "\n".join(linhas)
    except Exception as e:
        logger.error(f"[MKT-03] recall falhou: {e}")
        return ""


async def apply_decay(empresa_id: int, days_old: int = 30, factor: float = 0.9) -> int:
    """Reduz relevancia de fatos nao atualizados ha mais de `days_old` dias.
    Remove fatos com relevancia < 0.2."""
    if not _database.db_pool:
        return 0
    try:
        await _database.db_pool.execute(
            """
            UPDATE memoria_cliente
            SET relevancia = relevancia * $1
            WHERE empresa_id = $2
              AND updated_at < NOW() - ($3 || ' days')::interval
            """,
            factor, empresa_id, str(days_old),
        )
        deleted = await _database.db_pool.execute(
            "DELETE FROM memoria_cliente WHERE empresa_id = $1 AND relevancia < 0.2",
            empresa_id,
        )
        logger.info(f"[MKT-03] decay empresa={empresa_id}: {deleted}")
        return 0
    except Exception as e:
        logger.error(f"[MKT-03] apply_decay falhou: {e}")
        return 0


async def consolidate_if_needed(
    empresa_id: int,
    contato_fone: str,
    max_per_tipo: int = 5,
) -> int:
    """Se um cliente tem mais de max_per_tipo fatos do mesmo tipo, consolida os N mais antigos em 1."""
    if not _database.db_pool or not cliente_ia:
        return 0

    try:
        tipos = await _database.db_pool.fetch(
            """
            SELECT tipo, COUNT(*) c
            FROM memoria_cliente
            WHERE empresa_id = $1 AND contato_fone = $2
            GROUP BY tipo
            HAVING COUNT(*) > $3
            """,
            empresa_id, contato_fone, max_per_tipo,
        )
        consolidated = 0

        for t in tipos:
            tipo = t["tipo"]
            # Pega os mais antigos e com menor relevancia
            rows = await _database.db_pool.fetch(
                """
                SELECT id, conteudo FROM memoria_cliente
                WHERE empresa_id = $1 AND contato_fone = $2 AND tipo = $3
                ORDER BY relevancia ASC, updated_at ASC
                LIMIT $4
                """,
                empresa_id, contato_fone, tipo, max(1, int(t["c"]) - max_per_tipo),
            )
            if len(rows) < 2:
                continue

            conteudos = [r["conteudo"] for r in rows]
            texto = "\n".join(f"- {c}" for c in conteudos)

            try:
                resp = await cliente_ia.chat.completions.create(
                    model="google/gemini-2.5-flash",
                    messages=[
                        {"role": "system", "content": "Consolide estes fatos em UMA frase curta e objetiva, preservando informacoes relevantes. So retorne a frase."},
                        {"role": "user", "content": texto},
                    ],
                    temperature=0.2,
                    max_tokens=100,
                )
                resumo = (resp.choices[0].message.content or "").strip()
                if not resumo:
                    continue

                ids = [r["id"] for r in rows]
                await _database.db_pool.execute(
                    "DELETE FROM memoria_cliente WHERE id = ANY($1::int[])",
                    ids,
                )
                await _database.db_pool.execute(
                    """
                    INSERT INTO memoria_cliente
                        (empresa_id, contato_fone, tipo, conteudo, relevancia)
                    VALUES ($1, $2, $3, $4, 1.5)
                    """,
                    empresa_id, contato_fone, tipo, resumo,
                )
                consolidated += 1
            except Exception as e:
                logger.warning(f"[MKT-03] consolidate LLM falhou: {e}")

        return consolidated
    except Exception as e:
        logger.error(f"[MKT-03] consolidate falhou: {e}")
        return 0
