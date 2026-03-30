import re
from typing import Optional, List, Dict, Any
from src.utils.text_helpers import normalizar, limpar_nome

SAUDACOES = {
    # Abertura — cumprimentos de início de conversa
    "oi", "ola", "olá", "hey", "boa", "salve", "eai", "e ai",
    "bom dia", "boa tarde", "boa noite", "tudo bem", "tudo bom",
    "como vai", "oi tudo", "ola tudo", "oii", "oiii", "opa",
    # Follow-up imediato de small talk (resposta DIRETA à saudação da IA)
    "tudo sim", "tudo otimo", "tudo ótimo", "tudo ok",
    "por ai", "por aí", "e por ai", "e por aí", "e voce", "e você", "e vc",
    "bem sim", "tudo tranquilo", "tranquilo", "aqui tudo",
    "muito bem",
    # REMOVIDOS: palavras ambíguas que são usadas NO MEIO de conversas e causavam
    # o bot a reiniciar o cumprimento quando o cliente dizia "obrigado", "claro", etc.
    # "obrigado", "obg", "valeu", "brigado", "grato",  ← agradecimentos, não saudações
    # "otimo", "ótimo", "perfeito", "maravilha", "show", ← aprovações/reações
    # "ok ok", "beleza", "blz", "sim sim", "claro", "certo", ← afirmações
    # "que bom", "que otimo", "que ótimo", "que bom mesmo", ← reações positivas
    # "tudo certo", "bem obrigado", ← frases de transição
}

def eh_saudacao(texto: str) -> bool:
    """Retorna True se a mensagem for apenas uma saudação genérica (sem intenção real)."""
    if not texto:
        return False
    norm = normalizar(texto).strip()
    palavras = norm.split()
    # Mensagem curta (até 5 palavras) com match exato/início controlado
    if len(palavras) <= 5:
        return norm in SAUDACOES or any(norm.startswith(f"{s} ") for s in SAUDACOES)
    return False


def eh_confirmacao_curta(texto: str) -> bool:
    """Detecta confirmações curtas de continuidade (ex: 'quero sim', 'pode mandar')."""
    if not texto:
        return False
    t = normalizar(texto).strip()
    if len(t.split()) > 6:
        return False
    return bool(re.search(r"^(sim|quero sim|quero|pode|pode sim|pode mandar|manda|me passa|pode passar|ok|beleza|blz|claro)$", t))


def classificar_intencao(texto: str) -> str:
    """Classifica intenção principal com foco operacional (factual antes de LLM)."""
    t = normalizar(texto or "")
    if not t.strip():
        return "neutro"
    if eh_saudacao(t):
        return "saudacao"
    if re.search(r"(horario|horário|funcionamento|abre|fecha|que horas|aberto)", t):
        return "horario"
    if re.search(r"(endereco|endereço|localizacao|localização|onde fica|fica onde|como chegar)", t):
        return "endereco"
    if re.search(r"(telefone|whatsapp|contato|numero|número|ligar|falar com)", t):
        return "telefone"
    if re.search(r"(quais unidades|outras unidades|lista de unidades|quantas unidades|tem unidade|unidades)", t):
        return "unidades"
    if re.search(r"(preco|preço|valor|mensalidade|quanto custa|plano|planos|promo|promocao|promoção)", t):
        return "planos"
    if re.search(r"(grade de aulas?|grade|modalidade|modalidades|aulas?|musculacao|musculação|funcional|spinning|cross|pilates|yoga|zumba|fit\s?dance|fit\s?combat|muay|thai|jiu|jitsu|boxe|luta|lutas|jump|step|body\s?pump|body\s?balance|bike|hidroginastica|hidroginástica|natacao|natação|danca|dança|ballet|alongamento|rpg|circuito|hiit|treino)", t):
        return "modalidades"
    if re.search(r"(convenio|convênio|gympass|wellhub|totalpass)", t):
        return "convenio"
    return "llm"


def _faq_compativel_com_intencao(intencao: str, pergunta_faq: str) -> bool:
    """Evita FAQ fora de contexto (ex.: carnaval) para perguntas de grade/planos."""
    if not intencao or intencao in {"llm", "neutro", "saudacao"}:
        return True

    mapa = {
        "modalidades": {"aula", "aulas", "grade", "modalidade", "modalidades", "pilates", "zumba", "fit", "dance", "muay", "thai"},
        "horario": {"horario", "funcionamento", "abre", "fecha"},
        "endereco": {"endereco", "endereço", "local", "unidade", "fica"},
        "telefone": {"telefone", "whatsapp", "contato", "numero", "número"},
        "planos": {"plano", "planos", "valor", "preco", "preço", "mensalidade", "beneficio", "benefício"},
        "convenio": {"convenio", "convênio", "gympass", "wellhub", "totalpass"},
    }
    chaves = mapa.get(intencao)
    if not chaves:
        return True

    tokens_faq = {t for t in normalizar(pergunta_faq or "").split() if len(t) >= 3}
    return any(t in tokens_faq for t in chaves)


def garantir_frase_completa(txt: str) -> str:
    """Corta resposta truncada por max_tokens na última frase completa."""
    if not txt:
        return txt
    txt = txt.strip()
    if not txt:
        return txt
    ultimo = txt[-1]
    # Termina com pontuação ou qualquer emoji/símbolo unicode → está completo
    import unicodedata
    if ultimo in '.!?' or unicodedata.category(ultimo) in ('So', 'Sm', 'Sk', 'Mn'):
        return txt
    for _sep in ['. ', '! ', '? ', '!\n', '?\n', '.\n', '\n']:
        _pos = txt.rfind(_sep)
        if _pos > len(txt) * 0.3:
            return txt[:_pos + 1].strip()
    return txt
