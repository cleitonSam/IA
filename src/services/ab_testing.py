"""
A/B Testing Service — Testa variantes de prompts para otimizar conversão.

Fluxo:
1. Admin cria teste com variante_a e variante_b
2. Cada conversa é atribuída deterministicamente: conversation_id % 100 < percentual_b → B, senão A
3. A variante é aplicada ao prompt do LLM
4. Resultado (lead qualificado, intenção, score) é registrado
5. Dashboard mostra comparação entre variantes
"""
from typing import Optional, Dict, List
from src.core.config import logger
from src.services.db_queries import _database


async def obter_teste_ativo(empresa_id: int) -> Optional[Dict]:
    """
    Retorna o teste A/B ativo para a empresa (apenas 1 ativo por vez).
    Usa cache em memória do processo (sem Redis — dados mudam raramente).
    """
    try:
        row = await _database.db_pool.fetchrow("""
            SELECT id, nome, campo_teste, variante_a, variante_b, percentual_b
            FROM ab_testes
            WHERE empresa_id = $1 AND ativo = true
            ORDER BY created_at DESC
            LIMIT 1
        """, empresa_id)

        if not row:
            return None

        return dict(row)
    except Exception as e:
        logger.error(f"Erro ao buscar teste A/B ativo: {e}")
        return None


def atribuir_variante(conversation_id: int, percentual_b: float = 50.0) -> str:
    """
    Atribui variante de forma determinística baseado no conversation_id.
    Mesma conversa sempre recebe mesma variante.
    """
    if (conversation_id % 100) < percentual_b:
        return "B"
    return "A"


async def aplicar_teste_ab(
    empresa_id: int,
    conversation_id: int,
    prompt_blocos: list
) -> tuple[list, Optional[Dict]]:
    """
    Aplica o teste A/B aos blocos de prompt.
    Retorna (blocos_modificados, info_teste) ou (blocos_originais, None) se sem teste.

    campo_teste pode ser:
    - 'prompt_sistema': substitui/adiciona texto ao sistema prompt
    - 'tom_de_voz': altera o tom de voz
    - 'instrucoes_extra': adiciona instruções extras
    """
    teste = await obter_teste_ativo(empresa_id)
    if not teste:
        return prompt_blocos, None

    variante = atribuir_variante(conversation_id, teste["percentual_b"])
    texto_variante = teste["variante_a"] if variante == "A" else teste["variante_b"]
    campo = teste["campo_teste"]

    info = {
        "teste_id": teste["id"],
        "variante": variante,
        "campo": campo,
        "nome": teste["nome"],
    }

    # Aplica a variante ao prompt
    if campo == "prompt_sistema":
        # Adiciona como um bloco extra antes das regras de sistema
        prompt_blocos.append(f"[INSTRUÇÃO DE TESTE]\n{texto_variante}")

    elif campo == "tom_de_voz":
        # Substitui ou adiciona tom de voz
        for i, bloco in enumerate(prompt_blocos):
            if "[TOM DE VOZ]" in bloco:
                prompt_blocos[i] = f"[TOM DE VOZ]\n{texto_variante}"
                break
        else:
            prompt_blocos.append(f"[TOM DE VOZ]\n{texto_variante}")

    elif campo == "instrucoes_extra":
        prompt_blocos.append(f"[DIRETRIZES ADICIONAIS]\n{texto_variante}")

    return prompt_blocos, info


async def registrar_resultado_ab(
    teste_id: int,
    conversa_id: int,
    variante: str,
    lead_qualificado: bool = False,
    intencao_compra: bool = False,
    score_lead: float = 0,
    msgs_total: int = 0
):
    """Registra o resultado de uma conversa no teste A/B."""
    try:
        # Evita duplicata
        exists = await _database.db_pool.fetchval("""
            SELECT id FROM ab_resultados
            WHERE teste_id = $1 AND conversa_id = $2
        """, teste_id, conversa_id)

        if exists:
            # Atualiza se já existe
            await _database.db_pool.execute("""
                UPDATE ab_resultados SET
                    lead_qualificado = $1, intencao_compra = $2,
                    score_lead = $3, msgs_total = $4
                WHERE teste_id = $5 AND conversa_id = $6
            """, lead_qualificado, intencao_compra, score_lead, msgs_total,
                teste_id, conversa_id)
        else:
            await _database.db_pool.execute("""
                INSERT INTO ab_resultados
                    (teste_id, conversa_id, variante, lead_qualificado, intencao_compra, score_lead, msgs_total)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """, teste_id, conversa_id, variante, lead_qualificado, intencao_compra, score_lead, msgs_total)
    except Exception as e:
        logger.error(f"Erro ao registrar resultado A/B: {e}")


async def obter_resultados_ab(teste_id: int) -> Dict:
    """
    Retorna resultados agregados do teste A/B para comparação.
    """
    try:
        rows = await _database.db_pool.fetch("""
            SELECT
                variante,
                COUNT(*) AS total_conversas,
                COUNT(CASE WHEN lead_qualificado THEN 1 END) AS leads,
                COUNT(CASE WHEN intencao_compra THEN 1 END) AS intencoes,
                COALESCE(AVG(score_lead), 0) AS score_medio,
                COALESCE(AVG(msgs_total), 0) AS msgs_media
            FROM ab_resultados
            WHERE teste_id = $1
            GROUP BY variante
            ORDER BY variante
        """, teste_id)

        resultado = {"teste_id": teste_id, "variantes": {}}
        for r in rows:
            d = dict(r)
            total = d["total_conversas"] or 1
            d["taxa_conversao"] = round((d["leads"] / total) * 100, 1)
            d["taxa_intencao"] = round((d["intencoes"] / total) * 100, 1)
            d["score_medio"] = round(float(d["score_medio"]), 2)
            d["msgs_media"] = round(float(d["msgs_media"]), 1)
            resultado["variantes"][d["variante"]] = d

        # Calcula winner
        va = resultado["variantes"].get("A", {})
        vb = resultado["variantes"].get("B", {})
        if va and vb:
            if va.get("taxa_conversao", 0) > vb.get("taxa_conversao", 0):
                resultado["winner"] = "A"
                resultado["lift"] = round(va["taxa_conversao"] - vb["taxa_conversao"], 1)
            elif vb.get("taxa_conversao", 0) > va.get("taxa_conversao", 0):
                resultado["winner"] = "B"
                resultado["lift"] = round(vb["taxa_conversao"] - va["taxa_conversao"], 1)
            else:
                resultado["winner"] = "empate"
                resultado["lift"] = 0
        else:
            resultado["winner"] = "dados_insuficientes"
            resultado["lift"] = 0

        return resultado
    except Exception as e:
        logger.error(f"Erro ao buscar resultados A/B: {e}")
        return {"teste_id": teste_id, "variantes": {}, "winner": "erro"}


async def listar_testes(empresa_id: int) -> List[Dict]:
    """Lista todos os testes A/B da empresa."""
    try:
        rows = await _database.db_pool.fetch("""
            SELECT t.id, t.nome, t.descricao, t.campo_teste, t.percentual_b,
                   t.ativo, t.created_at, t.finalizado_em,
                   COUNT(r.id) AS total_resultados
            FROM ab_testes t
            LEFT JOIN ab_resultados r ON r.teste_id = t.id
            WHERE t.empresa_id = $1
            GROUP BY t.id
            ORDER BY t.created_at DESC
        """, empresa_id)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Erro ao listar testes A/B: {e}")
        return []


async def criar_teste(
    empresa_id: int,
    nome: str,
    campo_teste: str,
    variante_a: str,
    variante_b: str,
    percentual_b: float = 50.0,
    descricao: str = None
) -> Optional[int]:
    """
    Cria um novo teste A/B. Desativa qualquer teste ativo anterior.
    """
    try:
        # Desativa testes ativos anteriores
        await _database.db_pool.execute("""
            UPDATE ab_testes SET ativo = false, finalizado_em = NOW()
            WHERE empresa_id = $1 AND ativo = true
        """, empresa_id)

        row = await _database.db_pool.fetchrow("""
            INSERT INTO ab_testes (empresa_id, nome, descricao, campo_teste, variante_a, variante_b, percentual_b)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """, empresa_id, nome, descricao, campo_teste, variante_a, variante_b, percentual_b)

        logger.info(f"🧪 A/B Test criado: '{nome}' (id={row['id']}) para empresa {empresa_id}")
        return row["id"]
    except Exception as e:
        logger.error(f"Erro ao criar teste A/B: {e}")
        return None


async def finalizar_teste(empresa_id: int, teste_id: int) -> bool:
    """Finaliza um teste A/B."""
    try:
        await _database.db_pool.execute("""
            UPDATE ab_testes SET ativo = false, finalizado_em = NOW()
            WHERE id = $1 AND empresa_id = $2
        """, teste_id, empresa_id)
        return True
    except Exception as e:
        logger.error(f"Erro ao finalizar teste A/B: {e}")
        return False
