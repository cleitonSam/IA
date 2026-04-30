"""
[PROMPT-SHARED] Builder unificado do system prompt da IA.

Usado por:
- Playground (src/api/routers/management.py)
- Bot real WhatsApp (main.py)

Garante que ambos rendam respostas IDENTICAS em qualidade. Se a personalidade
tiver "tom_voz: profissional + objetivos_venda: converter" o bot real vai
seguir o mesmo, igual ao playground.
"""
import json
from typing import Dict, Any, List, Optional


_PG_LABEL_MAP = {
    "objetivos_venda":       "OBJETIVOS DE VENDA",
    "metas_comerciais":      "METAS COMERCIAIS",
    "script_vendas":         "SCRIPT DE VENDAS",
    "scripts_objecoes":      "RESPOSTAS A OBJEÇÕES",
    "frases_fechamento":     "FRASES DE FECHAMENTO",
    "diferenciais":          "DIFERENCIAIS DA EMPRESA",
    "posicionamento":        "POSICIONAMENTO DE MERCADO",
    "publico_alvo":          "PÚBLICO-ALVO",
    "linguagem_proibida":    "LINGUAGEM PROIBIDA",
    "contexto_empresa":      "CONTEXTO DA EMPRESA",
    "contexto_extra":        "CONTEXTO EXTRA",
    "abordagem_proativa":    "ABORDAGEM PROATIVA",
}

# Campos com blocos dedicados — não incluir no loop dinâmico de DIRETRIZES
_PG_SKIP_IN_LOOP = {
    "restricoes", "palavras_proibidas", "despedida_personalizada",
    "regras_formatacao", "regras_seguranca", "exemplos", "idioma",
    "estilo_comunicacao", "saudacao_personalizada", "regras_atendimento",
}


def _resumo_unidade(u: dict) -> str:
    """Formata resumo de uma unidade pra injetar no prompt (sem tags WhatsApp)."""
    partes = [f"• {u.get('nome', '?')}"]
    cidade = u.get('cidade') or u.get('bairro') or ''
    estado = u.get('estado') or ''
    if cidade or estado:
        partes.append(f"  Localização: {cidade}{', ' + estado if estado else ''}")
    end = u.get('endereco_completo') or u.get('endereco') or ''
    if end:
        partes.append(f"  Endereço: {end}")
    tel = u.get('telefone') or u.get('whatsapp') or ''
    if tel:
        partes.append(f"  Telefone: {tel}")
    hor = u.get('horarios')
    if hor:
        hor_str = hor if isinstance(hor, str) else json.dumps(hor, ensure_ascii=False)
        partes.append(f"  Horários: {hor_str}")
    infra = u.get('infraestrutura')
    if infra:
        if isinstance(infra, dict):
            itens = [k for k, v in infra.items() if v]
            infra_str = ", ".join(itens) if itens else json.dumps(infra, ensure_ascii=False)
        else:
            infra_str = str(infra)
        if infra_str:
            partes.append(f"  Infraestrutura: {infra_str}")
    mods = u.get('modalidades')
    if mods:
        if isinstance(mods, list):
            mods_str = ", ".join(str(m) for m in mods if m)
        elif isinstance(mods, dict):
            mods_str = ", ".join(k for k, v in mods.items() if v)
        else:
            mods_str = str(mods)
        if mods_str:
            partes.append(f"  Modalidades: {mods_str}")
    # [DIARIA] inclui valor da diária se ativa
    if u.get("diaria_disponivel"):
        _v = u.get("diaria_valor")
        partes.append(f"  Diária: R$ {_v}" if _v else "  Diária: disponível")
        if u.get("diaria_observacao"):
            partes.append(f"    Observação: {u.get('diaria_observacao')}")
    return "\n".join(partes)


def build_base_prompt(
    p: Dict[str, Any],
    faq_text: str = "",
    unidades: Optional[List[Dict]] = None,
    planos: Optional[List[Dict]] = None,
    *,
    incluir_contexto_temporal: bool = True,
    incluir_agendamento: bool = True,
) -> str:
    """
    Constrói o system prompt completo a partir dos campos da personalidade salva.
    UNICA fonte de verdade — usado pelo playground E pelo bot real (WhatsApp).

    Args:
        p: dict da personalidade (de personalidade_ia)
        faq_text: texto pré-formatado do FAQ
        unidades: lista de unidades da empresa
        planos: lista de planos
        incluir_contexto_temporal: True = inclui [CONTEXTO TEMPORAL].
            Default True. main.py pode passar False se já vai injetar
            sua própria versão com timezone customizado.
        incluir_agendamento: True = inclui bloco [AGENDAMENTO].
            Default True.

    Returns:
        String do system prompt pronta pra mandar pra LLM.
    """
    nome   = p.get("nome_ia") or "Assistente"
    idioma = p.get("idioma") or "Português do Brasil"
    blocos: List[str] = []

    # [FIX-K] CONTEXTO TEMPORAL — LLM e pessimo em calendar.
    if incluir_contexto_temporal:
        try:
            from datetime import datetime as _dt_pg, timedelta as _td_pg
            from zoneinfo import ZoneInfo as _ZI_pg
            _DIAS_PT = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
                        "sexta-feira", "sábado", "domingo"]
            _MESES_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
                         "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
            _agora = _dt_pg.now(_ZI_pg("America/Sao_Paulo"))
            _prox = []
            for _i in range(7):
                _d = _agora + _td_pg(days=_i)
                _lb = "HOJE" if _i == 0 else ("AMANHA" if _i == 1 else f"+{_i}d")
                _prox.append(
                    f"  {_lb:6s} = {_DIAS_PT[_d.weekday()]}, {_d.day:02d}/{_d.month:02d}/{_d.year}"
                )
            blocos.append(
                "[CONTEXTO TEMPORAL — DADOS REAIS DO SERVIDOR]\n"
                f"- Agora: {_DIAS_PT[_agora.weekday()]}, {_agora.day} de {_MESES_PT[_agora.month-1]} de {_agora.year}, "
                f"{_agora.hour:02d}h{_agora.minute:02d} (horário de São Paulo).\n"
                "- Próximos 7 dias (use SEMPRE estes valores, NUNCA calcule sozinho):\n"
                + "\n".join(_prox) + "\n"
                "- Quando o cliente disser 'amanhã', 'segunda', 'sexta que vem' etc, "
                "use a data REAL desta tabela. NUNCA invente dia da semana — você sempre erra. "
                "Quando mostrar uma data ao cliente, use o formato 'sexta-feira, 1 de maio às 09h00'."
            )
        except Exception:
            pass

    # 1. Regras gerais
    blocos.append(
        f"[REGRAS GERAIS]\n"
        f"- Idioma obrigatório: {idioma}.\n"
        f"- NUNCA use inglês ou outros idiomas a menos que o cliente use.\n"
        f"- NUNCA mostre tags internas, avisos de sistema ou colunas técnicas.\n"
        f"- NUNCA se apresente como IA ou robô.\n"
        f"- DATA/HORA: use SEMPRE o bloco [CONTEXTO TEMPORAL] acima. NUNCA chute weekday."
    )

    # 2. Identidade
    blocos.append(f"[IDENTIDADE]\nVocê é {nome}, assistente virtual desta empresa.")

    # 3. Personalidade
    if p.get("personalidade"):
        blocos.append(f"[PERSONALIDADE]\n{p['personalidade']}")

    # 4. Tom de voz
    if p.get("tom_voz"):
        blocos.append(f"[TOM DE VOZ]\n{p['tom_voz']}")

    # 5. Estilo de comunicação
    estilo = p.get("estilo_comunicacao") or ""
    if estilo.strip():
        blocos.append(f"[ESTILO DE COMUNICAÇÃO]\n{estilo}")

    # 6. Saudação padrão
    saudacao = p.get("saudacao_personalizada") or ""
    if saudacao.strip():
        blocos.append(f"[SAUDAÇÃO PADRÃO]\n{saudacao}")

    # 7. Instruções base
    if p.get("instrucoes_base"):
        blocos.append(f"[INSTRUÇÕES BASE]\n{p['instrucoes_base']}")

    # 8. Diretrizes de negócio (campos dinâmicos)
    extras = ""
    for campo, titulo in _PG_LABEL_MAP.items():
        if campo in _PG_SKIP_IN_LOOP:
            continue
        valor = p.get(campo)
        if valor and str(valor).strip():
            extras += f"\n\n[{titulo}]\n{valor}"
    if extras:
        blocos.append(f"[DIRETRIZES DE NEGÓCIO]{extras}")

    # 9. Regras de atendimento
    regras_atend = p.get("regras_atendimento") or ""
    if regras_atend.strip():
        blocos.append(f"[REGRAS DE ATENDIMENTO]\n{regras_atend}")

    # [AGEND-02] Bloco de agendamento
    if incluir_agendamento:
        try:
            from src.services.agendamento_tools import construir_bloco_prompt_agendamento
            _bloco_agend = construir_bloco_prompt_agendamento(p)
            if _bloco_agend:
                blocos.append(_bloco_agend)
        except Exception:
            pass

    # 9.5 Fluxo de Vendedor
    blocos.append("""[FLUXO DE VENDEDOR — OBRIGATÓRIO]
Você é um VENDEDOR, não um robô de FAQ. Siga este fluxo SEMPRE:
1. Responda a pergunta do cliente de forma direta e curta.
2. Depois da resposta, faça UMA pergunta de descoberta que avance a conversa.

Padrão de resposta (use SEMPRE os DADOS REAIS configurados — nunca invente valores):
• "Tem diária?" → consulte o campo diaria_disponivel da unidade.
   Se sim: informe o valor REAL da diária (campo diaria_valor) e pergunte se quer só treinar hoje ou começar.
   Se não: explique que essa unidade não trabalha com diária e pergunte o objetivo do cliente.
• "Qual o horário?" → use os horários REAIS da unidade selecionada.
• "Quanto custa?" → use os planos REAIS configurados.
• "Quero começar" → pergunte qual unidade fica mais perto.

REGRAS:
- Resposta + pergunta de descoberta na MESMA mensagem.
- A pergunta deve descobrir algo sobre o cliente (objetivo, frequência, localização, urgência).
- NUNCA invente valores, horários, serviços ou ofertas — use APENAS os dados configurados.
- Se o cliente já respondeu uma descoberta, avance pro próximo passo (mostrar plano, agendar visita).
- NUNCA peça dados pessoais para cadastro (CPF, endereço completo). Você é um vendedor, não um formulário. Se o cliente quiser se matricular, direcione à unidade ou recepção.
- Use emojis SOMENTE se a configuração [CONTROLES DE RESPOSTA] permitir. Caso contrário, texto puro.""")

    # 10. Unidades da rede
    if unidades:
        nomes_unidades = ", ".join(u.get("nome", "?") for u in unidades)
        resumos = "\n\n".join(_resumo_unidade(u) for u in unidades)
        nome_empresa = unidades[0].get("nome_empresa") or "Nossa Empresa"
        qtd = len(unidades)
        contexto_rede = (
            f"A rede {nome_empresa} possui {qtd} unidades ativas."
            if qtd > 1 else
            f"A rede {nome_empresa} está operando com 1 unidade ativa."
        )
        blocos.append(
            f"[UNIDADES DA REDE]\n"
            f"{contexto_rede}\n"
            f"Unidades: {nomes_unidades}\n\n"
            f"{resumos}"
        )

    # 11. Planos e preços
    if planos:
        try:
            from src.services.db_queries import formatar_planos_para_prompt
            planos_texto = formatar_planos_para_prompt(planos)
            blocos.append(
                f"[PLANOS E PREÇOS]\n"
                f"Planos disponíveis (com links de matrícula):\n"
                f"{planos_texto}"
            )
        except Exception:
            pass

    # 12. FAQ
    if faq_text and faq_text.strip():
        blocos.append(f"[FAQ — RESPOSTAS PRONTAS]\n{faq_text}")

    # 13. Exemplos
    if p.get("exemplos"):
        blocos.append(f"[EXEMPLOS DE INTERAÇÕES]\n{p['exemplos']}")

    # 14. Regras de sistema
    regras_seg = p.get("regras_seguranca") or ""
    bloco_sistema = (
        "[REGRAS DE SISTEMA]\n"
        "- Responda diretamente se tiver os dados disponíveis.\n"
        "- Se o cliente enviar apenas saudação social, responda somente saudação e pergunte como ajudar.\n"
        "- Seja honesto: se não souber algo, diga que vai verificar."
    )
    if regras_seg.strip():
        bloco_sistema += f"\n{regras_seg}"
    blocos.append(bloco_sistema)

    # 15. Anti-alucinação
    restricoes     = p.get("restricoes") or ""
    palavras_proib = p.get("palavras_proibidas") or ""
    bloco_anti = (
        "[REGRAS CRÍTICAS — ANTI-ALUCINAÇÃO]\n"
        "- Use EXCLUSIVAMENTE os dados fornecidos neste prompt.\n"
        "- Se não souber, diga que não tem a informação.\n"
        "- Nunca invente endereços, telefones, horários ou valores."
    )
    if restricoes.strip():
        bloco_anti += f"\n- RESTRIÇÕES: {restricoes}"
    if palavras_proib.strip():
        bloco_anti += f"\n- NUNCA USE ESTAS PALAVRAS/TERMOS: {palavras_proib}"
    blocos.append(bloco_anti)

    # 16. Formatação WhatsApp
    usar_emoji = p.get("usar_emoji", True)
    emoji_tipo = p.get("emoji_tipo") or "✨"
    emoji_cor  = p.get("emoji_cor") or ""
    r_format   = p.get("regras_formatacao") or ""
    bloco_fmt = (
        "[FORMATAÇÃO WHATSAPP]\n"
        "- Use *bold* para destaque. Listas com •.\n"
        "- Separe blocos com linha em branco.\n"
        "- NUNCA use markdown (**, ##, ```).\n"
        "- Tamanho ideal: 2-4 parágrafos curtos.\n"
        "- TERMINAR sempre com frases completas."
    )
    if usar_emoji and emoji_tipo:
        bloco_fmt += f"\n- EMOJI PRINCIPAL DA IA: {emoji_tipo}. Use-o com frequência."
    if emoji_cor:
        bloco_fmt += f"\n- PALETA DE CORES/VIBE: {emoji_cor}. Priorize emojis que combinem com esta cor."
    if not usar_emoji:
        bloco_fmt += "\n- NÃO use emojis nas respostas."
    if r_format.strip():
        bloco_fmt += f"\n{r_format}"
    blocos.append(bloco_fmt)

    # 17. Despedida
    despedida = p.get("despedida_personalizada") or ""
    if despedida.strip():
        blocos.append(f"[DESPEDIDA PADRÃO]\n{despedida}")

    # 18. Verbosidade
    _VERBOSIDADE_MAP = {
        "concisa":   (
            "[TAMANHO DE RESPOSTA — OBRIGATÓRIO]\n"
            "- Responda em no máximo 2–3 frases por mensagem.\n"
            "- Seja direto e objetivo. Elimine qualquer texto desnecessário.\n"
            "- NUNCA use listas, enumerações ou parágrafos longos.\n"
            "- Uma ideia por mensagem. Se precisar de mais, faça em mensagens separadas."
        ),
        "normal":    (
            "[TAMANHO DE RESPOSTA]\n"
            "- Respostas entre 3–5 frases. Balance completude e concisão.\n"
            "- Use listas apenas quando a comparação de opções for essencial."
        ),
        "detalhada": (
            "[TAMANHO DE RESPOSTA]\n"
            "- Pode detalhar quando o cliente demonstrar interesse ou pedir mais informações.\n"
            "- Use listas e estrutura quando ajudar a clareza da resposta."
        ),
    }
    verbosidade = p.get("comprimento_resposta") or "normal"
    if verbosidade in _VERBOSIDADE_MAP:
        blocos.append(_VERBOSIDADE_MAP[verbosidade])

    # 19. Cenários SE/ENTAO
    cenarios = p.get("cenarios")
    if cenarios:
        try:
            if isinstance(cenarios, str):
                cenarios = json.loads(cenarios)
            if isinstance(cenarios, list) and cenarios:
                _bloco_cen = "[CENÁRIOS DE AÇÃO — SIGA SEMPRE]\nQuando uma situação abaixo ocorrer, EXECUTE A AÇÃO correspondente:\n\n"
                _ativos = [c for c in cenarios if c.get("ativo") is not False]
                _ativos.sort(key=lambda x: int(x.get("ordem") or 99))
                for _i, _c in enumerate(_ativos[:50], 1):
                    _cen = (_c.get("cenario") or "").strip()
                    _ac = (_c.get("acao") or "").strip()
                    if not _cen or not _ac:
                        continue
                    _bloco_cen += f"📌 CENÁRIO {_i}: {_cen}\n   → AÇÃO:\n"
                    for _ln in _ac.split("\n"):
                        _ln = _ln.strip()
                        if _ln:
                            _bloco_cen += f"      {_ln}\n"
                    _bloco_cen += "\n"
                _bloco_cen += (
                    "[REGRAS DOS CENÁRIOS]\n"
                    "- Esses cenários são MAIS IMPORTANTES que regras gerais — siga ao pé da letra\n"
                    "- Se um cenário pedir pra agendar/transferir/encaminhar, EXECUTE\n"
                    "- Se um cenário não se aplica à conversa atual, IGNORE\n"
                    "- NUNCA invente cenários ou ações fora desta lista\n"
                )
                blocos.append(_bloco_cen)
        except Exception:
            pass

    return "\n\n".join(blocos)
