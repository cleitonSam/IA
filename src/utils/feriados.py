"""
[FERIADOS-01] Calendário de feriados brasileiro para o bot de atendimento.

Cobre:
  - Feriados nacionais fixos (Ano Novo, Tiradentes, Trabalho, etc.)
  - Feriados nacionais móveis calculados (Carnaval, Páscoa, Corpus Christi)
  - Feriados estaduais: SP, RJ, MG, RS, PR, SC, BA, DF, PE, CE, GO
  - Feriado municipal de São Paulo (Aniversário da cidade)

Integração:
    from src.utils.feriados import feriado_hoje, status_feriado_para_prompt

    info = feriado_hoje(estado="SP")
    # None  →  dia normal
    # {'nome': 'Natal', 'tipo': 'nacional', 'data': date(2025, 12, 25)}

    bloco = status_feriado_para_prompt(estado="SP", cidade="São Paulo")
    # "" ou "[FERIADO HOJE] Natal — horário pode ser diferente."
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Cálculo de Páscoa (algoritmo de Butcher/Meeus)
# ─────────────────────────────────────────────────────────────────────────────

def _pascoa(ano: int) -> date:
    """Retorna a data da Páscoa para o ano dado."""
    a = ano % 19
    b = ano // 100
    c = ano % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


# ─────────────────────────────────────────────────────────────────────────────
# Gerador de feriados por ano
# ─────────────────────────────────────────────────────────────────────────────

def _feriados_nacionais(ano: int) -> dict[date, str]:
    """Retorna dict {data: nome} de todos os feriados nacionais do ano."""
    pascoa = _pascoa(ano)
    carnaval_segunda = pascoa - timedelta(days=48)
    carnaval_terca   = pascoa - timedelta(days=47)
    sexta_santa      = pascoa - timedelta(days=2)
    corpus_christi   = pascoa + timedelta(days=60)

    feriados = {
        # Fixos
        date(ano, 1,  1):  "Confraternização Universal (Ano Novo)",
        date(ano, 4,  21): "Tiradentes",
        date(ano, 5,  1):  "Dia do Trabalho",
        date(ano, 9,  7):  "Independência do Brasil",
        date(ano, 10, 12): "Nossa Senhora Aparecida",
        date(ano, 11, 2):  "Finados",
        date(ano, 11, 15): "Proclamação da República",
        date(ano, 12, 25): "Natal",
        # Móveis
        carnaval_segunda:  "Carnaval (segunda-feira)",
        carnaval_terca:    "Carnaval (terça-feira)",
        sexta_santa:       "Sexta-Feira Santa",
        pascoa:            "Páscoa",
        corpus_christi:    "Corpus Christi",
    }

    # Consciência Negra: nacional a partir de 2024 (Lei 14.759/2023)
    if ano >= 2024:
        feriados[date(ano, 11, 20)] = "Dia da Consciência Negra"

    return feriados


_FERIADOS_ESTADUAIS: dict[str, dict[tuple[int, int], str]] = {
    "SP": {
        (7, 9):  "Revolução Constitucionalista de 1932",
        (11, 20): "Dia da Consciência Negra (SP)",  # antecipado ao nacional
    },
    "RJ": {
        (1, 20): "São Sebastião (padroeiro do RJ)",
        (4, 23): "Dia de São Jorge",
        (11, 20): "Dia da Consciência Negra (RJ)",
    },
    "MG": {
        (4, 21): "Tiradentes (feriado especial MG)",
        (12, 8): "Nossa Senhora da Imaculada Conceição (MG)",
    },
    "RS": {
        (9, 20): "Proclamação da República Rio-Grandense",
    },
    "PR": {
        (12, 19): "Emancipação Política do Paraná",
    },
    "SC": {
        (8, 11): "Dia do Estado de Santa Catarina",
    },
    "BA": {
        (7, 2):  "Independência da Bahia",
    },
    "DF": {
        (4, 21): "Fundação de Brasília",
        (11, 30): "Dia do Evangélico",
    },
    "PE": {
        (3, 6):  "Revolução Pernambucana de 1817",
        (6, 24): "São João (PE)",
    },
    "CE": {
        (3, 25): "Data Magna do Ceará",
        (6, 24): "São João (CE)",
    },
    "GO": {
        (10, 24): "Pedra Fundamental de Goiânia",
    },
}

_FERIADOS_MUNICIPAIS: dict[str, dict[tuple[int, int], str]] = {
    "São Paulo": {
        (1, 25): "Aniversário de São Paulo",
        (11, 20): "Dia da Consciência Negra (SP)",
    },
    "Rio de Janeiro": {
        (3, 1): "Carnaval (RJ municipal)",
        (11, 20): "Dia da Consciência Negra (RJ)",
    },
    "Belo Horizonte": {
        (8, 14): "Dia de Belo Horizonte",
    },
    "Salvador": {
        (7, 2):  "Independência da Bahia",
        (12, 8): "Nossa Senhora da Conceição (Salvador)",
    },
    "Fortaleza": {
        (3, 25): "Data Magna do Ceará",
    },
    "Recife": {
        (3, 6):  "Revolução Pernambucana",
        (12, 8): "Nossa Senhora da Conceição (Recife)",
    },
    "Curitiba": {
        (3, 29): "Aniversário de Curitiba",
    },
    "Porto Alegre": {
        (9, 20): "Farroupilha",
    },
    "Brasília": {
        (4, 21): "Aniversário de Brasília",
    },
    "Manaus": {
        (10, 24): "Aniversário de Manaus",
    },
    "Belém": {
        (10, 12): "Círio de Nazaré (feriado municipal em Belém)",
    },
    "Campinas": {
        (7, 14): "Aniversário de Campinas",
    },
    "Guarulhos": {
        (12, 9): "Aniversário de Guarulhos",
    },
    "Santo André": {
        (8, 8): "Aniversário de Santo André",
    },
    "Santos": {
        (1, 26): "Aniversário de Santos",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────────────────────────────────────

def feriado_hoje(
    estado: Optional[str] = None,
    cidade: Optional[str] = None,
    hoje: Optional[date] = None,
) -> Optional[dict]:
    """
    Verifica se hoje é feriado.

    Args:
        estado: sigla UF (ex: "SP", "RJ"). Inclui feriados estaduais.
        cidade: nome da cidade (ex: "São Paulo"). Inclui feriados municipais.
        hoje:   sobrescreve a data atual (útil para testes).

    Returns:
        None → dia normal.
        dict → {'nome': str, 'tipo': 'nacional'|'estadual'|'municipal', 'data': date}
    """
    d = hoje or date.today()
    ano = d.year

    # 1. Nacional
    nacionais = _feriados_nacionais(ano)
    if d in nacionais:
        return {"nome": nacionais[d], "tipo": "nacional", "data": d}

    # 2. Estadual
    if estado:
        uf = estado.upper().strip()
        estaduais = _FERIADOS_ESTADUAIS.get(uf, {})
        chave = (d.month, d.day)
        if chave in estaduais:
            return {"nome": estaduais[chave], "tipo": "estadual", "data": d}

    # 3. Municipal
    if cidade:
        municipais = _FERIADOS_MUNICIPAIS.get(cidade.strip(), {})
        chave = (d.month, d.day)
        if chave in municipais:
            return {"nome": municipais[chave], "tipo": "municipal", "data": d}

    return None


def proximos_feriados(
    dias: int = 30,
    estado: Optional[str] = None,
    cidade: Optional[str] = None,
    hoje: Optional[date] = None,
) -> list[dict]:
    """
    Lista os próximos feriados dentro de N dias.

    Returns:
        Lista de {'nome', 'tipo', 'data', 'dias_restantes'} ordenada por data.
    """
    inicio = hoje or date.today()
    resultado = []

    for offset in range(1, dias + 1):
        d = inicio + timedelta(days=offset)
        f = feriado_hoje(estado=estado, cidade=cidade, hoje=d)
        if f:
            f["dias_restantes"] = offset
            resultado.append(f)

    return resultado


def status_feriado_para_prompt(
    estado: Optional[str] = None,
    cidade: Optional[str] = None,
    horario_feriado: Optional[str] = None,
) -> str:
    """
    Gera bloco de texto para injetar no prompt do LLM quando há feriado.

    Args:
        estado: sigla UF da unidade.
        cidade: cidade da unidade.
        horario_feriado: horário especial de feriado configurado na unidade
                         (ex: "09h às 17h"). Se None, a IA vai informar que
                         pode haver horário diferenciado.

    Returns:
        String vazia → dia normal (não injeta nada no prompt).
        String preenchida → bloco [FERIADO HOJE] para o prompt.
    """
    info = feriado_hoje(estado=estado, cidade=cidade)
    if not info:
        return ""

    nome = info["nome"]
    tipo = info["tipo"].capitalize()

    if horario_feriado:
        return (
            f"[FERIADO HOJE — {tipo.upper()}] {nome}.\n"
            f"Horário especial de feriado desta unidade: {horario_feriado}.\n"
            f"USE este horário ao responder perguntas sobre funcionamento hoje."
        )
    else:
        return (
            f"[FERIADO HOJE — {tipo.upper()}] {nome}.\n"
            f"ATENÇÃO: Hoje é feriado. Informe ao cliente que o horário pode ser "
            f"diferenciado e sugira verificar com a unidade ou pelo site."
        )


def calendario_feriados_ano(
    ano: int,
    estado: Optional[str] = None,
    cidade: Optional[str] = None,
) -> list[dict]:
    """
    Retorna todos os feriados do ano em ordem cronológica.
    Útil para exibir no painel admin.
    """
    resultado = []

    nacionais = _feriados_nacionais(ano)
    for d, nome in sorted(nacionais.items()):
        resultado.append({"data": d, "nome": nome, "tipo": "nacional"})

    if estado:
        uf = estado.upper().strip()
        for (mes, dia), nome in sorted(_FERIADOS_ESTADUAIS.get(uf, {}).items()):
            d = date(ano, mes, dia)
            if d not in nacionais:  # evita duplicata com nacional
                resultado.append({"data": d, "nome": nome, "tipo": "estadual"})

    if cidade:
        for (mes, dia), nome in sorted(_FERIADOS_MUNICIPAIS.get(cidade.strip(), {}).items()):
            d = date(ano, mes, dia)
            if not any(r["data"] == d for r in resultado):
                resultado.append({"data": d, "nome": nome, "tipo": "municipal"})

    resultado.sort(key=lambda x: x["data"])
    return resultado
