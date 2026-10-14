"""
Leitura do buffer de tela do APAC Magnético via console clássico (conhost).

Requer que o APAC.exe esteja hospedado em conhost (não Windows Terminal).
"""

from __future__ import annotations

import ctypes
import re
from ctypes import wintypes
from enum import Enum
from apac_bot.logging_safe import setup_logging

log = setup_logging()

# AttachConsole(ATTACH_PARENT_PROCESS)
_ATTACH_PARENT_PROCESS = 0xFFFFFFFF
_STD_OUTPUT_HANDLE = -11

_RE_COD_PROCEDIMENTO = re.compile(r"\d{2}\.\d{2}\.\d{2}\.\d{3}-\d")


class TelaApac(str, Enum):
    MENU = "MENU"
    LISTA = "LISTA"
    IDENTIFICACAO = "IDENTIFICACAO"
    PROCEDIMENTOS = "PROCEDIMENTOS"
    DADOS_COMPLEMENTARES = "DADOS_COMPLEMENTARES"
    SOLICITACAO = "SOLICITACAO"
    DESCONHECIDA = "DESCONHECIDA"


class CampoApac(str, Enum):
    NOME = "NOME"
    NOME_MAE = "NOME_MAE"
    RESPONSAVEL = "RESPONSAVEL"
    CEP = "CEP"
    LOGRADOURO = "LOGRADOURO"
    ENDERECO = "ENDERECO"
    NUMERO = "NUMERO"
    COMPLEMENTO = "COMPLEMENTO"
    BAIRRO = "BAIRRO"
    TELEFONE = "TELEFONE"
    EMAIL = "EMAIL"
    NASCIMENTO = "NASCIMENTO"
    SEXO = "SEXO"
    ETNIA_RACA = "ETNIA_RACA"
    MUNICIPIO = "MUNICIPIO"
    COD_PROCEDIMENTO = "COD_PROCEDIMENTO"
    CBO = "CBO"
    QUANTIDADE = "QUANTIDADE"
    CNS_EXECUTANTE = "CNS_EXECUTANTE"
    EQUIPE = "EQUIPE"
    SERVICO = "SERVICO"
    CLASSIFICACAO = "CLASSIFICACAO"
    MOTIVO_SAIDA = "MOTIVO_SAIDA"
    DATA_ALTA = "DATA_ALTA"
    CID_PRINCIPAL = "CID_PRINCIPAL"
    CID_SECUNDARIO = "CID_SECUNDARIO"
    CAUSAS_ASSOCIADAS = "CAUSAS_ASSOCIADAS"
    CARATER_ATEND = "CARATER_ATEND"
    CNS_SOLICITANTE = "CNS_SOLICITANTE"
    CNS_AUTORIZADOR = "CNS_AUTORIZADOR"
    DT_SOLICITACAO = "DT_SOLICITACAO"
    DT_AUTORIZACAO = "DT_AUTORIZACAO"
    COD_ORGAO_EMISS = "COD_ORGAO_EMISS"
    DESCONHECIDO = "DESCONHECIDO"


# Marcadores de rotulo (ordem importa para desempate quando cx nao ajuda).
# Inclui truncagens do Magnético (ex.: "NOME DO RES:" em vez de RESPONSAVEL).
_ROTULOS_CAMPO: list[tuple[CampoApac, tuple[str, ...]]] = [
    (CampoApac.NOME_MAE, ("NOME DA MAE", "NOME DA MÃE", "NOME DA MA")),
    (
        CampoApac.RESPONSAVEL,
        (
            "NOME DO RESPONSAVEL",
            "NOME DO RESPONSÁVEL",
            "NOME DO RES",  # truncado no buffer: "NOME DO RES: O MESMO"
            "RESPONSAVEL",
            "RESPONSÁVEL",
        ),
    ),
    (CampoApac.NASCIMENTO, ("NASCIMENTO", "DATA DE NASC")),
    (CampoApac.ETNIA_RACA, ("ETNIA", "RACA", "RAÇA")),
    (CampoApac.LOGRADOURO, ("LOGRADOURO",)),
    (CampoApac.ENDERECO, ("ENDERECO", "ENDEREÇO")),
    (CampoApac.COMPLEMENTO, ("COMPLEMENTO",)),
    (CampoApac.BAIRRO, ("BAIRRO",)),
    (CampoApac.TELEFONE, ("TELEFONE", "DDD")),
    (CampoApac.EMAIL, ("EMAIL", "E-MAIL")),
    (CampoApac.MUNICIPIO, ("MUNICIPIO", "MUNICÍPIO", "IBGE")),
    (
        CampoApac.COD_PROCEDIMENTO,
        (
            "COD. PROCEDIMENTO",
            "COD.PROCEDIMENTO",
            "COD PROCEDIMENTO",
            "CODIGO DO PROCEDIMENTO",
        ),
    ),
    (CampoApac.CNS_EXECUTANTE, ("CNS EXECUTANTE", "CNS EXEC")),
    (CampoApac.CLASSIFICACAO, ("CLASSIFICACAO", "CLASSIF.", "CLASSIF")),
    (CampoApac.MOTIVO_SAIDA, ("MOTIVO SAIDA", "MOTIVO SAÍDA")),
    (
        CampoApac.DATA_ALTA,
        (
            "DATA ALTA/OBITO",
            "DATA ALTA",
            "MUDANCA PROCED",
            "MUDANÇA PROCED",
        ),
    ),
    (
        CampoApac.CID_PRINCIPAL,
        ("C.I.D. PRINCIPAL", "CID PRINCIPAL", "CID PRINC."),
    ),
    (CampoApac.CID_SECUNDARIO, ("SECUNDARIO",)),
    (CampoApac.CAUSAS_ASSOCIADAS, ("CAUSAS ASSOCIADAS",)),
    (CampoApac.CARATER_ATEND, ("CARATER ATEND", "CARATER ATEND.")),
    (CampoApac.DT_SOLICITACAO, ("DT.SOLICITACAO", "DT SOLICITACAO")),
    (CampoApac.DT_AUTORIZACAO, ("DT.AUTORIZACAO", "DT AUTORIZACAO")),
    (
        CampoApac.COD_ORGAO_EMISS,
        ("COD.ORGAO EMISS", "COD.ORGAO", "COD ORGAO EMISS"),
    ),
    # Apos CNS EXECUTANTE — "CNS" sozinho na tela SOLICITACAO
    (CampoApac.CNS_SOLICITANTE, ("CNS",)),
    (CampoApac.CNS_AUTORIZADOR, ("CNS",)),
    (CampoApac.QUANTIDADE, ("QUANTIDADE", "QUANT.")),
    (CampoApac.SERVICO, ("SERVICO", "SERVIÇO")),
    (CampoApac.EQUIPE, ("EQUIPE",)),
    (CampoApac.CBO, ("C.B.O.", "CBO")),
    (CampoApac.SEXO, ("SEXO",)),
    (CampoApac.CEP, ("CEP",)),
    (CampoApac.NUMERO, ("NUMERO", "NÚMERO")),
    (CampoApac.NOME, ("NOME",)),  # por ultimo — substring de outros
]

_RE_MUNICIPIO_VALOR = re.compile(
    r"^\d{6,7}\s*/\s*[A-ZÁÉÍÓÚÃÕÇ ]",
    re.IGNORECASE,
)


class COORD(ctypes.Structure):
    _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


class SMALL_RECT(ctypes.Structure):
    _fields_ = [
        ("Left", wintypes.SHORT),
        ("Top", wintypes.SHORT),
        ("Right", wintypes.SHORT),
        ("Bottom", wintypes.SHORT),
    ]


class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize", COORD),
        ("dwCursorPosition", COORD),
        ("wAttributes", wintypes.WORD),
        ("srWindow", SMALL_RECT),
        ("dwMaximumWindowSize", COORD),
    ]


class ConsoleScreenError(Exception):
    """Falha ao anexar/ler o buffer do console do APAC."""


def _kernel32():
    k32 = ctypes.windll.kernel32
    k32.AttachConsole.argtypes = [wintypes.DWORD]
    k32.AttachConsole.restype = wintypes.BOOL
    k32.FreeConsole.argtypes = []
    k32.FreeConsole.restype = wintypes.BOOL
    k32.GetStdHandle.argtypes = [wintypes.DWORD]
    k32.GetStdHandle.restype = wintypes.HANDLE
    k32.GetConsoleScreenBufferInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(CONSOLE_SCREEN_BUFFER_INFO),
    ]
    k32.GetConsoleScreenBufferInfo.restype = wintypes.BOOL
    k32.ReadConsoleOutputCharacterW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        COORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    k32.ReadConsoleOutputCharacterW.restype = wintypes.BOOL
    return k32


def ler_buffer_console(pid: int) -> str:
    """
    Anexa ao console do processo `pid`, le a janela visivel do buffer e devolve texto.
    Restaura o console do processo atual (pai) ao final.
    """
    if pid <= 0:
        raise ConsoleScreenError("PID invalido para leitura do console.")

    k32 = _kernel32()
    k32.FreeConsole()
    attached = False
    try:
        if not k32.AttachConsole(wintypes.DWORD(pid)):
            err = ctypes.GetLastError()
            raise ConsoleScreenError(
                f"AttachConsole falhou para PID {pid} (WinError {err}). "
                "O APAC precisa estar no console classico (conhost), nao no "
                "Windows Terminal. Feche o APAC e deixe a automacao reabrir."
            )
        attached = True

        h_out = k32.GetStdHandle(wintypes.DWORD(_STD_OUTPUT_HANDLE & 0xFFFFFFFF))
        if not h_out or h_out == wintypes.HANDLE(-1).value:
            raise ConsoleScreenError(
                f"GetStdHandle(STD_OUTPUT) falhou apos AttachConsole (PID {pid})."
            )

        info = CONSOLE_SCREEN_BUFFER_INFO()
        if not k32.GetConsoleScreenBufferInfo(h_out, ctypes.byref(info)):
            err = ctypes.GetLastError()
            raise ConsoleScreenError(
                f"GetConsoleScreenBufferInfo falhou (PID {pid}, WinError {err})."
            )

        left = int(info.srWindow.Left)
        top = int(info.srWindow.Top)
        right = int(info.srWindow.Right)
        bottom = int(info.srWindow.Bottom)
        width = right - left + 1
        height = bottom - top + 1
        if width <= 0 or height <= 0:
            raise ConsoleScreenError(
                f"Janela do console invalida ({width}x{height}) PID {pid}."
            )

        linhas: list[str] = []
        for row in range(top, bottom + 1):
            buf = ctypes.create_unicode_buffer(width + 1)
            nread = wintypes.DWORD(0)
            coord = COORD(left, row)
            ok = k32.ReadConsoleOutputCharacterW(
                h_out,
                buf,
                wintypes.DWORD(width),
                coord,
                ctypes.byref(nread),
            )
            if not ok:
                err = ctypes.GetLastError()
                raise ConsoleScreenError(
                    f"ReadConsoleOutputCharacterW falhou linha {row} "
                    f"(PID {pid}, WinError {err})."
                )
            linhas.append(buf.value[: int(nread.value)].rstrip())

        # Remove linhas vazias no fim; mantem estrutura da tela
        while linhas and not linhas[-1].strip():
            linhas.pop()
        texto = "\n".join(linhas)
        if not texto.strip():
            raise ConsoleScreenError(
                f"Buffer do console vazio (PID {pid}). "
                "Confira se a janela do APAC esta visivel no conhost."
            )
        return texto
    finally:
        if attached:
            k32.FreeConsole()
        # Reanexa ao console pai (Cursor/PowerShell) se existir
        k32.AttachConsole(wintypes.DWORD(_ATTACH_PARENT_PROCESS))


def ler_buffer_apac(pids: list[int]) -> str:
    """Tenta ler o buffer a partir da lista de PIDs do APAC.exe."""
    if not pids:
        raise ConsoleScreenError(
            "APAC.exe nao esta em execucao — nao ha console para ler."
        )
    erros: list[str] = []
    for pid in pids:
        try:
            return ler_buffer_console(pid)
        except ConsoleScreenError as exc:
            erros.append(f"PID {pid}: {exc}")
            log.debug("Falha ao ler console PID %s: %s", pid, exc)
    raise ConsoleScreenError(
        "Nao foi possivel ler o buffer do APAC. Detalhes: " + " | ".join(erros)
    )


_RE_DOTS = re.compile(r"\.{2,}\s*(.*)$")
_RE_BOX = re.compile(r"[║║╔╗╚╝═─\|]+")
_RE_CEP_INICIO = re.compile(r"^(\d{5}-?\d{3})\b")
_RE_DATA_INICIO = re.compile(r"^(\d{2}/\d{2}/\d{4}|\d{8})\b")
_RE_SEXO_INICIO = re.compile(r"^([MFmf12])\b")
_RE_ROTULO_SEGUINTE = re.compile(
    r"\s+(LOGRADOURO|ENDERECO|ENDEREÇO|NUMERO|NÚMERO|BAIRRO|COMPLEMENTO|"
    r"SEXO|ETNIA|RACA|RAÇA|TELEFONE|E-?MAIL|EMAIL|MUNICIPIO|DATA|CEP|"
    r"NOME|CNS)\b.*$",
    re.IGNORECASE,
)
# Corta valor no proximo rotulo da mesma linha (look-ahead)
_RE_SPLIT_PROXIMO_ROTULO = re.compile(
    r"\s+(?=(?:LOGRADOURO|ENDERECO|ENDEREÇO|NUMERO|NÚMERO|BAIRRO|COMPLEMENTO|"
    r"SEXO|ETNIA|RACA|RAÇA|TELEFONE|E-?MAIL|EMAIL|MUNICIPIO|DATA\s+DE|"
    r"CEP|NOME\s+DA|NOME\s+DO|CNS)\b)",
    re.IGNORECASE,
)

# Marcadores para extrair valor apos o rotulo do campo focado
_MARCAS_VALOR: dict[CampoApac, tuple[str, ...]] = {
    CampoApac.NOME: ("NOME",),
    CampoApac.NOME_MAE: ("NOME DA MAE", "NOME DA MÃE", "NOME DA MA"),
    CampoApac.RESPONSAVEL: ("NOME DO RESPONSAVEL", "NOME DO RES", "RESPONSAVEL"),
    CampoApac.CEP: ("CEP",),
    CampoApac.LOGRADOURO: ("LOGRADOURO",),
    CampoApac.ENDERECO: ("ENDERECO", "ENDEREÇO"),
    CampoApac.NUMERO: ("NUMERO", "NÚMERO"),
    CampoApac.COMPLEMENTO: ("COMPLEMENTO",),
    CampoApac.BAIRRO: ("BAIRRO",),
    CampoApac.TELEFONE: ("TELEFONE", "DDD"),
    CampoApac.EMAIL: ("E-MAIL", "EMAIL"),
    CampoApac.NASCIMENTO: ("NASCIMENTO", "DATA DE NASC"),
    CampoApac.SEXO: ("SEXO",),
    # RACA fica na linha do MUNICIPIO; ETNIA na linha do nascimento
    CampoApac.ETNIA_RACA: ("RACA", "RAÇA", "ETNIA"),
    CampoApac.MUNICIPIO: ("MUNICIPIO", "MUNICÍPIO"),
    CampoApac.COD_PROCEDIMENTO: (
        "COD. PROCEDIMENTO",
        "COD.PROCEDIMENTO",
        "COD PROCEDIMENTO",
        "CODIGO DO PROCEDIMENTO",
    ),
    CampoApac.CBO: ("C.B.O.", "CBO"),
    CampoApac.QUANTIDADE: ("QUANTIDADE", "QUANT."),
    CampoApac.CNS_EXECUTANTE: ("CNS EXECUTANTE", "CNS EXEC"),
    CampoApac.EQUIPE: ("EQUIPE",),
    CampoApac.SERVICO: ("SERVICO", "SERVIÇO"),
    CampoApac.CLASSIFICACAO: ("CLASSIFICACAO", "CLASSIF.", "CLASSIF"),
    CampoApac.MOTIVO_SAIDA: ("MOTIVO SAIDA", "MOTIVO SAÍDA"),
    CampoApac.DATA_ALTA: (
        "DATA ALTA/OBITO",
        "DATA ALTA",
        "MUDANCA PROCED",
        "MUDANÇA PROCED",
    ),
    CampoApac.CID_PRINCIPAL: (
        "C.I.D. PRINCIPAL",
        "CID PRINCIPAL",
        "CID PRINC.",
    ),
    CampoApac.CID_SECUNDARIO: ("SECUNDARIO",),
    CampoApac.CAUSAS_ASSOCIADAS: ("CAUSAS ASSOCIADAS",),
    CampoApac.CARATER_ATEND: ("CARATER ATEND", "CARATER ATEND."),
    CampoApac.CNS_SOLICITANTE: ("CNS",),
    CampoApac.CNS_AUTORIZADOR: ("CNS",),
    CampoApac.DT_SOLICITACAO: ("DT.SOLICITACAO", "DT SOLICITACAO"),
    CampoApac.DT_AUTORIZACAO: ("DT.AUTORIZACAO", "DT AUTORIZACAO"),
    CampoApac.COD_ORGAO_EMISS: (
        "COD.ORGAO EMISS",
        "COD.ORGAO",
        "COD ORGAO EMISS",
    ),
}


def _valor_apos_marcas(linha: str, marcas: tuple[str, ...]) -> str | None:
    """Valor apos o rotulo (respeita multi-campo na mesma linha)."""
    raw = _linha_para_cursor(linha)
    raw_u = raw.upper()
    best: tuple[int, int] | None = None  # pos, len
    for marca in marcas:
        mu = marca.upper()
        pos = raw_u.find(mu)
        if pos < 0:
            continue
        # Prefere o marcador mais a direita (RACA depois de MUNICIPIO)
        # e, no empate de posicao, o mais longo
        if best is None or pos > best[0] or (pos == best[0] and len(mu) > best[1]):
            best = (pos, len(mu))
    if best is None:
        return None
    pos, plen = best
    after = raw[pos + plen :]
    after = re.sub(r"^[\s.:]+", "", after)
    after = _RE_SPLIT_PROXIMO_ROTULO.split(after, maxsplit=1)[0]
    after = _RE_BOX.sub(" ", after)
    return " ".join(after.split()).strip()


def extrair_valor_campo_linha(
    linha: str,
    campo: CampoApac | None = None,
) -> str:
    """
    Extrai o valor editavel de uma linha do formulario Magnético.
    Se `campo` for informado, isola o segmento daquele rotulo
    (ex.: MUNICIPIO+RACA na mesma linha -> so o codigo da raca).
    """
    if campo is not None and campo in _MARCAS_VALOR:
        por_rotulo = _valor_apos_marcas(linha, _MARCAS_VALOR[campo])
        if por_rotulo is not None:
            # RACA: "03 ??" -> "03"
            if campo == CampoApac.ETNIA_RACA:
                m = re.match(r"^(0?[1-5])\b", por_rotulo)
                if m:
                    return m.group(1)
            if campo == CampoApac.SEXO:
                m = re.match(r"^([MFmf12])\b", por_rotulo)
                if m:
                    return m.group(1).upper()
            if campo == CampoApac.NASCIMENTO:
                m = re.match(r"^(\d{2}/\d{2}/\d{4}|\d{8})\b", por_rotulo)
                if m:
                    return m.group(1)
            if campo == CampoApac.CEP:
                m = re.match(r"^(\d{5}-?\d{3})\b", por_rotulo)
                if m:
                    return m.group(1)
            return por_rotulo

    t = _RE_BOX.sub(" ", linha or "")
    t = " ".join(t.split()).strip()
    if not t:
        return ""
    # Data / CEP / sexo no inicio + proximo rotulo na mesma linha
    m_data = _RE_DATA_INICIO.match(t)
    if m_data and _RE_ROTULO_SEGUINTE.search(t):
        return m_data.group(1)
    m_cep = _RE_CEP_INICIO.match(t)
    if m_cep and _RE_ROTULO_SEGUINTE.search(t):
        return m_cep.group(1)
    m_cep2 = _RE_CEP_INICIO.match(t)
    if m_cep2 and len(t) <= 12:
        return m_cep2.group(1)
    m_sexo = _RE_SEXO_INICIO.match(t)
    if m_sexo and _RE_ROTULO_SEGUINTE.search(t):
        return m_sexo.group(1).upper()
    # Corta rotulo seguinte colado na mesma linha
    t_cortado = _RE_ROTULO_SEGUINTE.sub("", t).strip()
    if t_cortado and t_cortado != t:
        t = t_cortado
        m_data2 = _RE_DATA_INICIO.match(t)
        if m_data2:
            return m_data2.group(1)
        m_sexo2 = _RE_SEXO_INICIO.match(t)
        if m_sexo2 and len(t) <= 3:
            return m_sexo2.group(1).upper()
    m = _RE_DOTS.search(t)
    if m:
        return (m.group(1) or "").strip()
    for sep in (":", "："):
        if sep in t:
            # Preferir trecho ANTES do rotulo seguinte; senao depois do sep
            antes = t.split(sep, 1)[0].strip()
            if _RE_DATA_INICIO.match(antes):
                return _RE_DATA_INICIO.match(antes).group(1)
            if _RE_CEP_INICIO.match(antes):
                return _RE_CEP_INICIO.match(antes).group(1)
            return t.split(sep, 1)[-1].strip()
    return t


def _linha_limpa_campo(linha: str) -> str:
    t = _RE_BOX.sub(" ", linha or "")
    return " ".join(t.split()).strip()


def _linha_para_cursor(linha: str) -> str:
    """Box -> espaco; preserva espacos internos para alinhar com cursor_x do buffer."""
    return _RE_BOX.sub(" ", linha or "")


def identificar_campo_linha(linha: str, cursor_x: int | None = None) -> CampoApac:
    """
    Identifica o campo focado a partir do texto da linha do cursor.
    Se a linha tiver varios rotulos, usa cursor_x (indice na linha lida) para
    escolher o segmento — posicoes medidas na linha com espacos preservados.
    """
    t = _linha_limpa_campo(linha)
    if not t:
        return CampoApac.DESCONHECIDO
    upper = t.upper()
    # Posicoes alinhadas ao buffer (cx); nao usar string colapsada
    raw = _linha_para_cursor(linha)
    raw_u = raw.upper()

    # Valor tipico de municipio/IBGE sem rotulo explicito (linha so com o valor)
    if _RE_MUNICIPIO_VALOR.match(upper) and "RACA" not in upper and "RAÇA" not in upper:
        return CampoApac.MUNICIPIO

    # Linha CEP + LOGRADOURO (print: "CEP : 65041235" + "LOGRADOURO : 81 RUA")
    if ("CEP" in upper or _RE_CEP_INICIO.match(t)) and "LOGRADOURO" in upper:
        pos_log = raw_u.find("LOGRADOURO")
        if cursor_x is not None and pos_log >= 0 and cursor_x >= pos_log:
            return CampoApac.LOGRADOURO
        return CampoApac.CEP

    # Linha ENDERECO + NUMERO
    if ("ENDERECO" in upper or "ENDEREÇO" in upper) and re.search(
        r"\bNUMERO\b|\bNÚMERO\b", upper
    ):
        pos_num = max(raw_u.find("NUMERO"), raw_u.find("NÚMERO"))
        if cursor_x is not None and pos_num >= 0 and cursor_x >= pos_num:
            return CampoApac.NUMERO
        return CampoApac.ENDERECO

    # Linha COMPLEMENTO + BAIRRO
    if "COMPLEMENTO" in upper and "BAIRRO" in upper:
        pos_bai = raw_u.find("BAIRRO")
        if cursor_x is not None and pos_bai >= 0 and cursor_x >= pos_bai:
            return CampoApac.BAIRRO
        return CampoApac.COMPLEMENTO

    # Linha TELEFONE + E-MAIL
    if "TELEFONE" in upper and ("EMAIL" in upper or "E-MAIL" in upper):
        pos_mail = max(raw_u.find("E-MAIL"), raw_u.find("EMAIL"))
        if cursor_x is not None and pos_mail >= 0 and cursor_x >= pos_mail:
            return CampoApac.EMAIL
        return CampoApac.TELEFONE

    # Linha QUANTIDADE + CNS EXECUTANTE (print: mesma linha horizontal)
    if "QUANTIDADE" in upper and "CNS" in upper:
        pos_cns = raw_u.find("CNS")
        if cursor_x is not None and pos_cns >= 0 and cursor_x >= pos_cns:
            return CampoApac.CNS_EXECUTANTE
        return CampoApac.QUANTIDADE

    # Linha MUNICIPIO + RACA (print real — RACA NAO e ETNIA da linha de baixo)
    if "MUNICIPIO" in upper and ("RACA" in upper or "RAÇA" in upper):
        pos_raca = max(raw_u.find("RACA"), raw_u.find("RAÇA"))
        if cursor_x is not None and pos_raca >= 0 and cursor_x >= pos_raca:
            return CampoApac.ETNIA_RACA
        return CampoApac.MUNICIPIO

    # Linha NASCIMENTO + SEXO + ETNIA (print: data/sexo/etnia — sem RACA)
    if (
        "NASCIMENTO" in upper or _RE_DATA_INICIO.match(t)
    ) and ("SEXO" in upper or "ETNIA" in upper):
        pos_sexo = raw_u.find("SEXO")
        pos_etnia = raw_u.find("ETNIA")
        if cursor_x is not None:
            if pos_etnia >= 0 and cursor_x >= pos_etnia:
                return CampoApac.ETNIA_RACA
            if pos_sexo >= 0 and cursor_x >= pos_sexo:
                return CampoApac.SEXO
            return CampoApac.NASCIMENTO
        return CampoApac.NASCIMENTO

    # Achados: (posicao_inicio na linha raw, campo, tamanho_marcador)
    achados: list[tuple[int, CampoApac, int]] = []
    for campo, marcas in _ROTULOS_CAMPO:
        for marca in marcas:
            m = marca.upper()
            pos = raw_u.find(m)
            if pos < 0:
                pos = upper.find(m)  # fallback colapsado
            if pos >= 0:
                # Evita NOME casar dentro de NOME DA MAE / RESPONSAVEL (e truncagens)
                if campo == CampoApac.NOME and (
                    "NOME DA MAE" in upper
                    or "NOME DA MÃE" in upper
                    or "NOME DA MA" in upper
                    or "RESPONSAVEL" in upper
                    or "RESPONSÁVEL" in upper
                    or "NOME DO RES" in upper
                ):
                    continue
                # CNS generico da SOLICITACAO vs CNS EXECUTANTE
                if campo in (
                    CampoApac.CNS_SOLICITANTE,
                    CampoApac.CNS_AUTORIZADOR,
                ) and ("CNS EXEC" in upper or "CNS EXECUTANTE" in upper):
                    continue
                # NUMERO generico vs NUMERO APAC no cabecalho — ok na identificacao
                achados.append((pos, campo, len(m)))

    # Preferir marcador mais longo no mesmo inicio (ex.: NOME DO RES > NOME)
    if achados:
        por_pos: dict[int, tuple[int, CampoApac, int]] = {}
        for pos, campo, tam in achados:
            prev = por_pos.get(pos)
            if prev is None or tam > prev[2]:
                por_pos[pos] = (pos, campo, tam)
        achados = list(por_pos.values())

    if not achados:
        # Heuristicas sem rotulo
        if _RE_CEP_INICIO.match(t) and "LOGRADOURO" in upper:
            return CampoApac.CEP
        if _RE_DATA_INICIO.match(t) and "SEXO" in upper:
            # Sem cx: assume nascimento (esquerda)
            return CampoApac.NASCIMENTO
        if "@" in t:
            return CampoApac.EMAIL
        return CampoApac.DESCONHECIDO

    # Um unico rotulo
    if len(achados) == 1:
        return achados[0][1]

    # Varios rotulos: escolher pelo cursor_x (rotulo imediatamente a esquerda do cursor)
    achados.sort(key=lambda x: x[0])
    if cursor_x is not None and cursor_x >= 0:
        # Preferir o ultimo rotulo com pos <= cursor_x (posicoes na linha raw)
        escolhido = achados[0][1]
        for pos, campo, _tam in achados:
            if pos <= cursor_x:
                escolhido = campo
            else:
                break
        return escolhido

    # Sem cursor: prioridade especial para linhas conhecidas do log
    campos = {c for _, c, _ in achados}
    if CampoApac.CEP in campos and CampoApac.LOGRADOURO in campos:
        return CampoApac.CEP
    if CampoApac.COMPLEMENTO in campos and CampoApac.BAIRRO in campos:
        return CampoApac.COMPLEMENTO
    if CampoApac.MUNICIPIO in campos and CampoApac.ETNIA_RACA in campos:
        return CampoApac.MUNICIPIO
    if CampoApac.ENDERECO in campos and CampoApac.NUMERO in campos:
        return CampoApac.ENDERECO
    if CampoApac.TELEFONE in campos and CampoApac.EMAIL in campos:
        return CampoApac.TELEFONE
    if CampoApac.QUANTIDADE in campos and CampoApac.CNS_EXECUTANTE in campos:
        return CampoApac.QUANTIDADE
    if CampoApac.MOTIVO_SAIDA in campos and CampoApac.DATA_ALTA in campos:
        return CampoApac.MOTIVO_SAIDA
    if CampoApac.NASCIMENTO in campos or (
        _RE_DATA_INICIO.match(t) and CampoApac.SEXO in campos
    ):
        return CampoApac.NASCIMENTO
    if CampoApac.SEXO in campos and CampoApac.ETNIA_RACA in campos:
        return CampoApac.SEXO
    # Primeiro rotulo da esquerda
    return achados[0][1]


def campo_compativel(
    atual: CampoApac,
    esperado: CampoApac,
    *,
    linha: str = "",
) -> bool:
    """
    True se o campo lido satisfaz o esperado.
    Em linhas multi-rotulo (nascimento/sexo/etnia), aceita se o rotulo
    esperado estiver presente na linha.
    """
    if atual == esperado:
        return True
    upper = _linha_limpa_campo(linha).upper()
    if not upper:
        return False
    # Em linhas multi-rotulo: se o parceiro tambem esta na linha, so aceita
    # quando a identificacao (cx) ja apontou o campo esperado.
    def _tem(*marcas: str) -> bool:
        return any(m in upper for m in marcas)

    if esperado == CampoApac.ETNIA_RACA and _tem("ETNIA", "RACA", "RAÇA"):
        # MUNICIPIO+RACA ou NASCIMENTO|SEXO|ETNIA: so com cx no ETNIA/RACA
        if "MUNICIPIO" in upper or _tem("NASCIMENTO", "SEXO") or _tem(
            "DATA DE NASC"
        ):
            return atual == CampoApac.ETNIA_RACA
        return True
    if esperado == CampoApac.SEXO and "SEXO" in upper:
        # Linha NASCIMENTO|SEXO|ETNIA: so aceita se cx ja apontou SEXO
        if _tem("NASCIMENTO", "DATA DE NASC") or _tem("ETNIA", "RACA", "RAÇA"):
            return atual == CampoApac.SEXO
        return True
    if esperado == CampoApac.NASCIMENTO and (
        "NASCIMENTO" in upper or _RE_DATA_INICIO.match(_linha_limpa_campo(linha))
    ):
        return True
    if esperado == CampoApac.CEP and (
        "CEP" in upper
        or (_RE_CEP_INICIO.match(_linha_limpa_campo(linha)) and "LOGRADOURO" in upper)
    ):
        return True
    if esperado == CampoApac.LOGRADOURO and "LOGRADOURO" in upper:
        return True
    if esperado == CampoApac.COMPLEMENTO and "COMPLEMENTO" in upper:
        return True
    if esperado == CampoApac.BAIRRO and "BAIRRO" in upper:
        if "COMPLEMENTO" in upper:
            return atual == CampoApac.BAIRRO
        return True
    if esperado == CampoApac.ENDERECO and _tem("ENDERECO", "ENDEREÇO"):
        return True
    if esperado == CampoApac.NUMERO and _tem("NUMERO", "NÚMERO"):
        if _tem("ENDERECO", "ENDEREÇO"):
            return atual == CampoApac.NUMERO
        return True
    if esperado == CampoApac.TELEFONE and "TELEFONE" in upper:
        return True
    if esperado == CampoApac.EMAIL and _tem("EMAIL", "E-MAIL"):
        if "TELEFONE" in upper:
            return atual == CampoApac.EMAIL
        return True
    if esperado == CampoApac.MUNICIPIO and "MUNICIPIO" in upper:
        if _tem("RACA", "RAÇA"):
            return atual == CampoApac.MUNICIPIO
        return True
    if esperado == CampoApac.COD_PROCEDIMENTO:
        if "PROCEDIMENTO" in upper or "COD.PROCEDIMENTO" in upper:
            return True
        # Foco default na tela: linha so com mascara (.. . . -) sem rotulo
        if atual in (CampoApac.COD_PROCEDIMENTO, CampoApac.DESCONHECIDO):
            if not upper or re.fullmatch(r"[\d.\-\s/]*", upper):
                return True
        return False
    if esperado == CampoApac.CBO and _tem("C.B.O.", "CBO"):
        return True
    if esperado == CampoApac.QUANTIDADE and _tem("QUANTIDADE", "QUANT."):
        # Mesma linha que CNS: so aceita se o cx ja apontou QUANTIDADE
        if "CNS" in upper:
            return atual == CampoApac.QUANTIDADE
        return True
    if esperado == CampoApac.CNS_EXECUTANTE and "CNS" in upper:
        # Mesma linha que QUANTIDADE: nao digitar CNS no campo quantidade
        if _tem("QUANTIDADE", "QUANT."):
            return atual == CampoApac.CNS_EXECUTANTE
        return True
    if esperado == CampoApac.EQUIPE and "EQUIPE" in upper:
        return True
    if esperado == CampoApac.SERVICO and _tem("SERVICO", "SERVIÇO"):
        return True
    if esperado == CampoApac.CLASSIFICACAO and _tem(
        "CLASSIFICACAO", "CLASSIF.", "CLASSIF"
    ):
        return True
    if esperado == CampoApac.MOTIVO_SAIDA and _tem(
        "MOTIVO SAIDA", "MOTIVO SAÍDA"
    ):
        if _tem("DATA ALTA", "DATA ALTA/OBITO"):
            return atual == CampoApac.MOTIVO_SAIDA
        return True
    if esperado == CampoApac.DATA_ALTA and _tem(
        "DATA ALTA", "DATA ALTA/OBITO", "MUDANCA PROCED", "MUDANÇA PROCED"
    ):
        if _tem("MOTIVO SAIDA", "MOTIVO SAÍDA"):
            return atual == CampoApac.DATA_ALTA
        return True
    if esperado == CampoApac.CID_PRINCIPAL and _tem(
        "C.I.D. PRINCIPAL", "CID PRINCIPAL", "CID PRINC."
    ):
        return True
    if esperado == CampoApac.CID_SECUNDARIO and "SECUNDARIO" in upper:
        return True
    if esperado == CampoApac.CAUSAS_ASSOCIADAS and "CAUSAS ASSOCIADAS" in upper:
        return True
    if esperado == CampoApac.CARATER_ATEND and "CARATER ATEND" in upper:
        return True
    if esperado in (
        CampoApac.CNS_SOLICITANTE,
        CampoApac.CNS_AUTORIZADOR,
    ) and "CNS" in upper:
        # Nao confundir com CNS EXECUTANTE da tela PROCEDIMENTOS
        if "CNS EXEC" in upper or "CNS EXECUTANTE" in upper:
            return False
        return True
    if esperado == CampoApac.DT_SOLICITACAO and _tem(
        "DT.SOLICITACAO", "DT SOLICITACAO"
    ):
        return True
    if esperado == CampoApac.DT_AUTORIZACAO and _tem(
        "DT.AUTORIZACAO", "DT AUTORIZACAO"
    ):
        return True
    if esperado == CampoApac.COD_ORGAO_EMISS and _tem(
        "COD.ORGAO EMISS", "COD.ORGAO", "COD ORGAO EMISS"
    ):
        return True
    if esperado == CampoApac.RESPONSAVEL and (
        "RESPONSAVEL" in upper
        or "RESPONSÁVEL" in upper
        or "NOME DO RES" in upper
    ):
        return True
    if esperado == CampoApac.NOME_MAE and (
        "NOME DA MAE" in upper or "NOME DA MÃE" in upper or "NOME DA MA" in upper
    ):
        return True
    return False


def identificar_campo_cursor(pids: list[int]) -> tuple[CampoApac, str, int]:
    """
    Le linha do cursor e identifica o campo.
    Retorna (campo, linha, cursor_x).
    """
    if not pids:
        raise ConsoleScreenError("APAC.exe nao esta em execucao.")
    erros: list[str] = []
    for pid in pids:
        try:
            linha, cx, _cy = ler_linha_e_cursor(pid)
            campo = identificar_campo_linha(linha, cursor_x=cx)
            log.debug(
                "Campo cursor PID=%s x=%s campo=%s linha=%r",
                pid,
                cx,
                campo.value,
                linha[:80],
            )
            return campo, linha, cx
        except ConsoleScreenError as exc:
            erros.append(f"PID {pid}: {exc}")
    raise ConsoleScreenError(
        "Nao foi possivel identificar campo no cursor. Detalhes: " + " | ".join(erros)
    )


def ler_linha_e_cursor(pid: int) -> tuple[str, int, int]:
    """
    Le a linha do buffer onde esta o cursor (sem enviar teclas).
    Retorna (linha, cursor_x, cursor_y).
    """
    if pid <= 0:
        raise ConsoleScreenError("PID invalido para leitura do cursor.")

    k32 = _kernel32()
    k32.FreeConsole()
    attached = False
    try:
        if not k32.AttachConsole(wintypes.DWORD(pid)):
            err = ctypes.GetLastError()
            raise ConsoleScreenError(
                f"AttachConsole falhou para PID {pid} (WinError {err})."
            )
        attached = True

        h_out = k32.GetStdHandle(wintypes.DWORD(_STD_OUTPUT_HANDLE & 0xFFFFFFFF))
        if not h_out or h_out == wintypes.HANDLE(-1).value:
            raise ConsoleScreenError("GetStdHandle(STD_OUTPUT) falhou.")

        info = CONSOLE_SCREEN_BUFFER_INFO()
        if not k32.GetConsoleScreenBufferInfo(h_out, ctypes.byref(info)):
            err = ctypes.GetLastError()
            raise ConsoleScreenError(
                f"GetConsoleScreenBufferInfo falhou (WinError {err})."
            )

        cx = int(info.dwCursorPosition.X)
        cy = int(info.dwCursorPosition.Y)
        left = int(info.srWindow.Left)
        right = int(info.srWindow.Right)
        width = right - left + 1
        if width <= 0:
            raise ConsoleScreenError("Largura da janela do console invalida.")

        buf = ctypes.create_unicode_buffer(width + 1)
        nread = wintypes.DWORD(0)
        ok = k32.ReadConsoleOutputCharacterW(
            h_out,
            buf,
            wintypes.DWORD(width),
            COORD(left, cy),
            ctypes.byref(nread),
        )
        if not ok:
            err = ctypes.GetLastError()
            raise ConsoleScreenError(
                f"ReadConsoleOutputCharacterW (cursor) falhou (WinError {err})."
            )
        # Nao rstrip agressivo: preserva colunas para alinhar cx com a linha
        linha = buf.value[: int(nread.value)].rstrip("\x00")
        # cx relativo ao inicio da string lida (srWindow.Left)
        return linha, max(0, cx - left), cy
    finally:
        if attached:
            k32.FreeConsole()
        k32.AttachConsole(wintypes.DWORD(_ATTACH_PARENT_PROCESS))


def ler_valor_campo_cursor(
    pids: list[int],
    *,
    campo: CampoApac | None = None,
) -> str:
    """
    Valor do campo focado via linha do cursor (sem Home/Shift+End).
    Se `campo` for omitido, identifica pelo rotulo/cx e extrai o segmento certo.
    """
    if not pids:
        raise ConsoleScreenError("APAC.exe nao esta em execucao.")
    erros: list[str] = []
    for pid in pids:
        try:
            linha, cx, cy = ler_linha_e_cursor(pid)
            campo_lido = campo if campo is not None else identificar_campo_linha(
                linha, cursor_x=cx
            )
            valor = extrair_valor_campo_linha(linha, campo=campo_lido)
            log.debug(
                "Cursor campo PID=%s y=%s x=%s campo=%s linha=%r valor=%r",
                pid,
                cy,
                cx,
                campo_lido.value if isinstance(campo_lido, CampoApac) else campo_lido,
                linha[:80],
                valor[:60],
            )
            return valor
        except ConsoleScreenError as exc:
            erros.append(f"PID {pid}: {exc}")
    raise ConsoleScreenError(
        "Nao foi possivel ler campo no cursor. Detalhes: " + " | ".join(erros)
    )


def classificar_tela(texto: str) -> TelaApac:
    """
    Classifica a tela a partir do texto do buffer (marcadores iniciais;
    calibrar com dump-apac-screen se necessario).
    """
    t = (texto or "").strip()
    if not t:
        return TelaApac.DESCONHECIDA
    upper = t.upper()

    # Antes de PROCEDIMENTOS: "CID PRINC" tambem aparece em DADOS COMPLEMENTARES
    if "DADOS COMPLEMENTARES" in upper:
        return TelaApac.DADOS_COMPLEMENTARES

    if (
        "SOLICITACAO" in upper
        and ("AUTORIZACAO" in upper or "AUTORIZAÇÃO" in upper)
    ) or "CARATER ATEND" in upper:
        return TelaApac.SOLICITACAO

    if (
        "PROCEDIMENTOS REALIZADOS" in upper
        or "COD.PROCEDIMENTO" in upper
        or (
            "CID PRINC" in upper
            and "DADOS COMPLEMENTARES" not in upper
            and "C.I.D. PRINCIPAL" not in upper
        )
        or _RE_COD_PROCEDIMENTO.search(t)
    ):
        return TelaApac.PROCEDIMENTOS

    # Dump real: "MENU - PRINCIPAL" (com hifen); submenu ainda tem esse cabecalho
    if (
        "MENU - PRINCIPAL" in upper
        or "MENU PRINCIPAL" in upper
        or (
            "A.P.A.C" in upper
            and "ATUALIZ" not in upper
            and "IDENTIFIC" not in upper
            and "SOLICITACAO" not in upper
        )
    ):
        return TelaApac.MENU

    if (
        "ATUALIZACAO DE APAC" in upper
        or "ATUALIZAÇÃO DE APAC" in upper
        or "ATUALIZACAO" in upper
        or "ATUALIZAÇÃO" in upper
    ):
        return TelaApac.LISTA

    if (
        "IDENTIFIC" in upper
        or "SITUACAO DE RUA" in upper
        or "SITUAÇÃO DE RUA" in upper
        or (
            "NUMERO" in upper
            and "APAC" in upper
            and "MENU - PRINCIPAL" not in upper
            and "MENU PRINCIPAL" not in upper
        )
        or "NOME DA MAE" in upper
        or "NOME DA MÃE" in upper
        or "DATA DE NASCIMENTO" in upper
    ):
        return TelaApac.IDENTIFICACAO

    return TelaApac.DESCONHECIDA


def preview_tela(texto: str, max_chars: int = 200) -> str:
    compacto = " | ".join(
        ln.strip() for ln in (texto or "").splitlines() if ln.strip()
    )
    if len(compacto) > max_chars:
        return compacto[: max_chars - 3] + "..."
    return compacto


def tela_compativel(atual: TelaApac, esperada: TelaApac) -> bool:
    return atual == esperada
