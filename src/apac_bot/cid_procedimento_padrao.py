"""
CID principal (linha 06) e classificação (linha 13) por sufixo — APAC Padrão.

Mapas em código (YAGNI). Mover para config.json se a clínica passar a alterar
com frequência (≥2x/mês ou por operador sem deploy).
"""

from __future__ import annotations

from apac_bot.set_layout import SetLayoutError

# Últimos 4 dígitos do código SUS (só numérico) → CID linha 06 / cidpri
CID_POR_SUFIXO_PADRAO: dict[str, str] = {
    "0224": "H112",
    "0151": "A300",
    "0372": "H250",
    "0321": "H401",
    "0100": "A300",
    "0011": "H264",
    "0210": "H250",
    "0105": "H250",
    "0193": "H360",
    "0045": "H330",
    "0125": "A300",
    "0283": "H353",
}

# Sufixo → codigo_classificacao linha 13 (demais usam dados_fixos.codigo_classificacao).
CLASSIFICACAO_POR_SUFIXO_PADRAO: dict[str, str] = {
    "0283": "001",
}


class CidProcedimentoPadraoError(SetLayoutError):
    """Procedimento sem CID mapeado para o sufixo (APAC Padrão)."""


def normalizar_codigo_procedimento(valor: object) -> str:
    """Código com só dígitos; mantém zeros à esquerda (layout SET usa 10 dígitos)."""
    digits = "".join(ch for ch in str(valor or "") if ch.isdigit())
    return digits


def sufixo_codigo(codigo: str) -> str:
    """Últimos 4 dígitos do código normalizado."""
    norm = normalizar_codigo_procedimento(codigo)
    if len(norm) < 4:
        raise SetLayoutError(
            f"[cid-padrao] codigo de procedimento curto demais ({len(norm)} digitos): {codigo!r}"
        )
    return norm[-4:]


def cid_principal_por_codigo_padrao(codigo: str) -> str:
    """
    Retorna o CID para o código do procedimento (planilha COD.).
    Levanta CidProcedimentoPadraoError se o sufixo não estiver mapeado.
    """
    norm = normalizar_codigo_procedimento(codigo)
    if not norm:
        raise SetLayoutError("[cid-padrao] codigo de procedimento ausente")
    sufixo = sufixo_codigo(norm)
    cid = CID_POR_SUFIXO_PADRAO.get(sufixo)
    if not cid:
        raise CidProcedimentoPadraoError(
            f"[cid-padrao] procedimento {norm}: sufixo {sufixo} sem CID mapeado"
        )
    return cid


def classificacao_por_codigo_padrao(codigo: str, *, padrao: str = "003") -> str:
    """
    Classificação linha 13 SET (Padrão). Sufixo mapeado ou fallback do config.
    """
    sufixo = sufixo_codigo(codigo)
    return CLASSIFICACAO_POR_SUFIXO_PADRAO.get(sufixo, padrao)
