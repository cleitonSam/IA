"""
prompt_builder.py — System prompt construction.

Handles:
- Modular prompt block assembly (identity, personality, rules, data)
- Plan context filtering
- Unit summary generation for multi-unit networks
- RAG and client memory integration
- A/B testing prompt modification
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any

from src.core.config import logger
from src.utils.text_helpers import normalizar
from src.utils.intent_helpers import eh_saudacao
from src.utils.time_helpers import esta_aberta_agora, formatar_horarios_funcionamento
from src.services.db_queries import (
    formatar_planos_para_prompt, listar_unidades_ativas,
    carregar_faq_unidade, bd_obter_historico_local,
)
from src.services.ia_processor import (
    normalizar_lista_campo, extrair_endereco_unidade, extrair_telefone_unidade,
    truncar_contexto, detectar_tipo_cliente,
    carregar_memoria_cliente, formatar_memoria_para_prompt,
)
from src.services.rag_service import buscar_conhecimento, formatar_rag_para_prompt
from src.services.ab_testing import aplicar_teste_ab


def filtrar_planos_por_contexto(texto_cliente: str, planos: List[Dict]) -> List[Dict]:
    """Prioriza planos mais aderentes ao que o cliente pediu (ex.: aulas coletivas)."""
    if not planos:
        return []

    txt = normalizar(texto_cliente or "")
    if not txt:
        return planos

    intencoes = {
        "aulas_coletivas": ["aulas coletivas", "coletiva", "fit dance", "zumba", "pilates", "yoga", "muay thai", "aula"],
        "musculacao": ["musculacao", "musculação", "peso", "hipertrofia", "academia"],
        "premium": ["premium", "vip", "completo", "top", "melhor plano"],
        "economico": ["barato", "mais em conta", "economico", "econômico", "preco", "preço"],
    }

    pesos = {k: 0 for k in intencoes}
    for k, chaves in intencoes.items():
        for c in chaves:
            if normalizar(c) in txt:
                pesos[k] += 1

    if sum(pesos.values()) == 0:
        return planos

    ranqueados = []
    for p in planos:
        corpus = " ".join([
            str(p.get("nome") or ""),
            str(p.get("descricao") or ""),
            str(p.get("pitch") or ""),
            str(p.get("slogan") or ""),
            json.dumps(p.get("diferenciais") or "", ensure_ascii=False),
        ])
        corp_norm = normalizar(corpus)
        score = 0
        for k, chaves in intencoes.items():
            if pesos[k] <= 0:
                continue
            score += sum(2 for c in chaves if normalizar(c) in corp_norm)
        ranqueados.append((score, p))

    ranqueados.sort(key=lambda x: x[0], reverse=True)
    melhores = [p for sc, p in ranqueados if sc > 0]
    if not melhores:
        return planos

    return melhores[:3]


def resumo_unidade(u: dict) -> str:
    """Gera resumo compacto de uma unidade para o prompt do LLM."""
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
    foto = u.get('foto_grade')
    if foto:
        partes.append(f"  Grade/Horários: imagem disponível — use <SEND_IMAGE:{u.get('slug')}> para enviar")
    tour = u.get('link_tour_virtual')
    if tour:
        partes.append(f"  Tour Virtual: vídeo disponível — use <SEND_VIDEO:{u.get('slug')}> para enviar")
    return "\n".join(partes)


def _montar_dados_unidade(
    unidade: dict,
    end_banco: str,
    tel_banco: str,
    planos_ativos: list,
    hor_banco,
) -> str:
    """Monta o bloco de dados completos da unidade para o prompt."""
    if hor_banco:
        if isinstance(hor_banco, dict):
            horarios_str = "\n".join([f"- {dia}: {h}" for dia, h in hor_banco.items()])
        else:
            horarios_str = str(hor_banco)
    else:
        horarios_str = "não informado"

    _aberta_agora, _horario_hoje = esta_aberta_agora(hor_banco)
    if _aberta_agora is True:
        _status_agora = f"✅ ABERTA AGORA (hoje: {_horario_hoje})"
    elif _aberta_agora is False:
        _status_agora = f"❌ FECHADA AGORA (hoje: {_horario_hoje})"
    else:
        _status_agora = "não informado"

    planos_detalhados = formatar_planos_para_prompt(planos_ativos) if planos_ativos else "não informado"
    modalidades_prompt = ", ".join(normalizar_lista_campo(unidade.get("modalidades"))) or "não informado"
    pagamentos_prompt = ", ".join(normalizar_lista_campo(unidade.get("formas_pagamento"))) or "não informado"

    convenios_raw = unidade.get("convenios")
    if isinstance(convenios_raw, dict):
        _parts = []
        _gw = convenios_raw.get("gympass_wellhub", "")
        if _gw and _gw != "Não aceita":
            _parts.append(f"Gympass/Wellhub {_gw}")
        _tp = convenios_raw.get("totalpass", "")
        if _tp and _tp != "Não aceita":
            _parts.append(f"Totalpass {_tp}")
        _outros = convenios_raw.get("outros", "")
        if _outros:
            _parts.append(_outros)
        convenios_prompt = ", ".join(_parts) or "não aceita convênios"
    else:
        convenios_prompt = ", ".join(normalizar_lista_campo(convenios_raw)) or "não informado"

    return f"""
DADOS COMPLETOS DA UNIDADE
Nome: {unidade.get('nome') or 'não informado'}
Empresa: {unidade.get('nome_empresa') or 'não informado'}
Endereço: {end_banco or 'não informado'}
Cidade/Estado: {unidade.get('cidade') or 'não informado'} / {unidade.get('estado') or 'não informado'}
Telefone: {tel_banco or 'não informado'}
Status atual: {_status_agora}
Horários:
{horarios_str}
Planos (com links de matricula):
{planos_detalhados}
Site: {unidade.get('site') or 'não informado'}
Instagram: {unidade.get('instagram') or 'não informado'}
Modalidades: {modalidades_prompt}
Infraestrutura: {json.dumps(unidade.get('infraestrutura', {}), ensure_ascii=False) if unidade.get('infraestrutura') else 'não informado'}
Pagamentos: {pagamentos_prompt}
Convênios: {convenios_prompt}
"""


def _montar_extras_personalidade(pers: dict) -> str:
    """Monta bloco dinâmico com campos extras da personalidade."""
    _CAMPOS_FIXOS = {
        'id', 'empresa_id', 'ativo', 'nome_ia', 'personalidade',
        'tom_voz', 'estilo_comunicacao', 'saudacao_personalizada',
        'instrucoes_base', 'regras_atendimento', 'modelo_preferido',
        'temperatura', 'created_at', 'updated_at', 'max_tokens',
    }
    _LABEL_MAP = {
        'objetivos_venda':     'OBJETIVOS DE VENDA',
        'metas_comerciais':    'METAS COMERCIAIS',
        'script_vendas':       'SCRIPT DE VENDAS',
        'scripts_objecoes':    'RESPOSTAS A OBJEÇÕES',
        'frases_fechamento':   'FRASES DE FECHAMENTO',
        'diferenciais':        'DIFERENCIAIS DA EMPRESA',
        'posicionamento':      'POSICIONAMENTO DE MERCADO',
        'publico_alvo':        'PÚBLICO-ALVO',
        'restricoes':         'RESTRIÇÕES CRÍTICAS',
        'linguagem_proibida':  'LINGUAGEM PROIBIDA',
        'contexto_empresa':    'CONTEXTO DA EMPRESA',
        'contexto_extra':      'CONTEXTO EXTRA',
        'abordagem_proativa':  'ABORDAGEM PROATIVA',
        'idioma':              'IDIOMA',
        'exemplos':            'EXEMPLOS DE INTERAÇÃO',
        'palavras_proibidas':  'PALAVRAS E TERMOS PROIBIDOS',
        'despedida_personalizada': 'DESPEDIDA PERSONALIZADA',
        'regras_formatacao':   'REGRAS DE FORMATAÇÃO DE MENSAGEM',
        'regras_seguranca':    'REGRAS DE SEGURANÇA E PRIVACIDADE',
    }

    _extras_prompt = ""
    for campo, label in _LABEL_MAP.items():
        valor = pers.get(campo)
        if valor and str(valor).strip():
            if campo in ('idioma', 'exemplos', 'regras_formatacao', 'regras_seguranca', 'restricoes', 'palavras_proibidas', 'despedida_personalizada'):
                continue
            _extras_prompt += f"\n\n[{label}]\n{valor}"
    return _extras_prompt


async def montar_prompt_sistema(
    pers: dict,
    unidade: dict,
    slug: str,
    empresa_id: int,
    conversation_id: int,
    contato_fone: Optional[str],
    estado_atual: str,
    ctx_aluno: str,
    contexto_precarregado: str,
    primeira_mensagem: str,
    texto_cliente_unificado: str,
    mensagens_formatadas: str,
    intencao: Optional[str],
    planos_ativos: list,
    source: str = 'chatwoot',
) -> Dict[str, Any]:
    """
    Monta o system prompt completo para o LLM.

    Retorna dict com:
    - prompt_sistema: str — o prompt montado
    - todas_unidades: list — unidades ativas (para uso posterior no envio de mídia)
    - ab_info: dict | None — informações do teste A/B
    """
    nome_ia = pers.get('nome_ia') or 'Assistente Virtual'

    # Busca dados auxiliares
    faq = await carregar_faq_unidade(slug, empresa_id) or ""
    logger.info(f"🧠 PromptBuilder: FAQ carregado, montando prompt para conv {conversation_id}")
    historico = await bd_obter_historico_local(conversation_id, empresa_id, limit=12) or "Sem histórico."

    todas_unidades = await listar_unidades_ativas(empresa_id)
    lista_unidades_nomes = ", ".join([u["nome"] for u in todas_unidades])

    resumo_todas = "\n\n".join(
        resumo_unidade(u) for u in todas_unidades
    ) if todas_unidades else "A nossa rede possui diversas unidades, mas não tenho os detalhes de endereço delas agora."

    nome_empresa = unidade.get('nome_empresa') or 'Nossa Empresa'
    nome_unidade = unidade.get('nome') or 'Unidade Matriz'
    qtd_unidades_rede = len(todas_unidades or [])
    contexto_rede_unidades = (
        f"A rede {nome_empresa} possui {qtd_unidades_rede} unidades ativas. "
        "Quando fizer sentido na conversa, mencione essa quantidade para orientar o cliente."
        if qtd_unidades_rede > 1 else
        f"A rede {nome_empresa} está operando com 1 unidade ativa."
    )

    # Dados da unidade
    end_banco = extrair_endereco_unidade(unidade)
    hor_banco = unidade.get('horarios')
    tel_banco = extrair_telefone_unidade(unidade)
    dados_unidade = _montar_dados_unidade(unidade, end_banco, tel_banco, planos_ativos, hor_banco)

    # Campos da personalidade
    tom_voz          = pers.get('tom_voz') or 'Profissional, claro e prestativo'
    estilo           = pers.get('estilo_comunicacao') or ''
    saudacao         = pers.get('saudacao_personalizada') or f"Olá! Sou {nome_ia}, como posso ajudar?"
    instrucoes_base  = pers.get('instrucoes_base') or "Atenda o cliente de forma educada."
    regras_atend     = pers.get('regras_atendimento') or "Seja breve e objetivo."

    _extras_prompt = _montar_extras_personalidade(pers)

    # ── CONSTRUÇÃO MODULAR DO PROMPT ──────────────────────────────────────────
    blocos_prompt = []

    # 1. Cabeçalho de Regras e Idioma
    t_idioma = pers.get('idioma') or 'Português do Brasil'
    blocos_prompt.append(f"""[REGRAS GERAIS]
- Idioma obrigatório: {t_idioma}.
- NUNCA use inglês ou outros idiomas.
- NUNCA mostre tags internas, avisos de sistema ou colunas técnicas.
- NUNCA se apresente como IA ou robô.
- NUNCA cumprimente novamente ("Oi", "Olá", "Boa noite") se o histórico mostra que já cumprimentou. Comece direto com a resposta.
- Se o cliente já está em conversa (histórico tem 2+ mensagens), NÃO repita saudação. Vá direto ao ponto.""")

    # 2. Identidade
    blocos_prompt.append(f"""[IDENTIDADE]
- Seu nome: {nome_ia}.
- Sua função: Consultor da rede {nome_empresa}.
- Você atende TODAS as unidades da rede. NUNCA diga que é focado ou especializado em uma unidade específica.
{f"- O cliente está sendo atendido pela unidade *{nome_unidade}*. Use os dados DESTA unidade para responder." if slug else "- A unidade do cliente ainda não foi definida."}
- REGRA DE UNIDADE: Quando o cliente perguntar sobre planos, preços, grade, horários, link de compra — use SEMPRE os dados da unidade atual ({nome_unidade if slug else 'a definir'}). NUNCA pergunte "para qual unidade?" se a unidade já está definida acima.
- Se o cliente perguntar "quais unidades vocês tem?" ou "quais são?", LISTE TODAS as unidades pelos nomes na seção [UNIDADES DA REDE] abaixo.""")

    if ctx_aluno:
        blocos_prompt.append(f"[CONTEXTO DO ALUNO]\n{ctx_aluno}")

    # 2.5. Data e Hora atual (contexto temporal)
    _DIAS_PT = {0: "Segunda-feira", 1: "Terça-feira", 2: "Quarta-feira", 3: "Quinta-feira", 4: "Sexta-feira", 5: "Sábado", 6: "Domingo"}
    _MESES_PT = {1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"}
    _agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    _dia_semana = _DIAS_PT.get(_agora.weekday(), "")
    _mes_nome = _MESES_PT.get(_agora.month, "")
    blocos_prompt.append(f"""[DATA E HORA ATUAL]
Hoje: {_dia_semana}, {_agora.day} de {_mes_nome} de {_agora.year}.
Horário atual: {_agora.strftime('%H:%M')} (Brasília).
REGRAS TEMPORAIS:
- Se o cliente perguntar "tem aula hoje?", verifique as aulas de {_dia_semana} na grade.
- Se perguntar "amanhã?", verifique o dia seguinte ({_DIAS_PT.get((_agora.weekday() + 1) % 7, "")}).
- Se perguntar horário de funcionamento, use o horário de {_dia_semana} nos dados da unidade.
- NUNCA invente horários de aulas ou funcionamento. Use SOMENTE os dados fornecidos.""")

    # 3. Personalidade e Tom
    p_desc = pers.get('personalidade') or 'Atendente prestativo e simpático.'
    blocos_prompt.append(f"[PERSONALIDADE]\n{p_desc}")

    if tom_voz:
        blocos_prompt.append(f"[TOM DE VOZ]\n{tom_voz}")
    if estilo:
        blocos_prompt.append(f"[ESTILO DE COMUNICAÇÃO]\n{estilo}")

    # 4. Saudação e Instruções Base
    if saudacao:
        blocos_prompt.append(f"[SAUDAÇÃO PADRÃO]\n{saudacao}")
    if instrucoes_base:
        blocos_prompt.append(f"[INSTRUÇÕES BASE]\n{instrucoes_base}")

    # 5. Fluxo de Vendas e Negócio (Dinâmico)
    if _extras_prompt:
        blocos_prompt.append(f"[DIRETRIZES DE NEGÓCIO]{_extras_prompt}")

    # 6. Regras de Atendimento
    if regras_atend:
        blocos_prompt.append(f"[REGRAS DE ATENDIMENTO]\n{regras_atend}")

    # 6.5 Fluxo de Vendedor Real (proatividade)
    blocos_prompt.append("""[FLUXO DE VENDEDOR — OBRIGATÓRIO]
Você é um VENDEDOR, não um robô de FAQ. Siga este fluxo SEMPRE:
1. Responda a pergunta do cliente de forma direta e curta.
2. Depois da resposta, faça UMA pergunta de descoberta que avance a conversa.

Exemplos:
• Cliente: "Tem diária?" → "Temos sim! A diária custa R$40 💪 Você pretende treinar só hoje ou está pensando em começar academia?"
• Cliente: "Qual o horário?" → "Nosso horário é seg-sex 06h às 23h 😊 Você já treina ou está começando agora?"
• Cliente: "Quanto custa?" → "Temos planos a partir de R$X! Qual seu objetivo principal — musculação, cardio, ou os dois?"
• Cliente: "Quero começar" → "Que demais, parabéns pela decisão! 💪 Qual unidade fica mais perto de você? Posso te mostrar os planos e horários!"

REGRAS:
- Resposta + pergunta na MESMA mensagem, SEMPRE.
- A pergunta deve descobrir algo sobre o cliente (objetivo, frequência, localização, urgência).
- NUNCA adicione dados que o cliente NÃO pediu (ex: não jogue horários se ele perguntou preço).
- Se o cliente já respondeu uma descoberta, avance para o próximo passo (mostrar plano, agendar visita).
- NUNCA invente serviços ou ofertas — use apenas o que consta nos dados/FAQ fornecidos.
- Você PODE perguntar o primeiro nome do cliente de forma natural (ex: "E qual seu nome?" ou "Com quem eu falo?"). Mas NUNCA peça outros dados pessoais (CPF, email, endereço, telefone, RG, data de nascimento). Você é um vendedor, NÃO um formulário.""")

    # 7. Dados da Unidade e Rede
    blocos_prompt.append(f"""[INFORMAÇÕES DA UNIDADE ATUAL]
{dados_unidade}

[UNIDADES DA REDE {nome_empresa.upper()}]
{resumo_todas}

[CONTEXTO DA REDE]
{contexto_rede_unidades}""")

    # 8. FAQ e Mídia
    if faq:
        blocos_prompt.append(f"[FAQ — RESPOSTAS PRONTAS]\n{faq}")

    if pers.get('exemplos'):
        blocos_prompt.append(f"[EXEMPLOS DE INTERAÇÕES]\n{pers.get('exemplos')}")

    # 8.5. RAG — Base de Conhecimento
    try:
        _rag_query = primeira_mensagem or texto_cliente_unificado or ""
        if len(_rag_query.strip()) >= 10:
            _rag_resultados = await buscar_conhecimento(_rag_query, empresa_id, top_k=3)
            _bloco_rag = formatar_rag_para_prompt(_rag_resultados)
            if _bloco_rag:
                blocos_prompt.append(_bloco_rag)
    except Exception as _rag_err:
        logger.debug(f"RAG lookup falhou (não crítico): {_rag_err}")

    # 9. Regras de Sistema
    regras_seg = pers.get('regras_seguranca') or ""
    blocos_prompt.append(f"""[REGRAS DE SISTEMA]
- Responda diretamente se tiver os dados. Se não souber a unidade, pergunte a região.
- Se o cliente enviar apenas saudação social, responda apenas saudação e pergunte como ajudar.
- Use <SEND_IMAGE:slug> para grades e <SEND_VIDEO:slug> para tours virtuais quando solicitado.
{regras_seg}""")

    # 9.5. Memória de longo prazo do cliente
    if contato_fone:
        _memorias = await carregar_memoria_cliente(contato_fone, empresa_id)
        _bloco_memoria = formatar_memoria_para_prompt(_memorias)
        if _bloco_memoria:
            blocos_prompt.append(_bloco_memoria)

    # 10. Histórico e Regras Anti-Alucinação
    restricoes = pers.get('restricoes') or ""
    palavras_proibidas = pers.get('palavras_proibidas') or ""

    blocos_prompt.append(f"""[HISTÓRICO DA CONVERSA]
{historico}

[REGRAS CRÍTICAS — ANTI-ALUCINAÇÃO]
- Use EXCLUSIVAMENTE os dados fornecidos.
- Se não souber, diga que não tem a informação.
- Nunca invente endereços, telefones ou horários.
- NUNCA diga "vou buscar", "estou validando" ou "vou enviar o link" — se o link existe nos dados, ENVIE IMEDIATAMENTE. Se não existe, diga que o cliente pode procurar a unidade diretamente.
- NUNCA prometa enviar algo que você não tem nos dados. Se o campo mostra "não disponível" ou está vazio, NÃO prometa.
- Se o link de matrícula está nos dados da unidade, inclua-o DIRETAMENTE na resposta. Não peça dados pessoais antes de enviar o link.
- NUNCA confunda unidades. Responda SEMPRE sobre a unidade que está nos DADOS DA UNIDADE ATUAL acima. Se o cliente mencionar outra unidade, informe que vai direcionar.
{f"- RESTRIÇÕES: {restricoes}" if restricoes else ""}
{f"- NUNCA USE ESTAS PALAVRAS/TERMOS: {palavras_proibidas}" if palavras_proibidas else ""}""")

    # 11. Formatação (WhatsApp)
    r_format = pers.get('regras_formatacao') or ""
    e_tipo = pers.get('emoji_tipo') or "✨"
    e_cor = pers.get('emoji_cor') or "#00d2ff"

    blocos_prompt.append(f"""[FORMATAÇÃO WHATSAPP — OBRIGATÓRIO]
REGRAS DE FORMATAÇÃO:
- Use *bold* para destaque (nomes de planos, preços, horários, nomes de unidade).
- Listas com • (bullet point Unicode). NUNCA use "* " ou "- " como marcador de lista. SEMPRE use "• ".
  CORRETO: • Plano Silver: R$ 89,90/mês
  ERRADO: * Plano Silver: R$ 89,90/mês
  ERRADO: - Plano Silver: R$ 89,90/mês
- Separe blocos de informação com linha em branco para facilitar leitura.
- NUNCA use markdown (**, ##, ```, [ ], etc). WhatsApp só suporta *bold*, _itálico_ e ~riscado~.
- Tamanho ideal: 2-4 parágrafos curtos. Máximo 5 parágrafos.
- TERMINAR sempre com frases completas. NUNCA cortar no meio de uma frase.
- Quando listar horários de aulas, use formato organizado:
  • *Modalidade*: Dia às HHhMM
- Quando listar preços, destaque o valor: *R$ XX,XX*/mês
- Quando listar planos, inclua nome e diferencial principal de cada um.
- EMOJI PRINCIPAL DA IA: {e_tipo}. Use-o com frequência.
- PALETA DE CORES/VIBE: {e_cor}. Priorize emojis e tons que combinem com esta cor.
- Use emojis para separar seções visualmente (ex: 🏋️ para treino, 📍 para endereço, 🕒 para horário).
- NÃO repita emojis em sequência. Varie entre os emojis relevantes.
{r_format}""")

    # 12. Despedida e dados do atendimento
    despedida = pers.get('despedida_personalizada') or ""
    if despedida:
        blocos_prompt.append(f"[DESPEDIDA PADRÃO]\n{despedida}")

    ctx_saudacao = "[SISTEMA: O cliente enviou APENAS UMA SAUDAÇÃO SOCIAL. Responda SOMENTE saudação e pergunte como ajudar.]" if eh_saudacao(primeira_mensagem or "") else ""

    contexto_precarregado_bloco = f"\n[CONTEXTO PRÉ-CARREGADO]\n{contexto_precarregado}" if contexto_precarregado else ""

    blocos_prompt.append(f"""[DADOS DO ATENDIMENTO]
Estado emocional: {estado_atual}
REGRA DE NOME: NUNCA assuma o nome do cliente. Use o nome SOMENTE se o próprio cliente já informou no histórico da conversa. Se ainda não sabe o nome, pergunte de forma natural (ex: "E qual seu nome?" ou "Com quem eu falo?"). Depois que souber, use o primeiro nome do cliente nas mensagens seguintes.
{contexto_precarregado_bloco}{ctx_saudacao}

[MENSAGENS DO CLIENTE]
{mensagens_formatadas}

RESPONDA com a mensagem diretamente — texto puro.""")

    # 13. A/B Testing
    _ab_info = None
    try:
        blocos_prompt, _ab_info = await aplicar_teste_ab(empresa_id, conversation_id, blocos_prompt)
        if _ab_info:
            logger.info(f"🧪 A/B Test '{_ab_info['nome']}' variante={_ab_info['variante']} conv={conversation_id}")
    except Exception as _ab_err:
        logger.debug(f"A/B test lookup falhou (não crítico): {_ab_err}")

    prompt_sistema = truncar_contexto(blocos_prompt, max_tokens=12000)

    # Injeta informação sobre grade/modalidades
    _foto_grade = unidade.get("foto_grade")
    _modalidades_texto = unidade.get("modalidades") or ""
    if _foto_grade or _modalidades_texto:
        prompt_sistema += "\n[GRADE DE AULAS & MODALIDADES — REGRAS]\n"
        if _modalidades_texto:
            prompt_sistema += "Você TEM acesso ao conteúdo textual completo das modalidades e grade de aulas desta unidade. Os dados estão no campo 'Modalidades' acima nos DADOS DA UNIDADE.\n"
            prompt_sistema += "REGRA PRIORITÁRIA: Sempre responda sobre aulas, modalidades, horários de aulas e grade usando o TEXTO que você já possui. Explique verbalmente.\n"
            prompt_sistema += "Se o cliente perguntar sobre uma modalidade específica (ex: fit dance, pilates, yoga), busque nos dados textuais e responda com as informações que tem.\n"
            prompt_sistema += "Se o cliente não consegue ler, tem dificuldade visual, ou pediu por áudio — NUNCA ofereça imagem. Use o texto para explicar verbalmente.\n"
        if _foto_grade:
            prompt_sistema += "Esta unidade também TEM uma imagem da grade de aulas disponível.\n"
            prompt_sistema += "A imagem é um COMPLEMENTO — ofereça APÓS já ter respondido com o texto. Exemplo: 'E se quiser ver a grade completa com os horários certinhos, posso te enviar a imagem também!'\n"
            prompt_sistema += "Para enviar a imagem, adicione a tag <SEND_IMAGE> no final da sua resposta.\n"
            prompt_sistema += "NUNCA envie a imagem como primeira/única resposta. Sempre responda com texto primeiro.\n"

    # Injeta informação sobre Tour Virtual
    _link_tour = unidade.get("link_tour_virtual")
    if _link_tour:
        _oferecer_tour_ativo = pers.get("oferecer_tour", True)
        _estrategia_tour = pers.get("estrategia_tour") or ""
        _tour_perguntar_visita = pers.get("tour_perguntar_primeira_visita", False)
        _tour_msg_custom = pers.get("tour_mensagem_custom") or ""
        _tipo_cli = detectar_tipo_cliente(primeira_mensagem or "")
        _eh_lead = _tipo_cli is None

        if _oferecer_tour_ativo and _eh_lead:
            _frases_tour = _tour_msg_custom if _tour_msg_custom else (
                '- "Temos um vídeo incrível mostrando nossa unidade por dentro! Quer ver?"\n'
                '- "Que tal dar uma espiadinha na nossa estrutura? Tenho um vídeo do tour virtual pra te mostrar!"\n'
                '- "Antes de você vir nos visitar, posso te enviar um tour virtual da unidade pra você já conhecer o espaço!"'
            )
            _bloco_estrategia = f"\nESTRATÉGIA CUSTOMIZADA:\n{_estrategia_tour}" if _estrategia_tour else ""
            _bloco_visita = "\n- Se o cliente demonstrar interesse, pergunte se seria a primeira visita dele na unidade." if _tour_perguntar_visita else ""
            prompt_sistema += f"""
[TOUR VIRTUAL — MODO PROATIVO]
Esta unidade possui um vídeo de Tour Virtual disponível.

VOCÊ DEVE oferecer proativamente o tour virtual ao cliente. Este cliente é um LEAD (potencial novo aluno).
{_bloco_estrategia}
ESTRATÉGIA DE OFERECIMENTO:
1. Se o cliente demonstrar QUALQUER sinal de interesse em conhecer, visitar ou saber mais sobre a unidade, ofereça o tour IMEDIATAMENTE.
   Sinais de interesse incluem: quero conhecer, como é a academia, posso ir lá, gostaria de ver, é bom?, tem estrutura?, como é por dentro, quero visitar, tem piscina, me fala mais, como funciona, quero começar, to pensando em treinar, quais aparelhos, qual a estrutura.
2. Após responder 2-3 mensagens de rapport com o lead (mesmo sem pergunta direta sobre a unidade), se ainda não ofereceu, OFEREÇA o tour naturalmente.
3. Se o lead perguntou sobre preços/planos, após responder, complemente oferecendo o tour.
4. NÃO ofereça o tour mais de uma vez na conversa. Se já ofereceu ou se o cliente recusou, não insista.{_bloco_visita}

COMO OFERECER:
{_frases_tour}

IMPORTANTE: Para enviar o vídeo do tour, adicione a tag <SEND_VIDEO> no final da sua resposta.
Sempre ofereça ANTES de enviar — não envie sem perguntar. Quando o lead aceitar, aí sim use <SEND_VIDEO>.
"""
        else:
            prompt_sistema += "\n[SISTEMA]: Esta unidade TEM um vídeo de Tour Virtual disponível.\n"
            prompt_sistema += "Se o cliente demonstrar interesse em conhecer a academia, ver por dentro ou perguntar por tour virtual, ofereça e envie o vídeo.\n"
            prompt_sistema += "IMPORTANTE: Para enviar o vídeo do tour, adicione a tag <SEND_VIDEO> no final da sua resposta.\n"

    return {
        "prompt_sistema": prompt_sistema,
        "todas_unidades": todas_unidades,
        "ab_info": _ab_info,
    }
