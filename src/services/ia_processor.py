import asyncio
import re
import json
import time
import io
import os
import base64
import zlib
import uuid
import random
import hashlib
import httpx
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple

from rapidfuzz import fuzz
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

from src.core.config import (
    logger, PROMETHEUS_OK,
    METRIC_IA_LATENCY, METRIC_FAST_PATH_TOTAL, METRIC_ERROS_TOTAL,
    METRIC_CONVERSAS_ATIVAS, METRIC_PLANOS_ENVIADOS, METRIC_ALUNO_DETECTADO,
    OPENAI_API_KEY
)
import src.core.database as _database
from src.core.redis_client import redis_client, redis_get_json, redis_set_json
from src.core.security import cb_llm
from src.utils.text_helpers import (
    normalizar, comprimir_texto, descomprimir_texto, limpar_nome,
    primeiro_nome_cliente, nome_eh_valido, extrair_nome_do_texto, limpar_markdown
)
from src.utils.intent_helpers import (
    SAUDACOES, eh_saudacao, eh_confirmacao_curta, classificar_intencao,
    _faq_compativel_com_intencao, garantir_frase_completa
)
from src.utils.time_helpers import (
    saudacao_por_horario, horario_hoje_formatado, formatar_horarios_funcionamento,
    esta_aberta_agora
)
from src.services.llm_service import cliente_ia, cliente_whisper, is_provider_unavailable_error, is_openrouter_auth_error
from src.services.db_queries import (
    buscar_planos_ativos, formatar_planos_para_prompt, listar_unidades_ativas,
    buscar_unidade_na_pergunta, carregar_unidade, carregar_personalidade,
    carregar_configuracao_global, bd_iniciar_conversa, bd_salvar_mensagem_local,
    bd_obter_historico_local, bd_atualizar_msg_cliente, bd_atualizar_msg_ia,
    bd_registrar_primeira_resposta, bd_registrar_evento_funil, buscar_resposta_faq,
    carregar_faq_unidade
)
from src.services.chatwoot_client import (
    simular_digitacao, enviar_mensagem_chatwoot, atualizar_nome_contato_chatwoot
)
import src.services.chatwoot_client as _chatwoot_module


async def resolver_contexto_unidade(
    conversation_id: int,
    texto: str,
    empresa_id: int,
    slug_atual: Optional[str] = None
) -> Dict[str, Optional[str]]:
    """Resolve unidade da conversa em um único ponto (mensagem > contexto)."""
    # Prioriza contexto já salvo em Redis (mais confiável que slug transitório do webhook)
    slug_redis = await redis_client.get(f"unidade_escolhida:{conversation_id}")
    slug_salvo = slug_redis or slug_atual

    # Só tenta trocar unidade com evidência geográfica para evitar trocas acidentais.
    # Aqui consideramos:
    # 1) match direto de nome/cidade/bairro
    # 2) interseção de tokens significativos com nome da unidade (ex.: "ricardo jafet")
    texto_norm = normalizar(texto or "")
    tokens_texto_sig = {t for t in texto_norm.split() if len(t) >= 4}
    tem_geo = False
    try:
        unidades = await listar_unidades_ativas(empresa_id)
        for u in unidades:
            nome_u = normalizar(u.get("nome", "") or "")
            cidade_u = normalizar(u.get("cidade", "") or "")
            bairro_u = normalizar(u.get("bairro", "") or "")

            # Match direto
            if any(ind and len(ind) >= 4 and ind in texto_norm for ind in (nome_u, cidade_u, bairro_u)):
                tem_geo = True
                break

            # Match por tokens do nome da unidade (suporta "ricardo jafet" sem nome completo)
            tokens_nome_sig = {t for t in nome_u.split() if len(t) >= 4 and t not in {"red", "fitness", "academia", "unidade"}}
            if len(tokens_texto_sig & tokens_nome_sig) >= 1:
                tem_geo = True
                break
    except Exception:
        tem_geo = False

    slug_detectado = await buscar_unidade_na_pergunta(texto, empresa_id) if tem_geo else None

    if slug_detectado:
        mudou = slug_detectado != slug_salvo
        if mudou:
            await redis_client.setex(f"unidade_escolhida:{conversation_id}", 86400, slug_detectado)
        return {"slug": slug_detectado, "origem": "mensagem", "mudou": "true" if mudou else "false"}

    if slug_salvo:
        return {"slug": slug_salvo, "origem": "contexto", "mudou": "false"}

    return {"slug": None, "origem": "indefinido", "mudou": "false"}


def responder_horario(unidade: dict) -> str:
    nome = unidade.get("nome") or "da unidade"
    horarios = formatar_horarios_funcionamento(unidade.get("horarios"))
    return (
        f"🕒 O horário da unidade *{nome}* é:\n"
        f"{horarios}\n\n"
        "Se quiser, também posso te passar o endereço 😊"
    )


def extrair_endereco_unidade(unidade: dict) -> Optional[str]:
    """Monta endereço completo com número quando necessário."""
    endereco = (unidade.get("endereco_completo") or unidade.get("endereco") or "").strip()
    numero = str(unidade.get("numero") or "").strip()
    if not endereco:
        return None
    if numero and numero.lower() not in {"s/n", "sn"}:
        # Se número ainda não aparece no endereço, concatena
        if numero not in endereco:
            endereco = f"{endereco}, {numero}"
    return endereco


def normalizar_lista_campo(valor: Any) -> List[str]:
    """Converte campo de lista (list/json/string) em itens limpos para WhatsApp."""
    if not valor:
        return []
    if isinstance(valor, list):
        bruto = valor
    elif isinstance(valor, str):
        txt = valor.strip()
        if not txt:
            return []
        try:
            parsed = json.loads(txt)
            if isinstance(parsed, list):
                bruto = parsed
            elif isinstance(parsed, str):
                bruto = [parsed]
            else:
                bruto = [txt]
        except Exception:
            # Se vier texto corrido/grade, quebra por linha e separadores mais comuns
            bruto = [p for p in re.split(r"\n+|;|\|", txt) if p and p.strip()]
    else:
        bruto = [str(valor)]

    itens = []
    for item in bruto:
        t = str(item).strip()
        if not t:
            continue
        # Remove marcadores/bullets estranhos no início
        t = re.sub(r"^[•\-⁠​\s]+", "", t).strip()
        if len(t) <= 1:
            continue
        itens.append(t)

    # Se ainda parece texto por caractere, tenta recompor como única linha
    if itens and all(len(i) == 1 for i in itens):
        juntado = "".join(itens).strip()
        return [juntado] if juntado else []

    return itens


def extrair_telefone_unidade(unidade: dict) -> Optional[str]:
    return (
        unidade.get("telefone_principal")
        or unidade.get("telefone")
        or unidade.get("whatsapp")
    )


def responder_endereco(unidade: dict) -> str:
    nome = unidade.get("nome") or "da unidade"
    endereco = extrair_endereco_unidade(unidade)
    if not endereco:
        return (
            f"📍 No momento não encontrei o endereço da unidade *{nome}*.\n\n"
            "Se quiser, posso te passar o telefone da unidade."
        )
    return (
        f"📍 A unidade *{nome}* fica em:\n{endereco}\n\n"
        "Se quiser, também te passo o horário de funcionamento 😊"
    )


    return (
        f"📞 O contato da unidade *{nome}* é:\n{telefone}\n\n"
        "Se quiser, também posso te passar o endereço ou horário."
    )


def responder_modalidades(unidade: dict) -> str:
    nome = unidade.get("nome") or "da unidade"
    modalidades = normalizar_lista_campo(unidade.get("modalidades"))
    foto_grade = unidade.get("foto_grade")
    
    if not modalidades:
        return (
            f"💪 Na unidade *{nome}* temos diversas atividades incríveis!\n\n"
            "Geralmente temos musculação, cardio e aulas coletivas. "
            "Qual modalidade você mais gosta? 😊"
        )
    
    lista = "\n".join([f"• {m}" for m in modalidades])
    resposta = f"💪 Na unidade *{nome}* temos:\n\n{lista}"
    
    if foto_grade:
        resposta += f"\n\n🖼️ *Também tenho a imagem com a grade completa de horários aqui!* Quer que eu te envie? 😊"
    else:
        resposta += "\n\nQual dessas você mais tem interesse? 😊"
        
    return resposta


async def responder_lista_unidades(empresa_id: int, texto: str) -> str:
    unidades = await listar_unidades_ativas(empresa_id)
    if not unidades:
        return "No momento não encontrei unidades cadastradas."

    texto_norm = normalizar(texto)
    cidade_filtro = None
    for u in unidades:
        cidade = normalizar(u.get("cidade", "") or "")
        if cidade and cidade in texto_norm:
            cidade_filtro = u.get("cidade")
            break

    if cidade_filtro:
        unidades = [u for u in unidades if normalizar(u.get("cidade", "") or "") == normalizar(cidade_filtro)]

    lista = "\n".join([f"• {u['nome']}" for u in unidades])
    if cidade_filtro:
        return (
            f"📍 Temos {len(unidades)} unidade(s) em *{cidade_filtro}*:\n\n{lista}\n\n"
            "Qual delas fica melhor para você? 😊"
        )
    return f"📍 Temos {len(unidades)} unidades:\n\n{lista}\n\nQual delas fica mais perto de você? 😊"


async def gerar_resposta_inteligente(
    conversation_id: int,
    empresa_id: int,
    texto_cliente: str,
    slug_atual: Optional[str] = None,
    nome_cliente: Optional[str] = None
) -> Dict[str, Any]:
    """Motor de decisão enxuto: fast-path apenas para horário/endereço."""
    ctx = await resolver_contexto_unidade(conversation_id, texto_cliente, empresa_id, slug_atual=slug_atual)
    slug = ctx.get("slug")
    intencao = classificar_intencao(texto_cliente)

    if intencao in {"horario", "endereco"} and not slug:
        _primeiro_nome = primeiro_nome_cliente(nome_cliente)
        _prefixo = f"{_primeiro_nome}, " if _primeiro_nome else ""
        return {
            "tipo": "texto",
            "resposta": f"{_prefixo}me fala a *cidade* ou *bairro* da unidade que você quer 😊",
            "slug": None,
            "intencao": intencao,
        }

    unidade = await carregar_unidade(slug, empresa_id) if slug else {}

    if intencao == "horario":
        return {"tipo": "texto", "resposta": responder_horario(unidade), "slug": slug, "intencao": intencao}
    if intencao == "endereco":
        return {"tipo": "texto", "resposta": responder_endereco(unidade), "slug": slug, "intencao": intencao}
    if intencao == "modalidades":
        return {"tipo": "texto", "resposta": responder_modalidades(unidade), "slug": slug, "intencao": intencao}

    return {
        "tipo": "llm", 
        "resposta": None, 
        "slug": slug, 
        "intencao": "llm",
        "foto_grade": unidade.get("foto_grade")
    }


def montar_saudacao_humanizada(
    nome_cliente: str,
    nome_ia: str,
    pers: dict,
    unidade: dict,
    hor_banco: Any,
) -> str:
    """
    Monta uma saudação super humanizada:
    - Usa o nome do cliente se disponível
    - Deseja bom dia/boa tarde/boa noite pelo horário de SP
    - Menciona horário de HOJE se disponível no banco
    - Tom quente e acolhedor
    """
    cumprimento = saudacao_por_horario()
    nome_limpo = limpar_nome(nome_cliente) if nome_cliente else ""

    # Monta a primeira linha: cumprimento + nome
    if nome_limpo and nome_limpo.lower() not in ("cliente", "contato", "visitante", ""):
        primeiro_nome = nome_limpo.split()[0].capitalize()
        linha1 = f"{cumprimento}, {primeiro_nome}! 😊"
    else:
        linha1 = f"{cumprimento}! 😊"

    # Apresentação do assistente
    linha2 = f"Eu sou {'a' if nome_ia and nome_ia[-1].lower() == 'a' else 'o'} {nome_ia}, tudo bem?"

    # Horário de hoje (se disponível no banco)
    horario_hoje = horario_hoje_formatado(hor_banco)
    if horario_hoje:
        agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
        NOMES_DIA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
        nome_dia = NOMES_DIA[agora.weekday()]
        linha3 = f"Hoje ({nome_dia}) estamos funcionando das {horario_hoje} 💪"
    else:
        linha3 = ""

    # Pergunta final
    linha4 = "Como posso te ajudar?"

    # Monta mensagem
    partes = [linha1, linha2]
    if linha3:
        partes.append(linha3)
    partes.append(linha4)

    return "\n\n".join(partes)


# 🏋️ PALAVRAS-CHAVE DE TIPO DE CLIENTE — detecta aluno atual ou usuário de convênio
ALUNO_KEYWORDS = [
    "sou aluno", "ja sou aluno", "já sou aluno", "sou cliente", "sou membro",
    "meu contrato", "minha matricula", "minha matrícula", "meu plano atual",
    "cancelar meu", "congelar minha", "pausar minha", "segunda via",
    "boleto atrasado", "fatura", "renovar meu", "transferir minha",
    "mudei de unidade", "troca de unidade", "problema com",
    "atendimento ao cliente", "suporte", "reclamacao", "reclamação",
]

GYMPASS_KEYWORDS = [
    "gympass", "totalpass", "wellhub", "sesi", "sesc",
    "convenio", "convênio", "beneficio corporativo", "benefício corporativo",
    "pelo app", "pelo aplicativo", "app parceiro", "parceria empresa",
    "plano empresarial", "beneficio da empresa", "benefício da empresa",
]


def detectar_tipo_cliente(texto: str) -> Optional[str]:
    """
    Detecta se o cliente já é aluno (suporte/cancelamento/dúvidas)
    ou usa convênio/gympass (roteamento diferente).
    Retorna: 'aluno' | 'gympass' | None
    """
    if not texto:
        return None
    norm = normalizar(texto)
    if any(k in norm for k in [normalizar(k) for k in GYMPASS_KEYWORDS]):
        return "gympass"
    if any(k in norm for k in [normalizar(k) for k in ALUNO_KEYWORDS]):
        return "aluno"
    return None

# 🎯 MAPEAMENTO DE INTENÇÕES PARA CACHE SEMÂNTICO
INTENCOES = {
    "preco": ["preco", "preço", "valor", "quanto custa", "mensalidade", "planos", "promoção", "promocao", "valores", "custa"],
    "horario": ["horario", "horário", "funcionamento", "abre", "fecha", "que horas", "aberto", "funciona", "horarios"],
    "endereco": ["endereco", "endereço", "local", "localização", "fica", "onde fica", "como chegar", "localizacao"],
    "telefone": ["telefone", "contato", "whatsapp", "numero", "número", "ligar", "falar", "telefone"],
    "unidades": ["unidades", "outras unidades", "lista de unidades", "quantas unidades", "onde tem", "tem em", "unidade"],
    "modalidades": ["modalidades", "atividades", "exercícios", "treinos", "aula", "aulas", "grade", "grade de aula", "grade de aulas", "musculação", "cardio", "spinning", "alongamento", "crossfit", "funcional"],
    "infraestrutura": ["estacionamento", "vestiário", "chuveiro", "armários", "sauna", "piscina", "acessibilidade", "infraestrutura"],
    "matricula": ["matricula", "matrícula", "inscrição", "cadastro", "se inscrever", "assinar", "contratar"]
}

# --- CONTROLE DE CONCORRÊNCIA ---
whisper_semaphore = asyncio.Semaphore(5)
llm_semaphore = asyncio.Semaphore(15)
USAR_CACHE_SEMANTICO = os.getenv("USAR_CACHE_SEMANTICO", "false").lower() == "true"

LUA_RELEASE_LOCK = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

# Regex compiladas para intenções frequentes (manutenção centralizada)
REGEX_PEDIDO_PLANOS = re.compile(
    r"(preco|valor(es)?|quanto (custa|cobra|fica)|mensalidade|planos?|promocao|promoç|"
    r"beneficio|benefícios|benefíci|quais.{0,10}planos|me (fala|mostra|manda).{0,15}planos?|"
    r"tem planos?|ver planos?|quero (assinar|contratar|me matricular)|"
    r"como (faço|faz|funciona).{0,10}(matric|assinar|contratar)|"
    r"quanto (é|e|custa|vale) o plano|opcoes.{0,10}planos?|opções.{0,10}planos?)",
    re.IGNORECASE,
)
REGEX_PEDIDO_END_HOR = re.compile(
    r"(endereco|enderco|localizacao|fica onde|onde fica|como chego|qual o local|onde voces ficam"
    r"|horario|funcionamento|abre|fecha|que horas|ta aberto|esta aberto)",
    re.IGNORECASE,
)
REGEX_PEDIDO_CONTATO = re.compile(r"(telefone|contato|whatsapp|numero|ligar|falar com alguem)", re.IGNORECASE)
REGEX_LISTAR_UNIDADES = re.compile(
    r"(quais.{0,15}unidades?|quantas.{0,10}unidades?|tem.{0,20}unidades?|unidades?.{0,10}tem|"
    r"mais.{0,10}unidades?|outras.{0,10}unidades?|lista.{0,10}unidades?|onde.{0,10}academia|"
    r"academia.{0,15}(sp|sao paulo|rio|rj|mg|bh)|saber.{0,10}unidades?|todas.{0,10}unidades?|"
    r"unidades?.{0,10}existem|unidades?.{0,10}disponiveis|unidades?.{0,10}abertas|"
    r"unidades?.{0,15}(sp|sao paulo|rio|rj|mg|bh|campinas|curitiba|belo horizonte|brasilia))",
    re.IGNORECASE,
)

# ==================== MENSAGENS PRÉ-FORMATADAS ====================
# Removido ** (markdown duplo) — WhatsApp usa *asterisco simples* para negrito

RESPOSTAS_UNIDADES = [
    "🏢 Temos {total} unidades:\n\n{lista_str}\n\nQual delas fica mais perto de você?",
    "Claro! Nossas unidades são:\n\n{lista_str}\n\nQual é a mais conveniente pra você?",
    "Aqui estão nossas {total} unidades:\n\n{lista_str}\n\nEm qual posso te ajudar?",
    "Temos {total} unidades disponíveis:\n\n{lista_str}\n\nQual prefere?",
]

RESPOSTAS_ENDERECO = [
    "📍 Ficamos aqui:\n{endereco}\n\nPosso te ajudar com mais alguma dúvida?",
    "Nosso endereço é:\n{endereco}\n\nPrecisando de mais informações, é só falar!",
    "Estamos localizados em:\n{endereco}\n\nSe quiser, também posso passar os horários de funcionamento."
]

RESPOSTAS_HORARIO = [
    "🕒 Nosso horário de funcionamento é:\n\n{horario_str}\n\nSe quiser, posso te ajudar com planos e valores também!",
    "Funcionamos nos seguintes horários:\n\n{horario_str}\n\nAlguma dúvida sobre os horários?",
    "Horário de atendimento:\n\n{horario_str}\n\nEstamos prontos para te receber! 💪"
]

RESPOSTAS_CONTATO = [
    "📞 Nosso número de contato é:\n{tel_banco}\n\nPosso ajudar com mais algo?",
    "Pode entrar em contato conosco pelo telefone:\n{tel_banco}\n\nEstamos à disposição!",
    "Nosso WhatsApp é:\n{tel_banco}\n\nFique à vontade para chamar! 😊"
]
# ===================================================================


def formatar_planos_bonito(planos: List[Dict], destacar_melhor_preco: bool = True) -> List[str]:
    """
    Formata os planos de forma bonita para envio ao cliente via WhatsApp/Chatwoot.
    Retorna uma LISTA de strings — cada item = uma mensagem separada no chat.

    Formato por plano:
        🏋️ *Plano Nome*

        Pitch do plano aqui.

        Você terá acesso a:

        • Diferencial 1
        • Diferencial 2
        • Diferencial 3

        Tudo isso por apenas:

        💰 *R$XX,XX por mês*

        ⚡ *Oferta: Xmeses por R$XX,XX/mês*   (se houver promoção)

        👉 Comece agora:
        https://link-aqui

        Quer saber como funciona ou tirar alguma dúvida?
    """
    if not planos:
        return ["Não temos planos disponíveis no momento. 😕"]

    # Emojis rotativos por posição para dar variedade visual
    _EMOJIS_PLANO = ["🏋️", "💪", "⚡", "🔥", "🎯", "🌟"]

    blocos: List[str] = []

    planos_ordenados = list(planos)
    if destacar_melhor_preco:
        def _valor_plano(item: Dict[str, Any]) -> float:
            raw = item.get('valor_promocional') if item.get('valor_promocional') not in (None, "") else item.get('valor')
            try:
                v = float(raw)
                return v if v > 0 else 999999.0
            except (TypeError, ValueError):
                return 999999.0

        planos_ordenados.sort(key=_valor_plano)

    for idx, p in enumerate(planos_ordenados):
        nome = p.get('nome', 'Plano')
        link = p.get('link_venda', '') or ''

        if not link.strip():
            continue  # Plano sem link de matrícula não é exibido

        # ── Valores ──────────────────────────────────────────────────
        try:
            valor_float = float(p['valor']) if p.get('valor') is not None else None
        except (TypeError, ValueError):
            valor_float = None

        try:
            promo_float = float(p['valor_promocional']) if p.get('valor_promocional') is not None else None
        except (TypeError, ValueError):
            promo_float = None

        meses_promo = p.get('meses_promocionais')

        # ── Diferenciais ─────────────────────────────────────────────
        diferenciais = p.get('diferenciais') or []
        if isinstance(diferenciais, str):
            # Tenta deserializar caso venha como JSON string
            try:
                diferenciais = json.loads(diferenciais)
            except (json.JSONDecodeError, ValueError):
                diferenciais = [d.strip() for d in diferenciais.split(',') if d.strip()]
        if not isinstance(diferenciais, list):
            diferenciais = []

        # ── Pitch/descrição ──────────────────────────────────────────
        # Ignora pitch que pareça código de banco (todo maiúsculo, igual ao nome, etc.)
        _pitch_raw = (
            p.get('descricao') or
            p.get('pitch') or
            p.get('slogan') or
            ""
        )
        _pitch_raw = str(_pitch_raw).strip()
        _e_codigo = (
            _pitch_raw == _pitch_raw.upper()         # todo maiúsculo
            or normalizar(_pitch_raw) == normalizar(nome)   # igual ao nome do plano
            or len(_pitch_raw) < 10                  # curto demais para ser um pitch real
        )
        pitch = None if _e_codigo or not _pitch_raw else _pitch_raw

        # ── Emoji do plano ───────────────────────────────────────────
        emoji = _EMOJIS_PLANO[idx % len(_EMOJIS_PLANO)]

        # ── Montagem do bloco ────────────────────────────────────────
        linhas: List[str] = []

        # Cabeçalho
        _selo = " 🏆 *MELHOR CUSTO-BENEFÍCIO*" if destacar_melhor_preco and idx == 0 else ""
        linhas.append(f"{emoji} *{nome}*{_selo}")

        # Pitch (só se existir e não for código)
        if pitch:
            linhas.append("")
            linhas.append(pitch)

        # Diferenciais
        if diferenciais:
            linhas.append("")
            linhas.append("Você terá acesso a:")
            linhas.append("")
            for dif in diferenciais:
                linhas.append(f"• {str(dif).strip()}")
            linhas.append("")
            linhas.append("Tudo isso por apenas:")
            linhas.append("")
        else:
            linhas.append("")

        # Preço principal
        if valor_float and valor_float > 0:
            valor_fmt = f"{valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            linhas.append(f"💰 *R${valor_fmt} por mês*")
        else:
            linhas.append("💰 *Consulte o valor*")

        # Promoção (opcional)
        if promo_float and promo_float > 0 and meses_promo:
            promo_fmt = f"{promo_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            linhas.append("")
            linhas.append(f"⚡ *Oferta: {meses_promo}x R${promo_fmt}/mês*")

        # Link de matrícula
        linhas.append("")
        linhas.append("👉 Comece agora:")
        linhas.append(link.strip())

        # ⚠️ SEM pergunta de fechamento aqui — vai só no último bloco (ver abaixo)

        blocos.append("\n".join(linhas))

    if not blocos:
        return ["Não temos planos disponíveis no momento. 😕"]

    # Pergunta de fechamento apenas no ÚLTIMO plano
    blocos[-1] += "\n\nQuer saber mais sobre algum plano ou tirar alguma dúvida? 😊"

    # Cada bloco = mensagem separada
    return blocos


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

    # Limita a 3 para não poluir, mas mantém contexto comercial claro.
    return melhores[:3]


async def renovar_lock(chave: str, valor: str, intervalo: int = 40):
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


# ── Cache Semântico por Embedding via API ────────────────────────────────────
# Usa text-embedding-3-small via OpenRouter/OpenAI (async, sem CPU local).
# 90% mais leve que SentenceTransformer — não bloqueia event loop.
# Fallback automático para cache por hash md5 se API falhar.

def _cosine_sim(a: list, b: list) -> float:
    """Similaridade de cosseno entre dois vetores (pura Python, sem numpy)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    return dot / (norm_a * norm_b) if norm_a > 0 and norm_b > 0 else 0.0


async def _get_embedding(texto: str) -> Optional[List[float]]:
    """
    Obtém embedding via API (text-embedding-3-small).
    Retorna None se a API falhar — o sistema cai no hash cache.
    """
    if not cliente_ia:
        return None
    # Textos muito curtos (saudações, "oi", "ok") não geram cache semântico útil
    # e evitam custo de API desnecessário em escala
    if len(texto.strip()) <= 15:
        return None
    try:
        resp = await cliente_ia.embeddings.create(
            model="text-embedding-3-small",
            input=texto[:512],  # Trunca para economizar tokens
        )
        return resp.data[0].embedding
    except Exception as e:
        logger.debug(f"Embedding API indisponível: {e}")
        return None


async def buscar_cache_semantico(
    texto: str,
    slug: str,
    threshold: float = 0.88
) -> Optional[Dict]:
    """
    Busca no Redis por uma resposta cacheada semanticamente similar à pergunta.
    Usa embedding via API (async) + SCAN (não bloqueia Redis) + cosine similarity.
    Retorna dict {"resposta": ..., "estado": ...} ou None.
    """
    emb_query = await _get_embedding(texto)
    if not emb_query:
        return None  # API indisponível — usa hash cache

    try:
        pattern = f"semcache:{slug}:*"
        melhor_score = 0.0
        melhor_key   = None
        total_scan   = 0

        # ✅ SCAN em vez de KEYS — não trava o Redis
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(cursor, match=pattern, count=50)
            for k in keys:
                total_scan += 1
                if total_scan > 300:   # limita a 300 entradas por slug
                    break
                emb_str = await redis_client.hget(k, "embedding")
                if not emb_str:
                    continue
                emb_cached = json.loads(emb_str)
                score = _cosine_sim(emb_query, emb_cached)
                if score > melhor_score:
                    melhor_score = score
                    melhor_key   = k
            if cursor == 0 or total_scan > 300:
                break

        if melhor_score >= threshold and melhor_key:
            resposta_str = await redis_client.hget(melhor_key, "resposta")
            if resposta_str:
                logger.info(f"🧠 Cache semântico HIT (sim={melhor_score:.3f}) para '{texto[:40]}'")
                return json.loads(resposta_str)
    except Exception as e:
        logger.warning(f"Cache semântico erro: {e}")
    return None


async def salvar_cache_semantico(
    texto: str,
    slug: str,
    dados: Dict,
    ttl: int = 3600
):
    """
    Salva embedding (via API) + resposta no Redis para uso futuro.
    Chave: semcache:{slug}:{md5(texto)}
    """
    emb = await _get_embedding(texto)
    if not emb:
        return  # API indisponível — não salva embedding (hash cache ainda funciona)
    try:
        # ── Limite por slug: máx 500 entradas para evitar crescimento ilimitado ──
        _total_slug = 0
        _cur_lim = 0
        while True:
            _cur_lim, _kk_lim = await redis_client.scan(
                _cur_lim, match=f"semcache:{slug}:*", count=100
            )
            _total_slug += len(_kk_lim)
            if _cur_lim == 0 or _total_slug >= 500:
                break
        if _total_slug >= 500:
            logger.debug(f"semcache: limite 500 atingido para slug={slug}, entrada descartada")
            return

        chave = f"semcache:{slug}:{hashlib.md5(texto.encode()).hexdigest()}"
        await redis_client.hset(chave, mapping={
            "embedding": json.dumps(emb),
            "resposta":  json.dumps(dados),
            "texto":     texto[:200],
        })
        await redis_client.expire(chave, ttl)
    except Exception as e:
        logger.warning(f"Erro ao salvar cache semântico: {e}")


def detectar_intencao(texto: str) -> Optional[str]:
    """Detecta a intenção principal da pergunta do usuário usando palavras-chave e fuzzy matching"""
    if not texto:
        return None

    texto_norm = normalizar(texto)
    melhor_intencao = None
    melhor_score = 0

    for intent, palavras in INTENCOES.items():
        for palavra in palavras:
            if palavra in texto_norm:
                return intent
            score = fuzz.partial_ratio(palavra, texto_norm)
            if score > melhor_score and score > 80:
                melhor_score = score
                melhor_intencao = intent

    return melhor_intencao


async def coletar_mensagens_buffer(conversation_id: int) -> List[str]:
    """Coleta mensagens do buffer e limpa a fila da conversa.

    Faz uma coalescência curta para agrupar rajadas (2-4 mensagens seguidas)
    em uma única resposta, reduzindo respostas duplicadas e melhorando fluidez.
    """
    chave_buffet = f"buffet:{conversation_id}"

    mensagens_acumuladas: List[str] = []
    deadline = time.time() + 1.6  # janela curta para juntar burst sem aumentar muito latência

    while True:
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.lrange(chave_buffet, 0, -1)
            pipe.delete(chave_buffet)
            resultado = await pipe.execute()
        lote = resultado[0] or []
        if lote:
            mensagens_acumuladas.extend(lote)
            if len(mensagens_acumuladas) >= 8 or time.time() >= deadline:
                break
            await asyncio.sleep(0.25)
            continue
        if mensagens_acumuladas or time.time() >= deadline:
            break
        await asyncio.sleep(0.15)

    logger.info(f"📦 Buffer tem {len(mensagens_acumuladas)} mensagens para conv {conversation_id}")
    return mensagens_acumuladas


async def aguardar_escolha_unidade_ou_reencaminhar(conversation_id: int, mensagens_acumuladas: List[str]) -> bool:
    """Reencaminha buffer quando conversa ainda está aguardando escolha de unidade."""
    if not await redis_client.exists(f"esperando_unidade:{conversation_id}"):
        return False

    logger.info(f"⏳ Conv {conversation_id} aguardando escolha de unidade — IA pausada")
    for m_json in mensagens_acumuladas:
        await redis_client.rpush(f"buffet:{conversation_id}", m_json)
    await redis_client.expire(f"buffet:{conversation_id}", 300)
    return True


async def processar_anexos_mensagens(mensagens_acumuladas: List[str]) -> Dict[str, Any]:
    """Extrai textos, transcrições e imagens a partir das mensagens acumuladas."""
    textos, tasks_audio, imagens_urls = [], [], []
    for m_json in mensagens_acumuladas:
        m = json.loads(m_json)
        if m.get("text"):
            textos.append(m["text"])
        for f in m.get("files", []):
            if f["type"] == "audio":
                tasks_audio.append(transcrever_audio(f["url"]))
            elif f["type"] == "image":
                imagens_urls.append(f["url"])

    transcricoes = await asyncio.gather(*tasks_audio)

    mensagens_lista = []
    for i, txt in enumerate(textos, 1):
        mensagens_lista.append(f"{i}. {txt}")
    for i, transc in enumerate(transcricoes, len(textos) + 1):
        mensagens_lista.append(f"{i}. [Áudio] {transc}")

    return {
        "textos": textos,
        "transcricoes": transcricoes,
        "imagens_urls": imagens_urls,
        "mensagens_formatadas": "\n".join(mensagens_lista) if mensagens_lista else "",
    }


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
                conversation_id, "mudanca_unidade", f"Contexto alterado para {slug}", score_incremento=1
            )

    return {"slug": slug, "mudou_unidade": mudou_unidade, "primeira_mensagem": primeira_mensagem}


async def persistir_mensagens_usuario(conversation_id: int, textos: List[str], transcricoes: List[str]):
    """Persiste histórico de mensagens do usuário (texto e áudio transcrito)."""
    for txt in textos:
        await bd_salvar_mensagem_local(conversation_id, "user", txt)
    for transc in transcricoes:
        await bd_salvar_mensagem_local(conversation_id, "user", f"[Áudio] {transc}")


# --- UTILITÁRIOS DE JSON ---

def extrair_json(texto: str) -> str:
    texto = texto.strip()
    inicio = texto.find('{')
    fim = texto.rfind('}')
    if inicio != -1 and fim != -1 and fim > inicio:
        return texto[inicio:fim + 1]
    return texto


def corrigir_json(texto: str) -> str:
    texto = texto.strip()
    texto = re.sub(r'^```(?:json)?\s*', '', texto)
    texto = re.sub(r'\s*```$', '', texto)
    texto = extrair_json(texto)
    return texto


# --- PROCESSAMENTO IA E ÁUDIO ---

async def transcrever_audio(url: str):
    if not cliente_whisper:
        return "[Áudio recebido, mas Whisper não configurado]"
    async with whisper_semaphore:
        try:
            resp = await baixar_midia_com_retry(url, timeout=15.0)
            audio_file = io.BytesIO(resp.content)
            audio_file.name = "audio.ogg"
            transcription = await cliente_whisper.audio.transcriptions.create(
                model="whisper-1", file=audio_file
            )
            return transcription.text
        except httpx.TimeoutException as e:
            logger.error(f"⏱️ Timeout ao baixar áudio: {e}")
            if PROMETHEUS_OK:
                METRIC_ERROS_TOTAL.labels(tipo="whisper_timeout").inc()
            return "[Erro ao baixar áudio: timeout]"
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ HTTP {e.response.status_code} ao baixar áudio: {e}")
            if PROMETHEUS_OK:
                METRIC_ERROS_TOTAL.labels(tipo="whisper_http").inc()
            return "[Erro ao baixar áudio]"
        except Exception as e:
            logger.error(f"Erro Whisper: {e}")
            if PROMETHEUS_OK:
                METRIC_ERROS_TOTAL.labels(tipo="whisper_unknown").inc()
            return "[Erro ao transcrever áudio]"


@retry(
    wait=wait_exponential(multiplier=0.5, min=1, max=4),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError)),
    reraise=True,
)
async def baixar_midia_com_retry(url: str, timeout: float = 15.0, headers: Optional[Dict[str, str]] = None) -> httpx.Response:
    """Baixa mídia com retry para mitigar falhas transitórias de rede/provedor."""
    resp = await _chatwoot_module.http_client.get(
        url,
        headers=headers,
        follow_redirects=True,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp



