"""
[MKT-09] Agentic RAG — retrieval iterativo com planning LLM.

Evolui o rag_service.py (retrieval linear — 1 query -> top-k chunks) para um
loop com multiplas etapas:

  1. PLAN  — LLM decompoe a pergunta em 1..3 sub-queries especificas
  2. RETRIEVE — para cada sub-query, busca top_k chunks
  3. EVALUATE — LLM decide se o contexto coletado responde a pergunta;
                se nao, propoe refinamentos (ate max_iterations)
  4. ANSWER — LLM sintetiza resposta citando as fontes

Beneficios esperados:
  - Reduz alucinacao em perguntas complexas (ex: "qual plano para perder 10kg em 3 meses
    considerando que tenho problema no joelho?")
  - Melhora cobertura em KB grande (mais de 200 entradas)
  - Audit trail — a trilha de queries + decisoes fica registrada

Custo extra: ~2-3x mais chamadas LLM por pergunta. Use quando a pergunta for
complexa ou o RAG linear nao encontra resposta boa.

Uso:
    from src.services.agentic_rag import answer_with_agentic_rag

    resp = await answer_with_agentic_rag(
        empresa_id=1,
        pergunta="quero um plano barato mas tenho lesao no joelho",
        max_iterations=3,
    )
    # resp = {"answer": "...", "fontes": [...], "iteracoes": [...]}
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from src.core.config import logger
from src.services.llm_service import cliente_ia
from src.services.rag_service import buscar_conhecimento


PLANNER_PROMPT = """Voce recebe uma pergunta de um aluno/lead e decompoe em sub-queries focadas
para buscar em uma base de conhecimento sobre a academia (planos, horarios, regras, etc).

Retorne JSON:
{
  "sub_queries": ["query 1 bem especifica", "query 2", "query 3 opcional"],
  "raciocinio": "por que dividi assim"
}

Se a pergunta for simples, retorne 1 sub_query igual a pergunta original.
Maximo 3 sub_queries.
"""


EVALUATOR_PROMPT = """Voce recebe: (a) a pergunta original, (b) as informacoes ja coletadas da base.
Decida se o contexto e suficiente para responder bem, ou se precisa refinar a busca.

Retorne JSON:
{
  "suficiente": true|false,
  "raciocinio": "por que sim ou nao",
  "nova_sub_query": "so se suficiente=false — query mais especifica para complementar"
}
"""


SYNTHESIS_PROMPT = """Voce e a assistente IA da academia. Responda a pergunta do aluno usando
APENAS as informacoes da BASE DE CONHECIMENTO abaixo. Se alguma informacao nao estiver la,
diga honestamente "nao tenho essa informacao aqui, posso te passar para um atendente".

Estilo: tom amigavel, breve, direto. Nunca invente precos, horarios ou regras.
No final, cite as fontes numeradas (ex: [1], [2]).
"""


async def _plan_sub_queries(pergunta: str) -> List[str]:
    if not cliente_ia:
        return [pergunta]
    try:
        resp = await cliente_ia.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": PLANNER_PROMPT},
                {"role": "user", "content": pergunta},
            ],
            temperature=0.1,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        subs = data.get("sub_queries") or [pergunta]
        return [s for s in subs if isinstance(s, str) and len(s) > 3][:3] or [pergunta]
    except Exception as e:
        logger.warning(f"[MKT-09] planner falhou: {e}")
        return [pergunta]


async def _evaluate(pergunta: str, contexto_acumulado: str) -> Dict:
    if not cliente_ia or not contexto_acumulado:
        return {"suficiente": True, "raciocinio": "sem_llm_ou_sem_contexto"}
    try:
        resp = await cliente_ia.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": EVALUATOR_PROMPT},
                {"role": "user", "content": f"PERGUNTA: {pergunta}\n\nCONTEXTO COLETADO:\n{contexto_acumulado[:3000]}"},
            ],
            temperature=0.1,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content or "{}") or {}
    except Exception as e:
        logger.warning(f"[MKT-09] evaluator falhou: {e}")
        return {"suficiente": True, "raciocinio": "erro_llm"}


async def _synthesize(pergunta: str, chunks: List[Dict]) -> str:
    if not cliente_ia:
        # Fallback — devolve texto dos chunks
        return "\n\n".join(c.get("conteudo", "") for c in chunks[:3])

    fontes_txt = "\n\n".join(
        f"[{i+1}] {c.get('titulo','')} ({c.get('categoria','geral')})\n{c.get('conteudo','')[:500]}"
        for i, c in enumerate(chunks)
    )

    try:
        resp = await cliente_ia.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": SYNTHESIS_PROMPT},
                {"role": "user", "content": f"BASE DE CONHECIMENTO:\n{fontes_txt}\n\nPERGUNTA: {pergunta}"},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning(f"[MKT-09] synthesize falhou: {e}")
        return ""


async def answer_with_agentic_rag(
    empresa_id: int,
    pergunta: str,
    max_iterations: int = 2,
    top_k_por_query: int = 3,
    threshold: float = 0.68,
) -> Dict:
    """Responde uma pergunta usando RAG agentic com planning + eval + synth.
    Retorna { answer, fontes, iteracoes } onde iteracoes eh o audit trail."""
    iteracoes: List[Dict] = []
    all_chunks: List[Dict] = []
    seen_ids = set()

    # 1. PLAN
    sub_queries = await _plan_sub_queries(pergunta)
    iteracoes.append({"step": "plan", "sub_queries": sub_queries})

    # 2. RETRIEVE inicial
    for sq in sub_queries:
        chunks = await buscar_conhecimento(
            sq, empresa_id=empresa_id,
            top_k=top_k_por_query, threshold=threshold,
        )
        novos = [c for c in chunks if c.get("id") not in seen_ids]
        for c in novos:
            seen_ids.add(c.get("id"))
            all_chunks.append(c)
        iteracoes.append({"step": "retrieve", "query": sq, "n_chunks": len(novos)})

    # 3. EVALUATE + REFINE (loop)
    for it in range(max_iterations):
        contexto = "\n\n".join(c.get("conteudo", "") for c in all_chunks[:6])
        eval_result = await _evaluate(pergunta, contexto)
        iteracoes.append({"step": "evaluate", "result": eval_result})

        if eval_result.get("suficiente"):
            break
        nova_sq = (eval_result.get("nova_sub_query") or "").strip()
        if not nova_sq or nova_sq in sub_queries:
            break
        sub_queries.append(nova_sq)

        refined = await buscar_conhecimento(
            nova_sq, empresa_id=empresa_id,
            top_k=top_k_por_query, threshold=threshold,
        )
        novos = [c for c in refined if c.get("id") not in seen_ids]
        for c in novos:
            seen_ids.add(c.get("id"))
            all_chunks.append(c)
        iteracoes.append({"step": "retrieve", "query": nova_sq, "n_chunks": len(novos)})

        if len(all_chunks) >= 10:
            break

    # 4. ANSWER
    if not all_chunks:
        return {
            "answer": "Nao encontrei essa informacao na nossa base. Posso te conectar com um atendente agora.",
            "fontes": [],
            "iteracoes": iteracoes,
        }

    # Ordena por score desc e pega top 6 para nao estourar contexto
    all_chunks.sort(key=lambda c: c.get("score", 0), reverse=True)
    top = all_chunks[:6]

    answer = await _synthesize(pergunta, top)
    return {
        "answer": answer or "Desculpe, nao consegui formular uma resposta boa. Vou chamar um atendente.",
        "fontes": [{"id": c.get("id"), "titulo": c.get("titulo"), "score": c.get("score")} for c in top],
        "iteracoes": iteracoes,
    }
