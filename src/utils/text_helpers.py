import re
import unicodedata
import base64
import zlib
from typing import Optional, List, Dict, Any

def normalizar(texto: str) -> str:
    """Remove acentos e converte para minúsculas"""
    if not texto:
        return ""
    return unicodedata.normalize("NFD", str(texto).lower()).encode("ascii", "ignore").decode("utf-8")


def comprimir_texto(texto: str) -> str:
    if not texto:
        return ""
    dados = zlib.compress(texto.encode('utf-8'))
    return base64.b64encode(dados).decode('utf-8')


def descomprimir_texto(texto_comprimido: str) -> str:
    if not texto_comprimido:
        return ""
    try:
        dados = base64.b64decode(texto_comprimido)
        return zlib.decompress(dados).decode('utf-8')
    except Exception:
        return texto_comprimido


def limpar_nome(nome):
    if not nome:
        return "Cliente"
    return re.sub(r"[^a-zA-ZÀ-ÿ\s]", "", str(nome)).strip()


def primeiro_nome_cliente(nome: Optional[str]) -> str:
    nome_limpo = limpar_nome(nome) if nome else ""
    if not nome_limpo or not nome_eh_valido(nome_limpo):
        return ""
    return nome_limpo.split()[0].capitalize()


_NOMES_INVALIDOS = {
    # Genéricos de sistema
    "cliente", "contato", "visitante", "unknown", "na", "n a", "lead", "user",
    "usuario", "teste", "test", "admin", "suporte", "support", "bot",
    # Saudações / palavras comuns salvas como nome
    "boa", "bom", "oi", "ola", "hello", "hi", "hey", "obrigado", "obrigada",
    "sim", "nao", "ok", "tudo", "bem", "blz", "beleza",
    # Profissões / ocupações comuns
    "costureira", "costureiro", "pedreiro", "padeiro", "padeira", "motorista",
    "porteiro", "porteira", "zelador", "zeladora", "cabeleireiro", "cabeleireira",
    "barbeiro", "eletricista", "encanador", "pintor", "pintora", "faxineira",
    "faxineiro", "diarista", "mecanico", "mecanica", "garcom", "garconete",
    "cozinheiro", "cozinheira", "vendedor", "vendedora", "professor", "professora",
    "doutor", "doutora", "enfermeiro", "enfermeira", "dentista", "advogado",
    "advogada", "personal", "personol", "nutricionista", "recepcionista",
    # Adjetivos / apelidos genéricos
    "amor", "amiga", "amigo", "querido", "querida", "lindo", "linda", "fofo",
    "fofa", "mano", "mana", "brother", "parceiro", "parceira", "chefe", "boss",
    "gato", "gata", "principe", "princesa", "prince", "princess", "rei", "rainha", "anjo",
    # Parentesco
    "mae", "pai", "filho", "filha", "esposo", "esposa", "marido", "mulher",
    "tio", "tia", "primo", "prima", "sogro", "sogra", "cunhado", "cunhada",
    "vovo", "vovo", "neto", "neta", "irmao", "irma",
    # Substantivos comuns / locais / objetos
    "whatsapp", "wpp", "zap", "instagram", "face", "facebook", "empresa",
    "academia", "loja", "casa", "trabalho", "escritorio", "consultorio",
    "encantos", "encanto", "sorrisos", "sorriso", "brilho", "estrela",
    "flor", "flores", "beleza", "saude", "vida", "forca", "foco",
    "treino", "fitness", "gym", "crossfit", "pilates", "musculacao",
    "dieta", "projeto", "resultado", "objetivo", "meta", "corpo",
    "praia", "sol", "lua", "ceu", "terra", "mar", "rio", "moda",
    "negocio", "negocios", "servico", "servicos", "produto", "produtos",
    # Nomes comuns de WhatsApp / redes sociais
    "baby", "babe", "honey", "dear", "queen", "king", "lion", "tiger",
    "wolf", "angel", "star", "sunshine", "rainbow", "diamond", "gold",
    "silver", "dark", "light", "magic", "power", "super", "top",
    "best", "real", "oficial", "original", "novo", "nova",
    # Números / abreviações viram "nome"
    "msg", "info", "contato", "atendimento", "sac", "central",
    "equipe", "time", "grupo", "turma", "galera", "pessoal",
    # Emojis e variações que sobram após limpar_nome
    "coracao", "estrelas", "anjinho", "anjinha", "gatinha", "gatinho",
    "mozao", "mozinho", "mozinha", "docinho", "docinha", "benzinho", "benzinha",
}

def nome_eh_valido(nome: Optional[str]) -> bool:
    nome_limpo = limpar_nome(nome) if nome else ""
    if not nome_limpo or len(nome_limpo) < 2:
        return False
    nome_lower = normalizar(nome_limpo)
    palavras = nome_lower.split()
    # Palavra única na blocklist
    if len(palavras) == 1 and palavras[0] in _NOMES_INVALIDOS:
        return False
    # Todas as palavras são inválidas
    if all(p in _NOMES_INVALIDOS for p in palavras):
        return False
    # Nome sem letras
    if not any(c.isalpha() for c in nome_limpo):
        return False
    # Palavra única muito longa (>15 chars) = username/nome grudado (ex: "Tatianaribeirosampaio")
    if len(palavras) == 1 and len(palavras[0]) > 15:
        return False
    return True


def extrair_nome_do_texto(texto: str) -> Optional[str]:
    if not texto:
        return None
    t = str(texto).strip()
    padroes = [
        r"(?:meu nome e|meu nome é|me chamo|me chamam de|me chamam|pode me chamar de|chamo|sou o|sou a|eu sou)\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s]{1,40})",
        r"^([A-Za-zÀ-ÿ]{2,20})(?:\s+[A-Za-zÀ-ÿ]{2,20})?$",
    ]
    for ptn in padroes:
        m = re.search(ptn, t, flags=re.IGNORECASE)
        if not m:
            continue
        nome = limpar_nome(m.group(1))
        if nome_eh_valido(nome):
            return nome.title()
    return None


def limpar_markdown(texto: str) -> str:
    """
    Converte markdown para formato compatível com WhatsApp/Chatwoot:
    - [texto](url)  →  url
    - **texto**     →  *texto*  (WhatsApp usa asterisco simples para negrito)
    - __texto__     →  _texto_
    - Remove ### headers
    """
    if not texto:
        return texto

    # [texto](url) → url  (evita colchetes e parênteses feios)
    texto = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\2', texto)

    # **texto** → *texto*
    texto = re.sub(r'\*\*(.+?)\*\*', r'*\1*', texto)

    # __texto__ → _texto_
    texto = re.sub(r'__(.+?)__', r'_\1_', texto)

    # ### Título → Título (remove headers markdown)
    texto = re.sub(r'^#{1,6}\s+', '', texto, flags=re.MULTILINE)

    return texto


def randomizar_mensagem(texto: str) -> str:
    """
    Adiciona um caractere invisível (Zero Width Space ou similar) 
    aleatório ao final da mensagem para evitar bloqueio por conteúdo idêntico.
    """
    if not texto:
        return texto
    
    import random
    # Lista de caracteres invisíveis Unicode seguros para WhatsApp
    chars_invisiveis = [
        "\u200B", # Zero Width Space
        "\u200C", # Zero Width Non-Joiner
        "\u200D", # Zero Width Joiner
        "\u2060", # Word Joiner
        "\uFEFF", # Zero Width No-Break Space
    ]
    char_prefixo = random.choice(chars_invisiveis)
    char_sufixo = random.choice(chars_invisiveis)
    
    return f"{char_prefixo}{texto}{char_sufixo}"
