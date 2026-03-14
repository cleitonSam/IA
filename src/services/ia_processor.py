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


def responder_telefone(unidade: dict) -> str:
    nome = unidade.get("nome") or "da unidade"
    telefone = extrair_telefone_unidade(unidade)
    if not telefone:
        return (
            f"📞 No momento não encontrei o contato da unidade *{nome}*.\n\n"
            "Se quiser, posso te passar o endereço."
        )
    return (
        f"📞 O contato da unidade *{nome}* é:\n{telefone}\n\n"
        "Se quiser, também posso te passar o endereço ou horário."
    )


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

    return {"tipo": "llm", "resposta": None, "slug": slug, "intencao": "llm"}


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


async def processar_ia_e_responder(
    account_id: int,
    conversation_id: int,
    contact_id: int,
    slug: str,
    nome_cliente: str,
    lock_val: str,
    empresa_id: int,
    integracao_chatwoot: dict
):
    chave_lock = f"lock:{conversation_id}"
    chave_buffet = f"buffet:{conversation_id}"
    watchdog = asyncio.create_task(renovar_lock(chave_lock, lock_val))

    try:
        # ⏱️ Aguarda curto período para acumular mensagens sem sacrificar latência
        await asyncio.sleep(0.8)

        mensagens_acumuladas = await coletar_mensagens_buffer(conversation_id)
        if not mensagens_acumuladas:
            return

        if await aguardar_escolha_unidade_ou_reencaminhar(conversation_id, mensagens_acumuladas):
            return

        anexos = await processar_anexos_mensagens(mensagens_acumuladas)
        textos = anexos["textos"]
        transcricoes = anexos["transcricoes"]
        imagens_urls = anexos["imagens_urls"]
        mensagens_formatadas = anexos["mensagens_formatadas"]

        # ── Anti-duplicata: bloqueia reprocessamento do mesmo conteúdo ──────────
        # O drain loop pode recolocar mensagens no buffer após o processamento.
        # Se o hash das mensagens atuais é igual ao que foi respondido nos últimos
        # 2 minutos, descarta silenciosamente — a resposta já foi enviada.
        _hash_msgs = hashlib.md5(mensagens_formatadas.encode()).hexdigest()
        _ultima_resp_key = f"last_ai_msg:{conversation_id}"
        _ultima_resp_hash = await redis_client.get(_ultima_resp_key)
        if _ultima_resp_hash and _ultima_resp_hash == _hash_msgs:
            logger.info(f"⏭️ Anti-duplicata: mensagens já respondidas, descartando conv {conversation_id}")
            return

        contexto = await resolver_contexto_atendimento(
            conversation_id=conversation_id,
            textos=textos,
            transcricoes=transcricoes,
            slug=slug,
            empresa_id=empresa_id,
        )
        slug = contexto["slug"]
        mudou_unidade = contexto["mudou_unidade"]
        primeira_mensagem = contexto["primeira_mensagem"]

        await persistir_mensagens_usuario(conversation_id, textos, transcricoes)

        unidade = await carregar_unidade(slug, empresa_id) or {}
        pers = await carregar_personalidade(empresa_id) or {}
        nome_ia = pers.get('nome_ia') or 'Assistente Virtual'

        estado_raw = await redis_client.get(f"estado:{conversation_id}")
        estado_atual = descomprimir_texto(estado_raw) or "neutro"

        texto_norm_fast = normalizar(primeira_mensagem or "")
        resposta_texto = ""
        novo_estado = estado_atual
        fast_reply = None          # str  — mensagem única (resposta fixa, sem LLM)
        fast_reply_lista = None   # List[str] — múltiplas mensagens (ex: planos)
        contexto_precarregado = ""  # Dados buscados do BD — LLM gera a resposta humanizada
        intencao_motor = None
        _resposta_foi_truncada = False

        # Fast-path desativado: sempre seguir pelo fluxo FAQ + IA.
        texto_cliente_unificado = " ".join([t for t in (textos + transcricoes) if t]).strip()
        if texto_cliente_unificado and not imagens_urls:
            intencao_motor = detectar_intencao(texto_cliente_unificado)

        # Campos da unidade
        end_banco = extrair_endereco_unidade(unidade)
        hor_banco = unidade.get('horarios')
        link_mat = unidade.get('link_matricula') or unidade.get('site') or 'nosso site oficial'
        tel_banco = extrair_telefone_unidade(unidade)

        # Planos ativos
        planos_ativos = await buscar_planos_ativos(empresa_id, unidade.get('id'), force_sync=True)
        if planos_ativos:
            link_plano = planos_ativos[0].get('link_venda') if planos_ativos else link_mat
        else:
            link_plano = link_mat

        # Fast-path desativado conforme regra de negócio.


        # Cache: usa chave por intenção APENAS para intenções factuais/estáveis.
        # Nunca usar cache por intenção para "llm"/"saudacao", senão uma resposta
        # genérica (ex: boas-vindas) pode ser repetida para perguntas diferentes.
        intencao = intencao_motor or (detectar_intencao(primeira_mensagem) if primeira_mensagem else None)
        _texto_cliente_norm = normalizar(texto_cliente_unificado or "")
        _intencao_compra = bool(re.search(
            r"(vou querer|quero (esse|este|fechar|contratar|assinar)|manda(r)? (o )?link|pode mandar o link|poderia mandar o link|tenho interesse|gostei desse preco|gostei desse preço|vamos fechar|quero me matricular)",
            _texto_cliente_norm,
        ))
        _quer_todos_planos = bool(re.search(
            r"(fora o plano|alem do prime|além do prime|outro plano|outros planos|quais planos|todos os planos|opcoes de plano|opções de plano|saber dos planos|quero ver planos|me fala dos planos)",
            _texto_cliente_norm,
        ))
        if planos_ativos and intencao in {"planos", "preco"}:
            # Sempre envia planos em blocos estruturados — nunca pelo LLM.
            # O LLM trunca respostas longas com múltiplos planos.
            _planos_filtrados = filtrar_planos_por_contexto(texto_cliente_unificado, planos_ativos)
            fast_reply_lista = formatar_planos_bonito(_planos_filtrados, destacar_melhor_preco=True)
            logger.info(f"⚡ Planos: envio em blocos ({len(_planos_filtrados)} planos)")

        # Pré-carrega horário com status aberta/fechada quando intenção é horário
        if intencao == "horario" and hor_banco:
            horarios_formatados = formatar_horarios_funcionamento(hor_banco)
            _aberta, _hor_hoje = esta_aberta_agora(hor_banco)
            _nome_unid = unidade.get('nome') or 'da unidade'
            if _aberta is True:
                _status_ctx = f"✅ A unidade está ABERTA agora. Horário de hoje: {_hor_hoje}"
            elif _aberta is False:
                _status_ctx = f"❌ A unidade está FECHADA no momento. Horário de hoje: {_hor_hoje}"
            else:
                _status_ctx = "Status de funcionamento não determinado."
            contexto_precarregado = (
                f"Horários de funcionamento — {_nome_unid}:\n{horarios_formatados}\n\n{_status_ctx}"
            )
            logger.info(f"📋 Horário + status pré-carregado: {_status_ctx}")

        _intencoes_cacheaveis = {
            "horario", "endereco"
        }
        _usa_cache_por_intencao = bool(intencao and intencao in _intencoes_cacheaveis)

        if _usa_cache_por_intencao:
            chave_cache_ia = f"cache:intent:{slug}:{intencao}"
        else:
            hash_pergunta = hashlib.md5(texto_norm_fast.encode('utf-8')).hexdigest()
            chave_cache_ia = f"cache:ia:{slug}:{hash_pergunta}"

        # Quando há dados pré-carregados do BD, bypassa cache completamente:
        # os dados são ao vivo (endereço/horário podem ter mudado) e o LLM precisa
        # gerar uma resposta humanizada nova — não uma resposta cacheada de outra conversa.
        if contexto_precarregado:
            resposta_cacheada = None
        else:
            resposta_cacheada = await redis_client.get(chave_cache_ia)

        # Cache semântico (embedding) — consultado apenas se não houver cache exato nem contexto live
        _cache_sem = None
        if USAR_CACHE_SEMANTICO and intencao == "llm" and not resposta_cacheada and not fast_reply and not contexto_precarregado and not imagens_urls and not mudou_unidade and primeira_mensagem:
            _cache_sem = await buscar_cache_semantico(primeira_mensagem, slug)

        if fast_reply:
            logger.info("⚡ Fast-Path Ativado! Respondendo sem IA.")
            resposta_texto = fast_reply
            novo_estado = estado_atual

        elif resposta_cacheada and not imagens_urls and not mudou_unidade:
            logger.info("🧠 Cache Hash HIT! Respondendo direto do Redis.")
            dados_cache = json.loads(resposta_cacheada)
            resposta_texto = dados_cache["resposta"]
            novo_estado = dados_cache["estado"]

            # Proteção anti-loop: se a resposta cacheada parece saudação, só use
            # quando a mensagem atual também for saudação.
            _msg_eh_saudacao = eh_saudacao(primeira_mensagem or "")
            _resp_norm = normalizar(resposta_texto or "")
            _resp_parece_saudacao = any(
                s in _resp_norm for s in [
                    "como posso te ajudar", "bem-vindo", "eu sou o", "eu sou a"
                ]
            )
            if _resp_parece_saudacao and not _msg_eh_saudacao:
                logger.info("⏭️ Cache ignorado: resposta de saudação para pergunta não-saudação")
                resposta_texto = ""

        elif _cache_sem and not imagens_urls and not mudou_unidade:
            logger.info("🧬 Cache Semântico HIT! Respondendo por similaridade.")
            resposta_texto = _cache_sem["resposta"]
            novo_estado = _cache_sem.get("estado", estado_atual)

        else:
            # --- FLUXO IA ---
            faq = await carregar_faq_unidade(slug, empresa_id) or ""
            historico = await bd_obter_historico_local(conversation_id, limit=12) or "Sem histórico."

            todas_unidades = await listar_unidades_ativas(empresa_id)
            lista_unidades_nomes = ", ".join([u["nome"] for u in todas_unidades])

            nome_empresa = unidade.get('nome_empresa') or 'Nossa Empresa'
            nome_unidade = unidade.get('nome') or 'Unidade Matriz'

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

            # Detalhes de planos para o prompt (texto simples, sem markdown)
            planos_detalhados = formatar_planos_para_prompt(planos_ativos) if planos_ativos else "não informado"
            modalidades_prompt = ", ".join(normalizar_lista_campo(unidade.get("modalidades"))) or "não informado"
            pagamentos_prompt = ", ".join(normalizar_lista_campo(unidade.get("formas_pagamento"))) or "não informado"
            convenios_prompt = ", ".join(normalizar_lista_campo(unidade.get("convenios"))) or "não informado"

            dados_unidade = f"""
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

            # ── Campos conhecidos da personalidade_ia ──────────────────────────
            tom_voz          = pers.get('tom_voz') or 'Profissional, claro e prestativo'
            estilo           = pers.get('estilo_comunicacao') or ''
            saudacao         = pers.get('saudacao_personalizada') or f"Olá! Sou {nome_ia}, como posso ajudar?"
            instrucoes_base  = pers.get('instrucoes_base') or "Atenda o cliente de forma educada."
            regras_atend     = pers.get('regras_atendimento') or "Seja breve e objetivo."

            # ── Campos extras da personalidade_ia (consumidos dinamicamente) ──
            # Qualquer coluna presente na tabela mas não listada acima é injetada
            # automaticamente no prompt — sem hardcode, sem brecha para falha.
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
                'restricoes':         'RESTRIÇÕES',
                'linguagem_proibida':  'LINGUAGEM PROIBIDA',
                'contexto_empresa':    'CONTEXTO DA EMPRESA',
                'contexto_extra':      'CONTEXTO EXTRA',
                'abordagem_proativa':  'ABORDAGEM PROATIVA',
                'idioma':              'IDIOMA',
                'horario_ativo_inicio':'HORÁRIO ATIVO INÍCIO',
                'horario_ativo_fim':   'HORÁRIO ATIVO FIM',
                'exemplos':            'EXEMPLOS DE ATENDIMENTO',
                'palavras_proibidas':  'PALAVRAS PROIBIDAS',
                'despedida_personalizada': 'DESPEDIDA PERSONALIZADA',
            }

            _extras_prompt = ""
            for _campo, _valor in pers.items():
                if _campo in _CAMPOS_FIXOS:
                    continue
                if not _valor:
                    continue
                # Converte tipos complexos (dict/list) para string legível
                if isinstance(_valor, (dict, list)):
                    _valor_str = json.dumps(_valor, ensure_ascii=False, indent=2)
                else:
                    _valor_str = str(_valor).strip()
                if not _valor_str or _valor_str in ('null', 'None', '{}', '[]', ''):
                    continue
                _label = _LABEL_MAP.get(_campo, _campo.upper().replace('_', ' '))
                _extras_prompt += f"\n{_label}\n{_valor_str}\n"

            aviso_mudanca = (
                f"\n[AVISO]: O cliente perguntou sobre a unidade {nome_unidade}. "
                "Use os dados abaixo para responder."
            ) if mudou_unidade else ""

            contexto_precarregado_bloco = ""
            if contexto_precarregado:
                contexto_precarregado_bloco = f"""
DADOS JÁ CARREGADOS DO BANCO — USE EXATAMENTE ESSES, não invente nem altere:
{contexto_precarregado}

REGRA OBRIGATÓRIA: O cliente JÁ pediu esses dados — entregue-os DIRETAMENTE na resposta.
NUNCA pergunte "Quer que eu te passe?", "Posso te enviar?" ou qualquer variação.
NUNCA ofereça ajuda de navegação como "posso te ensinar a chegar", "te passo o caminho",
"precisa de indicações para chegar" ou similares — apenas informe o endereço/dado solicitado.
"""

            prompt_sistema = f"""
IDIOMA OBRIGATÓRIO: Responda SEMPRE em português do Brasil.
NUNCA use inglês ou qualquer outro idioma — nem uma palavra, nem no meio de frases.
NUNCA avalie respostas com frases como "is perfect", "that's great", "perfect answer" ou similares.
Você é um atendente — apenas responda o cliente diretamente.

Seu nome é {nome_ia}. Você é atendente da academia {nome_empresa}, unidade {nome_unidade}.

PERSONALIDADE
{pers.get('personalidade', 'Atendente prestativo, simpático e focado em ajudar.')}

ESTILO DE COMUNICAÇÃO
Tom de voz: {tom_voz}
Estilo: {estilo}

SAUDAÇÃO PADRÃO
{saudacao}

INSTRUÇÕES BASE
{instrucoes_base}

REGRAS DE ATENDIMENTO
{regras_atend}
{_extras_prompt}
INFORMAÇÕES DA UNIDADE
{dados_unidade}

UNIDADES DA REDE {nome_empresa.upper()}:
{lista_unidades_nomes}
(Se o cliente perguntar quais unidades existem, liste esses nomes. Para detalhes de endereço/horário de outra unidade, pergunte qual delas ele prefere para você buscar as informações.)

FAQ — RESPOSTAS PRONTAS (USE SEMPRE QUE A PERGUNTA DO CLIENTE SE ENCAIXAR):
{faq}

HISTÓRICO DA CONVERSA
{historico}

REGRAS CRÍTICAS — ANTI-ALUCINAÇÃO (OBRIGATÓRIO):
- Use EXCLUSIVAMENTE as informações presentes em "INFORMAÇÕES DA UNIDADE" acima.
- Se um campo estiver como "não informado", diga que não tem essa informação agora.
- NUNCA invente endereços, telefones, horários ou qualquer dado não informado.
- NUNCA diga que a empresa tem "apenas uma unidade" — você não tem essa informação completa.
- Se a pergunta do cliente bater com algum item do FAQ acima, USE aquela resposta como base.

FLUXO DE VENDEDOR REAL (OBRIGATÓRIO):
Você é um VENDEDOR, não um robô de FAQ. Siga este fluxo:
1. Responda a pergunta do cliente de forma direta e curta
2. Depois da resposta, faça UMA pergunta de descoberta que avança a conversa
Exemplos:
  Cliente: "Tem diária?" → "Temos sim! A diária custa R$40 💪 Você pretende treinar só hoje ou está pensando em começar academia?"
  Cliente: "Qual o horário?" → "Nosso horário é seg-sex 06h às 23h 😊 Você já treina ou está começando agora?"
  Cliente: "Quanto custa?" → "Temos planos a partir de R$X! Qual seu objetivo principal — musculação, cardio, ou os dois?"
REGRAS do fluxo:
- Resposta + pergunta na MESMA mensagem, sempre
- A pergunta deve descobrir algo sobre o cliente (objetivo, frequência, localização)
- NUNCA adicione dados que o cliente NÃO pediu (ex: não jogue horários se pediu preço)
- Se o cliente já respondeu uma descoberta, avance para a próxima etapa (mostrar plano, agendar visita)

REGRAS DE TOM (OBRIGATÓRIO):
- NUNCA comece resposta com "Olá" se já houve troca de mensagens — vá direto ao ponto
- NUNCA diga "Olá! Nossos horários são:" — diga "Nosso horário é:"
- Em saudações iniciais, NÃO mencione o nome da unidade — apenas se apresente
- Quando perguntarem seu nome, responda APENAS seu nome
- Conversa casual ("tudo bem?", "e aí?"): responda naturalmente, NÃO empurre planos

FORMATAÇÃO DA RESPOSTA (OBRIGATÓRIO):
Você escreve para WhatsApp. Toda mensagem deve ser LIMPA, ORGANIZADA e FÁCIL de ler.

ESTRUTURA de cada resposta:
1. Frase de abertura curta (resposta direta à pergunta)
2. Dados/informações (se houver) — organizados com quebra de linha
3. Pergunta de descoberta (para avançar a conversa)

REGRAS DE FORMATO:
- Use *texto* para destaque (bold do WhatsApp) — NUNCA use ** ou ##
- Listas com • no início, cada item em linha separada
- Separe blocos com UMA linha em branco
- Links: sempre URL plana (ex: https://exemplo.com)
- Emojis: máximo 2-3 por mensagem, nos pontos certos (😊 💪 ✅)
- NUNCA use markdown: sem **, sem ##, sem ```código```, sem [texto](url)

TAMANHO DA RESPOSTA (CRÍTICO — RESPEITE SEMPRE):
- Tamanho ideal: 2-4 linhas. Máximo absoluto: 8 linhas
- Se a resposta ficar maior que 8 linhas, RESUMA. Nunca liste todos os dias da semana um por um.
- Horários: agrupe em UMA linha. Ex: "Seg-Sex: 06h-23h • Sáb: 09h-17h • Dom: 09h-13h"
- NUNCA liste dia por dia (Segunda: ..., Terça: ..., Quarta: ...) — SEMPRE agrupe dias com mesmo horário
- Planos: mostre no máximo 2-3 opções resumidas, não liste todos os detalhes
- Se o cliente pedir detalhes completos, AINDA resuma — ofereça enviar por link ou foto
- REGRA DE OURO: é melhor uma resposta CURTA e COMPLETA do que uma resposta LONGA e CORTADA

REGRAS DE TOM:
- Fale como pessoa real — NUNCA mencione ser IA, robô ou assistente virtual
- NUNCA se apresente novamente se já houver histórico
- NUNCA repita o nome do cliente na mesma resposta — use no máximo 1 vez, na saudação
- NUNCA comece com "Olá" se a conversa já começou — vá direto ao ponto

EXEMPLO DE MENSAGEM BEM FORMATADA:
"Temos sim! A diária custa *R$40* 💪

Se quiser, pode vir treinar hoje mesmo — estamos abertos até as 23h.

Você pretende treinar só hoje ou está pensando em começar academia?"
{aviso_mudanca}

DADOS DO ATENDIMENTO:
Cliente: {nome_cliente}
Estado emocional anterior: {estado_atual}
{contexto_precarregado_bloco}
MENSAGENS DO CLIENTE (responda a TODAS):
{mensagens_formatadas}

RESPONDA com a mensagem diretamente — texto puro, sem JSON, sem ```código```, sem prefixos.
"""

            conteudo_usuario = []
            for img_url in imagens_urls:
                try:
                    resp = await baixar_midia_com_retry(
                        img_url,
                        timeout=12.0,
                        headers={"api_access_token": integracao_chatwoot['token']},
                    )
                    img_b64 = base64.b64encode(resp.content).decode("utf-8")
                    conteudo_usuario.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                    })
                except Exception as e:
                    logger.error(f"Erro ao baixar imagem: {e}")

            modelo_escolhido = pers.get("modelo_preferido") or (
                "google/gemini-2.5-flash" if imagens_urls else "google/gemini-2.5-flash-lite"
            )
            temperature = float(pers.get("temperatura") or 0.7)
            max_tokens_llm = int(pers.get("max_tokens") or 8000)
            # Mínimo alto para nunca truncar respostas com múltiplos planos ou detalhes
            max_tokens_llm = max(max_tokens_llm, 8000)

            # ── Guard de cota do provedor LLM (cooldown) ─────────────────────
            llm_provider_pause_key = f"llm:provider_pause:{empresa_id}"
            if await redis_client.get(llm_provider_pause_key) == "1":
                _nome_cb = nome_cliente.split()[0].capitalize() if nome_cliente else "você"
                resposta_texto = (
                    f"{_nome_cb}, agora estamos com alto volume no atendimento automático 😕\n\n"
                    "Se quiser, me manda sua dúvida em uma frase curta que priorizo aqui pra você."
                )
                novo_estado = estado_atual
                goto_send = True
            else:
                goto_send = False

            # ── Circuit Breaker check ─────────────────────────────────────────
            if not goto_send:
                _cb_allowed = await cb_llm.is_allowed()
            else:
                _cb_allowed = True

            if not goto_send and not _cb_allowed:
                logger.warning(f"🔴 CircuitBreaker OPEN — usando resposta padrão para conv {conversation_id}")
                # Resposta de fallback quando LLM está indisponível
                _nome_cb = nome_cliente.split()[0].capitalize() if nome_cliente else "você"
                resposta_texto = (
                    f"Olá, {_nome_cb}! 😊 Estou com uma lentidão no momento.\n\n"
                    "Pode me repetir sua dúvida em instantes? Já vou te atender! 💪"
                )
                novo_estado = estado_atual
                # Pula o bloco IA e vai direto para envio
                goto_send = True
            if not goto_send:
                if not cliente_ia:
                    resposta_texto = "Estou temporariamente sem conexão com a IA. Pode tentar novamente em instantes? 😊"
                    novo_estado = estado_atual
                    goto_send = True

            if not goto_send:
                # ── Chamada ao LLM com timeout global + circuit breaker ───────────
                start_time = time.time()

                # Monta conteúdo do role "user":
                # - Com imagem: lista multimodal [imagem(s) + texto da pergunta]
                # - Sem imagem: string direta com as mensagens
                # Sem isso o modelo recebe a imagem mas não a pergunta real do cliente.
                if conteudo_usuario:
                    conteudo_usuario.append({"type": "text", "text": mensagens_formatadas})
                    user_content = conteudo_usuario
                else:
                    user_content = mensagens_formatadas

                async def _chamar_llm(model_id: str, extra_timeout: int = 25):
                    return await asyncio.wait_for(
                        cliente_ia.chat.completions.create(
                            model=model_id,
                            messages=[
                                {"role": "system", "content": prompt_sistema},
                                {"role": "user", "content": user_content}
                            ],
                            temperature=temperature,
                            max_tokens=max_tokens_llm,
                        ),
                        timeout=extra_timeout
                    )

                _resposta_foi_truncada = False
                async with llm_semaphore:
                    try:
                        response = await _chamar_llm(modelo_escolhido, extra_timeout=25)
                        resposta_bruta = response.choices[0].message.content
                        # Detecta resposta truncada por max_tokens
                        _finish = getattr(response.choices[0], 'finish_reason', None)
                        if _finish == "length" and resposta_bruta:
                            logger.warning(f"⚠️ Resposta truncada (finish_reason=length) conv {conversation_id}")
                            _resposta_foi_truncada = True
                            # Corta na última frase completa para não enviar frase pela metade
                            for _sep in ['. ', '! ', '? ', '\n']:
                                _pos = resposta_bruta.rfind(_sep)
                                if _pos > len(resposta_bruta) * 0.3:
                                    resposta_bruta = resposta_bruta[:_pos + 1]
                                    break
                        await cb_llm.record_success()

                    except asyncio.TimeoutError:
                        logger.warning(f"⏱️ Timeout LLM (25s) — tentando fallback. Conv {conversation_id}")
                        await cb_llm.record_failure()
                        if PROMETHEUS_OK:
                            METRIC_ERROS_TOTAL.labels(tipo="llm_timeout").inc()
                        try:
                            modelo_fallback = "google/gemini-2.5-flash" if imagens_urls else "google/gemini-2.5-flash-lite"
                            response = await _chamar_llm(modelo_fallback, extra_timeout=20)
                            resposta_bruta = response.choices[0].message.content
                            await cb_llm.record_success()
                        except asyncio.TimeoutError:
                            logger.error(f"❌ Timeout no fallback também. Conv {conversation_id}")
                            await cb_llm.record_failure()
                            resposta_bruta = json.dumps({
                                "resposta": "Estou com uma lentidão agora 😕 Pode tentar novamente em instantes?",
                                "estado": estado_atual
                            })
                        except Exception as e2:
                            if is_provider_unavailable_error(e2):
                                logger.warning("⚠️ Fallback de IA indisponível temporariamente")
                                await redis_client.setex(llm_provider_pause_key, 300, "1")
                            else:
                                logger.error("❌ Erro no fallback")
                            await cb_llm.record_failure()
                            resposta_bruta = json.dumps({
                                "resposta": "Estamos com alto volume de atendimentos agora 😕 Pode tentar novamente em instantes?",
                                "estado": estado_atual
                            })

                    except Exception as e:
                        erro_provedor = is_provider_unavailable_error(e)
                        if erro_provedor:
                            logger.warning("⚠️ IA indisponível temporariamente (OpenRouter)")
                            await redis_client.setex(llm_provider_pause_key, 300, "1")
                        elif is_openrouter_auth_error(e):
                            logger.warning("⚠️ Falha de autenticação OpenRouter (verifique OPENROUTER_API_KEY)")
                            await redis_client.setex(llm_provider_pause_key, 600, "1")
                        else:
                            logger.warning("⚠️ Erro LLM primário — tentando fallback")
                        await cb_llm.record_failure()
                        if PROMETHEUS_OK:
                            METRIC_ERROS_TOTAL.labels(tipo="llm_fallback").inc()

                        # Em indisponibilidade do provedor, evita nova tentativa imediata no fallback
                        # para reduzir ruído de log e latência.
                        if erro_provedor:
                            await redis_client.setex(llm_provider_pause_key, 300, "1")
                            resposta_bruta = json.dumps({
                                "resposta": "Estamos com alto volume de atendimentos agora 😕 Pode tentar novamente em instantes?",
                                "estado": estado_atual
                            })
                        else:
                            try:
                                modelo_fallback = "google/gemini-2.5-flash" if imagens_urls else "google/gemini-2.5-flash-lite"
                                response = await _chamar_llm(modelo_fallback, extra_timeout=20)
                                resposta_bruta = response.choices[0].message.content
                                await cb_llm.record_success()
                            except Exception as e2:
                                if is_provider_unavailable_error(e2):
                                    logger.warning("⚠️ Fallback de IA indisponível temporariamente")
                                    await redis_client.setex(llm_provider_pause_key, 300, "1")
                                else:
                                    logger.error("❌ Fallback também falhou")
                                await cb_llm.record_failure()
                                resposta_bruta = json.dumps({
                                    "resposta": "Estamos com alto volume de atendimentos agora 😕 Pode tentar novamente em instantes?",
                                    "estado": estado_atual
                                })

                _latencia = time.time() - start_time
                logger.info(f"⏱️ LLM Latency: {_latencia:.2f}s")
                if PROMETHEUS_OK:
                    METRIC_IA_LATENCY.observe(_latencia)

            if not goto_send:
                # ── Garante que NENHUMA resposta saia com frase cortada ──────────
                def _garantir_frase_completa(txt: str) -> str:
                    """Remove frase incompleta no final do texto.
                    Procura o último terminador de frase (. ! ? ou quebra de linha)
                    e descarta tudo depois, evitando enviar 'horários super est'."""
                    if not txt:
                        return txt
                    txt = txt.strip()
                    # Se termina com pontuação ou emoji, está OK
                    if txt[-1] in '.!?😊💪✅🏋🎯':
                        return txt
                    # Procura último ponto de corte seguro
                    for _sep in ['. ', '! ', '? ', '!\n', '?\n', '.\n', '\n']:
                        _pos = txt.rfind(_sep)
                        if _pos > len(txt) * 0.3:  # só corta se mantém >30% do texto
                            return txt[:_pos + 1].strip()
                    # Sem ponto de corte — retorna tudo (melhor inteiro que vazio)
                    return txt

                # ── A IA agora responde texto puro — sem JSON ──────────────────
                resposta_texto = limpar_markdown(resposta_bruta.strip())

                # Tenta extrair JSON legado caso o modelo ainda retorne JSON (backward compat)
                if resposta_texto.startswith('{'):
                    try:
                        _dados_legado = json.loads(corrigir_json(resposta_texto))
                        resposta_texto = limpar_markdown(_dados_legado.get("resposta", resposta_texto))
                        novo_estado = _dados_legado.get("estado", estado_atual).strip().lower()
                    except (json.JSONDecodeError, ValueError):
                        pass  # Não é JSON, usa como texto mesmo

                # Inferir estado emocional a partir das palavras-chave da resposta
                _resp_norm = normalizar(resposta_texto)
                if any(w in _resp_norm for w in ("matricula", "matricular", "assinar", "plano", "checkout", "comecar agora")):
                    novo_estado = "conversao"
                elif any(w in _resp_norm for w in ("parabens", "que otimo", "incrivel", "adorei", "perfeito")):
                    novo_estado = "animado"
                elif any(w in _resp_norm for w in ("entendo", "compreendo", "preocupo", "problema", "dificuldade")):
                    novo_estado = "hesitante"
                elif any(w in _resp_norm for w in ("interesse", "quero saber", "me conta", "curioso")):
                    novo_estado = "interessado"
                else:
                    novo_estado = estado_atual

                if not resposta_texto:
                    resposta_texto = "Desculpe, pode repetir sua pergunta? 😊"
                    novo_estado = estado_atual

                # Pós-processamento de conversão: se o cliente já sinalizou compra,
                # garante envio do link de matrícula e CTA de outros planos na mesma resposta.
                if _intencao_compra and link_plano:
                    _resp_norm_compra = normalizar(resposta_texto or "")
                    _tem_link = ("http://" in (resposta_texto or "")) or ("https://" in (resposta_texto or ""))
                    if not _tem_link:
                        _base = resposta_texto.strip() if resposta_texto and resposta_texto.strip() else "Perfeito! Vamos fechar agora 🚀"
                        resposta_texto = (
                            f"{_base}\n\n"
                            f"🔗 Para garantir sua matrícula agora: {link_plano}\n\n"
                            "Se quiser, também te mostro *outros planos* para você comparar rapidinho."
                        )
                    elif "outros planos" not in _resp_norm_compra:
                        resposta_texto = (
                            f"{resposta_texto.rstrip()}\n\n"
                            "Se quiser, também te mostro *outros planos* para você comparar rapidinho."
                        )
                    novo_estado = "conversao"

                if not imagens_urls and resposta_texto:
                    _cache_payload = json.dumps({"resposta": resposta_texto, "estado": novo_estado})
                    # Não persiste cache para saudações curtas para evitar repetição
                    # em consultas futuras de conteúdo diferente.
                    _mensagem_eh_saudacao = eh_saudacao(primeira_mensagem or "")
                    if not _mensagem_eh_saudacao:
                        await redis_client.setex(chave_cache_ia, 600, _cache_payload)

                    if USAR_CACHE_SEMANTICO and primeira_mensagem and not _mensagem_eh_saudacao:
                        await salvar_cache_semantico(
                            primeira_mensagem, slug,
                            {"resposta": resposta_texto, "estado": novo_estado},
                            ttl=3600
                        )

                if link_plano in resposta_texto or "matricular" in resposta_texto.lower():
                    await bd_registrar_evento_funil(
                        conversation_id, "link_matricula_enviado", "Link enviado via IA", score_incremento=2
                    )
                if tel_banco and tel_banco in resposta_texto:
                    await bd_registrar_evento_funil(
                        conversation_id, "solicitacao_telefone", "IA forneceu telefone", score_incremento=3
                    )

        # --- Salvar estado ---
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.setex(f"estado:{conversation_id}", 86400, comprimir_texto(novo_estado))
            pipe.lpush(
                f"hist_estado:{conversation_id}",
                f"{datetime.now(ZoneInfo('America/Sao_Paulo')).isoformat()}|{novo_estado}"
            )
            pipe.ltrim(f"hist_estado:{conversation_id}", 0, 10)
            pipe.expire(f"hist_estado:{conversation_id}", 86400)
            await pipe.execute()

        if any(k in novo_estado for k in ("interessado", "conversao", "matricula", "animado")):
            await bd_registrar_evento_funil(
                conversation_id, "interesse_detectado", f"Estado: {novo_estado}"
            )

        salvar_resposta_unica = bool(resposta_texto and resposta_texto.strip() and not fast_reply_lista)
        if salvar_resposta_unica:
            await bd_salvar_mensagem_local(conversation_id, "assistant", resposta_texto)

        is_manual = (await redis_client.get(f"atend_manual:{conversation_id}")) == "1"

        if is_manual or await redis_client.exists(f"pause_ia:{conversation_id}"):
            pass  # IA pausada, não envia

        elif fast_reply_lista:
            # ── Planos: cada item da lista = 1 mensagem separada ──────────────
            for i, bloco_plano in enumerate(fast_reply_lista):
                if await redis_client.exists(f"pause_ia:{conversation_id}"):
                    break
                if not bloco_plano.strip():
                    continue
                await bd_salvar_mensagem_local(conversation_id, "assistant", bloco_plano.strip())
                typing_time = min(len(bloco_plano) * 0.012, 3.0) + random.uniform(0.2, 0.6)
                await simular_digitacao(account_id, conversation_id, integracao_chatwoot, typing_time)
                await enviar_mensagem_chatwoot(
                    account_id, conversation_id, bloco_plano.strip(), nome_ia, integracao_chatwoot
                )
                await bd_atualizar_msg_ia(conversation_id)
                if i == 0:
                    await bd_registrar_primeira_resposta(conversation_id)

        elif fast_reply:
            # ── Fast-path: envia UMA mensagem (saudação, endereço, horário, etc.) ──
            if not resposta_texto:
                resposta_texto = fast_reply if isinstance(fast_reply, str) else ""
            typing_time = min(len(resposta_texto) * 0.015, 3.5) + random.uniform(0.3, 0.8)
            await simular_digitacao(account_id, conversation_id, integracao_chatwoot, typing_time)
            await enviar_mensagem_chatwoot(
                account_id, conversation_id, resposta_texto, nome_ia, integracao_chatwoot
            )
            await bd_atualizar_msg_ia(conversation_id)
            await bd_registrar_primeira_resposta(conversation_id)

        else:
            # ── Resposta da IA: envia INTEIRA como UMA mensagem ──────────────
            # Split por parágrafo causava frases cortadas no meio ("Uma ótima opção
            # para conhecer..." em mensagem separada). O cliente recebe a resposta
            # completa de uma vez, como um humano digitaria.
            if resposta_texto and resposta_texto.strip():
                # Só corta se a LLM confirmou truncamento — nunca corta respostas completas
                _texto_final = garantir_frase_completa(resposta_texto) if _resposta_foi_truncada else resposta_texto.strip()
                typing_time = min(len(_texto_final) * 0.02, 4.0) + random.uniform(0.3, 0.8)
                await simular_digitacao(account_id, conversation_id, integracao_chatwoot, typing_time)
                await enviar_mensagem_chatwoot(
                    account_id, conversation_id, _texto_final, nome_ia, integracao_chatwoot
                )
                await bd_atualizar_msg_ia(conversation_id)
                await bd_registrar_primeira_resposta(conversation_id)

        # Registra hash das mensagens respondidas para bloquear duplicatas no drain
        await redis_client.setex(_ultima_resp_key, 120, _hash_msgs)

        # 🔄 DRAIN LOOP — processa mensagens que chegaram DURANTE o processamento da IA
        # Isso resolve o problema de mensagens perdidas quando o cliente digita rápido
        _drain_tentativas = 0
        while _drain_tentativas < 2:
            await asyncio.sleep(1.0)
            mensagens_pendentes = await redis_client.lrange(chave_buffet, 0, -1)
            if not mensagens_pendentes:
                break
            # Há mensagens novas — consome e repassa para o mesmo fluxo
            async with redis_client.pipeline(transaction=True) as pipe:
                pipe.lrange(chave_buffet, 0, -1)
                pipe.delete(chave_buffet)
                res_drain = await pipe.execute()
            msgs_drain = res_drain[0]
            if not msgs_drain:
                break
            logger.info(f"🔄 Drain: {len(msgs_drain)} mensagens extras para conv {conversation_id}")
            textos_drain = [json.loads(m).get("text", "") for m in msgs_drain if json.loads(m).get("text")]
            for txt in textos_drain:
                await bd_salvar_mensagem_local(conversation_id, "user", txt)
            # Passa essas mensagens para outro ciclo de processamento reutilizando o mesmo lock
            for m_json in msgs_drain:
                await redis_client.rpush(f"buffet_drain:{conversation_id}", m_json)
            await redis_client.expire(f"buffet_drain:{conversation_id}", 120)
            # Coloca de volta no buffet para ser pego pelo próximo webhook (lock será liberado logo)
            for m_json in msgs_drain:
                await redis_client.rpush(chave_buffet, m_json)
            await redis_client.expire(chave_buffet, 60)
            _drain_tentativas += 1

    except Exception:
        logger.exception("🔥 Erro Crítico no processamento")
    finally:
        watchdog.cancel()
        try:
            await redis_client.eval(LUA_RELEASE_LOCK, 1, chave_lock, lock_val)
        except Exception:
            pass
        # Após liberar o lock, se ainda há mensagens no buffet, agenda novo processamento
        try:
            restantes = await redis_client.lrange(chave_buffet, 0, -1)
            if restantes:
                logger.info(f"📬 {len(restantes)} mensagens no buffet após processamento — reagendando conv {conversation_id}")
                novo_lock_val = str(uuid.uuid4())
                if await redis_client.set(chave_lock, novo_lock_val, nx=True, ex=180):
                    asyncio.create_task(processar_ia_e_responder(
                        account_id, conversation_id, contact_id, slug,
                        nome_cliente, novo_lock_val, empresa_id, integracao_chatwoot
                    ))
        except Exception as e_drain:
            logger.error(f"Erro no drain pós-processamento: {e_drain}")
