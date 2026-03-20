import json
import logging
import re
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from typing import Optional, Any, Tuple
from src.utils.text_helpers import normalizar

logger = logging.getLogger(__name__)

def saudacao_por_horario() -> str:
    """
    Retorna 'Bom dia', 'Boa tarde' ou 'Boa noite' baseado no horário de São Paulo.
    Faixas:  6h–11h59 → Bom dia | 12h–17h59 → Boa tarde | 18h–5h59 → Boa noite
    Madrugada (0h–5h) também recebe 'Boa noite'.
    """
    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    hora = agora.hour
    if 6 <= hora < 12:
        return "Bom dia"
    elif 12 <= hora < 18:
        return "Boa tarde"
    else:  # 18h–23h e 0h–5h (madrugada)
        return "Boa noite"


def horario_hoje_formatado(horarios: Any) -> Optional[str]:
    """
    Retorna o horário de funcionamento de HOJE (baseado no dia da semana em SP).
    Suporta dict com chaves como "segunda", "seg", "segunda-feira", etc.
    Retorna None se não encontrar.
    """
    if not horarios:
        return None

    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    dia_semana_idx = agora.weekday()  # 0=segunda, 6=domingo

    # Mapeamento de dia da semana para possíveis chaves no dict de horários
    DIAS_MAP = {
        0: ["segunda", "seg", "segunda-feira", "mon", "segunda feira"],
        1: ["terca", "ter", "terça", "terca-feira", "terça-feira", "tue", "terca feira"],
        2: ["quarta", "qua", "quarta-feira", "wed", "quarta feira"],
        3: ["quinta", "qui", "quinta-feira", "thu", "quinta feira"],
        4: ["sexta", "sex", "sexta-feira", "fri", "sexta feira"],
        5: ["sabado", "sab", "sábado", "sat"],
        6: ["domingo", "dom", "sun"],
    }

    # Também tenta "seg a sex" / "segunda a sexta" / "dias uteis" para dias 0-4
    AGRUPADOS = {
        "seg a sex": range(0, 5),
        "segunda a sexta": range(0, 5),
        "dias uteis": range(0, 5),
        "dias úteis": range(0, 5),
        "sab e dom": range(5, 7),
        "sabado e domingo": range(5, 7),
        "sábado e domingo": range(5, 7),
        "fim de semana": range(5, 7),
        "feriados": [],  # tratado separadamente
    }

    # Se vier como string JSON (ex: asyncpg retorna JSONB como texto), converte para dict
    if isinstance(horarios, str):
        try:
            horarios = json.loads(horarios)
        except (json.JSONDecodeError, ValueError):
            # String simples (ex: "06:00-23:00") — retorna diretamente
            return horarios if len(horarios) < 50 else None

    if isinstance(horarios, dict):
        # 1. Tenta chave específica do dia
        possiveis = DIAS_MAP.get(dia_semana_idx, [])
        for chave in possiveis:
            for key_orig, valor in horarios.items():
                if normalizar(key_orig).strip() == normalizar(chave).strip():
                    return str(valor)

        # 2. Tenta chaves agrupadas ("seg a sex", "dias uteis", etc.)
        for chave_agrupada, dias_range in AGRUPADOS.items():
            if dia_semana_idx in dias_range:
                for key_orig, valor in horarios.items():
                    if normalizar(chave_agrupada) in normalizar(key_orig):
                        return str(valor)

    return None


def formatar_horarios_funcionamento(horarios: Any) -> str:
    """Converte horários da unidade em texto amigável para resposta direta ao cliente."""
    if not horarios:
        return "não informado"

    if isinstance(horarios, str):
        try:
            horarios = json.loads(horarios)
        except (json.JSONDecodeError, ValueError):
            return horarios

    if isinstance(horarios, dict):
        return "\n".join([f"- {dia}: {hora}" for dia, hora in horarios.items()])

    return str(horarios)


def esta_aberta_agora(horarios: Any) -> Tuple[Optional[bool], Optional[str]]:
    """
    Analisa o horário de funcionamento e retorna (aberta_agora, horario_hoje).
    Suporta string multi-linha "Seg-Sex: 06:00–23:00\nSáb: 09:00–17:00\nDom: 09:00–13:00"
    e dict com chaves por dia.
    Retorna (None, None) se não conseguir determinar.
    """
    if not horarios:
        return None, None

    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    dia_idx = agora.weekday()  # 0=segunda, 6=domingo
    hora_atual = agora.time()

    DIA_ABREV = {
        'seg': 0, 'ter': 1, 'qua': 2, 'qui': 3, 'sex': 4,
        'sab': 5, 'sáb': 5, 'dom': 6,
    }

    def _normalizar_dia(s: str) -> Optional[int]:
        return DIA_ABREV.get(normalizar(s).strip()[:3])

    def _dia_na_linha(dias_str: str) -> bool:
        dias_str = normalizar(dias_str).strip()
        m = re.match(r'^(\w+)\s*[-–]\s*(\w+)$', dias_str)
        if m:
            ini = _normalizar_dia(m.group(1))
            fim = _normalizar_dia(m.group(2))
            if ini is not None and fim is not None:
                return ini <= dia_idx <= fim
        d = _normalizar_dia(dias_str)
        return d == dia_idx

    horario_hoje = None

    if isinstance(horarios, str):
        try:
            horarios = json.loads(horarios)
        except (json.JSONDecodeError, ValueError):
            for linha in horarios.strip().split('\n'):
                linha = linha.strip()
                if ':' not in linha:
                    continue
                partes = linha.split(':', 1)
                if _dia_na_linha(partes[0].strip()):
                    horario_hoje = partes[1].strip()
                    break

    if isinstance(horarios, dict):
        horario_hoje = horario_hoje_formatado(horarios)

    if not horario_hoje:
        return None, None

    # Extrai os dois primeiros horários: abertura e fechamento
    times = re.findall(r'(\d{1,2}):(\d{2})', horario_hoje)
    if len(times) < 2:
        return None, horario_hoje

    try:
        abertura = dtime(int(times[0][0]), int(times[0][1]))
        fechamento = dtime(int(times[1][0]), int(times[1][1]))
    except ValueError:
        return None, horario_hoje

    return abertura <= hora_atual < fechamento, horario_hoje


# Mapeamento índice weekday → chave PT-BR usada no horario_atendimento_ia
_DIA_KEYS = {
    0: "segunda",
    1: "terca",
    2: "quarta",
    3: "quinta",
    4: "sexta",
    5: "sabado",
    6: "domingo",
}


def ia_esta_no_horario(config: Any) -> bool:
    """
    Verifica se a IA deve atender agora com base na configuração de horário.
    """
    logger.info(f"🕒 [Horário IA] Raw Config recebido: {config}")

    if not config:
        return True

    if isinstance(config, str):
        try:
            config = json.loads(config)
        except (json.JSONDecodeError, ValueError):
            return True

    if not isinstance(config, dict):
        return True

    tipo = config.get("tipo", "dia_todo")
    if tipo == "dia_todo":
        return True

    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    dia_key = _DIA_KEYS.get(agora.weekday(), "segunda")
    hora_atual = agora.time()

    logger.info(f"🕒 [Horário IA] Verificando para {dia_key} às {hora_atual.strftime('%H:%M:%S')} (SP)")

    dias = config.get("dias", {})
    periodos = dias.get(dia_key, [])

    if not periodos:
        logger.info(f"🕒 [Horário IA] Nenhum período configurado para {dia_key}. Resultado: False")
        return False

    for periodo in periodos:
        try:
            h_ini, m_ini = map(int, periodo["inicio"].split(":"))
            h_fim, m_fim = map(int, periodo["fim"].split(":"))

            t_ini = dtime(h_ini, m_ini)

            # Ajuste para fim do dia (00:00 interpretado como o limite final da data atual)
            if h_fim == 0 and m_fim == 0:
                # Se o fim é 00:00, tratamos como 23:59:59 daquele mesmo dia
                esta_no_periodo = t_ini <= hora_atual <= dtime(23, 59, 59)
            else:
                t_fim = dtime(h_fim, m_fim)
                # Período só é válido quando fim > inicio.
                # Se inicio >= fim o período é ignorado (ex: 23:50-18:00).
                if t_ini >= t_fim:
                    logger.info(f"🕒 [Horário IA] Período inválido ignorado: {periodo['inicio']} >= {periodo['fim']}")
                    continue
                esta_no_periodo = t_ini <= hora_atual < t_fim

            logger.info(f"🕒 [Horário IA] Check: {periodo['inicio']} - {periodo['fim']} -> {esta_no_periodo}")
            if esta_no_periodo:
                return True
        except Exception as e:
            logger.error(f"🕒 [Horário IA] Erro ao processar período {periodo}: {e}")
            continue

    return False
