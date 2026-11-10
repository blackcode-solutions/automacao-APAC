"""Leitura do arquivo SET/TXT (layout INTERNO) — espelho inverso de set_layout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from apac_bot.set_layout import (
    EOF_SUB,
    LEN_CID,
    LEN_CORPO,
    LEN_HEADER,
    LEN_PROC,
    LINE_ENDING,
    CidGeralSet,
    CorpoApacSet,
    PacienteSetRecord,
    ProcedimentoSet,
    SetLayoutError,
)


@dataclass(frozen=True, slots=True)
class ParsedProc:
    competencia: str
    numeracao: str
    codigo_procedimento: str
    cbo: str
    quantidade: str


@dataclass(frozen=True, slots=True)
class ParsedPaciente:
    competencia: str
    numeracao: str
    nome: str
    nascimento: str  # AAAAMMDD
    procedimentos: tuple[ParsedProc, ...]


@dataclass(frozen=True, slots=True)
class ParsedSet:
    competencia: str
    orgao_origem: str
    pacientes: tuple[ParsedPaciente, ...]


def _slice(line: str, start: int, length: int) -> str:
    end = start + length
    if len(line) < end:
        raise SetLayoutError(
            f"linha curta (len={len(line)}, precisa {end}): tipo={line[:2]!r}"
        )
    return line[start:end]


def _lines_from_bytes(blob: bytes) -> list[str]:
    data = blob
    if data.endswith(EOF_SUB):
        data = data[: -len(EOF_SUB)]
    text = data.decode("latin-1")
    # Aceita CRLF (canônico) ou LF solto.
    if LINE_ENDING.decode("ascii") in text:
        parts = text.split(LINE_ENDING.decode("ascii"))
    else:
        parts = text.split("\n")
    return [p for p in parts if p]


def _parse_header(line: str) -> tuple[str, str]:
    if len(line) != LEN_HEADER:
        raise SetLayoutError(f"cabecalho len={len(line)} esperado {LEN_HEADER}")
    if not line.startswith("01#APAC"):
        raise SetLayoutError(f"cabecalho invalido: prefixo={line[:7]!r}")
    competencia = _slice(line, 7, 6).strip()
    orgao = _slice(line, 23, 30).strip()
    return competencia, orgao


def _parse_corpo_14(line: str) -> tuple[str, str, str, str]:
    if len(line) != LEN_CORPO:
        raise SetLayoutError(f"corpo 14 len={len(line)} esperado {LEN_CORPO}")
    if not line.startswith("14"):
        raise SetLayoutError(f"esperado tipo 14, obtido {line[:2]!r}")
    competencia = _slice(line, 2, 6).strip()
    numeracao = _slice(line, 8, 13).strip()
    nome = _slice(line, 57, 30).strip()
    nascimento = _slice(line, 177, 8).strip()
    return competencia, numeracao, nome, nascimento


def _parse_proc_13(line: str) -> ParsedProc:
    if len(line) != LEN_PROC:
        raise SetLayoutError(f"proc 13 len={len(line)} esperado {LEN_PROC}")
    if not line.startswith("13"):
        raise SetLayoutError(f"esperado tipo 13, obtido {line[:2]!r}")
    qtd_raw = _slice(line, 37, 7).strip()
    qtd_digits = "".join(ch for ch in qtd_raw if ch.isdigit())
    if qtd_digits:
        quantidade = str(int(qtd_digits))
    else:
        quantidade = qtd_raw or "1"
    return ParsedProc(
        competencia=_slice(line, 2, 6).strip(),
        numeracao=_slice(line, 8, 13).strip(),
        codigo_procedimento=_slice(line, 21, 10).strip(),
        cbo=_slice(line, 31, 6).strip(),
        quantidade=quantidade,
    )


def parse_set_bytes(blob: bytes) -> ParsedSet:
    """Interpreta bytes latin-1 do Magnético / gerar-set."""
    lines = _lines_from_bytes(blob)
    if not lines:
        raise SetLayoutError("arquivo SET vazio")

    competencia_hdr, orgao = _parse_header(lines[0])
    pacientes: list[ParsedPaciente] = []
    i = 1
    while i < len(lines):
        line = lines[i]
        tipo = line[:2]
        if tipo == "14":
            comp, num, nome, nasc = _parse_corpo_14(line)
            i += 1
            if i < len(lines) and lines[i].startswith("06"):
                if len(lines[i]) != LEN_CID:
                    raise SetLayoutError(
                        f"cid 06 len={len(lines[i])} esperado {LEN_CID}"
                    )
                i += 1
            procs: list[ParsedProc] = []
            while i < len(lines) and lines[i].startswith("13"):
                procs.append(_parse_proc_13(lines[i]))
                i += 1
            if not procs:
                raise SetLayoutError(
                    f"paciente {num} sem procedimento tipo 13"
                )
            pacientes.append(
                ParsedPaciente(
                    competencia=comp or competencia_hdr,
                    numeracao=num,
                    nome=nome,
                    nascimento=nasc,
                    procedimentos=tuple(procs),
                )
            )
            continue
        raise SetLayoutError(f"linha inesperada tipo={tipo!r} pos={i}")

    return ParsedSet(
        competencia=competencia_hdr,
        orgao_origem=orgao,
        pacientes=tuple(pacientes),
    )


def parse_set_file(path: Path) -> ParsedSet:
    """Lê path .SET / .TXT e devolve estrutura tipada."""
    dest = Path(path)
    try:
        blob = dest.read_bytes()
    except OSError as exc:
        raise SetLayoutError(f"falha ao ler SET: {exc}") from exc
    return parse_set_bytes(blob)


def numeracoes_no_set(parsed: ParsedSet) -> frozenset[str]:
    """Conjunto de numerações APAC (13 dígitos) presentes no arquivo."""
    return frozenset(p.numeracao for p in parsed.pacientes)


def procs_por_numeracao(
    parsed: ParsedSet,
) -> dict[str, Sequence[ParsedProc]]:
    return {p.numeracao: p.procedimentos for p in parsed.pacientes}


def _slice1(line: str, ini: int, fim: int) -> str:
    """Fatia posições 1-based inclusivas (igual ao golden test)."""
    return line[ini - 1 : fim]


def _parse_corpo_14_full(line: str) -> CorpoApacSet:
    if len(line) != LEN_CORPO or not line.startswith("14"):
        raise SetLayoutError(f"corpo 14 invalido: len={len(line)}")
    return CorpoApacSet(
        competencia=_slice1(line, 3, 8),
        numeracao=_slice1(line, 9, 21),
        uf_ibge=_slice1(line, 22, 23),
        cnes=_slice1(line, 24, 30),
        data_proc=_slice1(line, 31, 38),
        data_ini_val=_slice1(line, 39, 46),
        data_fim_val=_slice1(line, 47, 54),
        tipo_atendimento=_slice1(line, 55, 56),
        tipo_apac=_slice1(line, 57, 57),
        nome=_slice1(line, 58, 87).rstrip(),
        nome_mae=_slice1(line, 88, 117).rstrip(),
        logradouro=_slice1(line, 118, 147).rstrip(),
        numero=_slice1(line, 148, 152).rstrip(),
        complemento=_slice1(line, 153, 162),
        cep=_slice1(line, 163, 170),
        municipio_ibge=_slice1(line, 171, 177).rstrip(),
        nascimento=_slice1(line, 178, 185),
        sexo=_slice1(line, 186, 186),
        medico_responsavel=_slice1(line, 187, 216).rstrip(),
        codigo_procedimento=_slice1(line, 217, 226),
        motivo_saida=_slice1(line, 227, 228),
        data_obito_alta=_slice1(line, 229, 236),
        autorizador_nome=_slice1(line, 237, 266).rstrip(),
        cns_paciente=_slice1(line, 267, 281).strip(),
        cns_medico=_slice1(line, 282, 296),
        cns_autorizador=_slice1(line, 297, 311),
        cid_causas=_slice1(line, 312, 315),
        prontuario=_slice1(line, 316, 325),
        cnes_solicitante=_slice1(line, 326, 332),
        data_solicitacao=_slice1(line, 333, 340),
        data_autorizacao=_slice1(line, 341, 348),
        cod_orgao_emiss=_slice1(line, 349, 358),
        carater_atend=_slice1(line, 359, 360),
        apac_anterior=_slice1(line, 361, 373),
        raca=_slice1(line, 374, 375),
        nome_responsavel_pac=_slice1(line, 376, 405).rstrip(),
        nacionalidade=_slice1(line, 406, 408),
        etnia=_slice1(line, 409, 412),
        codigo_logradouro=_slice1(line, 413, 415),
        bairro=_slice1(line, 416, 445).rstrip(),
        ddd=_slice1(line, 446, 447),
        telefone=_slice1(line, 448, 456),
        email=_slice1(line, 457, 496),
        cns_executante=_slice1(line, 497, 511),
        cpf=_slice1(line, 512, 522),
        ine=_slice1(line, 523, 532),
        situacao_rua=_slice1(line, 533, 533),
        fonte_orcamentaria=_slice1(line, 534, 535),
        emendas=_slice1(line, 536, 536),
        sem_cpf=_slice1(line, 537, 537),
    )


def _parse_cid_06_full(line: str) -> CidGeralSet:
    if len(line) != LEN_CID or not line.startswith("06"):
        raise SetLayoutError(f"cid 06 invalido: len={len(line)}")
    return CidGeralSet(
        competencia=_slice1(line, 3, 8),
        numeracao=_slice1(line, 9, 21),
        cid_principal=_slice1(line, 22, 25).rstrip(),
    )


def _parse_proc_13_full(line: str) -> ProcedimentoSet:
    if len(line) != LEN_PROC or not line.startswith("13"):
        raise SetLayoutError(f"proc 13 invalido: len={len(line)}")
    return ProcedimentoSet(
        competencia=_slice1(line, 3, 8),
        numeracao=_slice1(line, 9, 21),
        codigo_procedimento=_slice1(line, 22, 31),
        cbo=_slice1(line, 32, 37),
        quantidade=_slice1(line, 38, 44),
        cnpj_cessao=_slice1(line, 45, 58),
        nota_fiscal=_slice1(line, 59, 64),
        cid_principal=_slice1(line, 65, 68),
        cid_secundario=_slice1(line, 69, 72),
        codigo_servico=_slice1(line, 73, 75),
        codigo_classificacao=_slice1(line, 76, 78),
        equipe_seq=_slice1(line, 79, 86),
        equipe_area=_slice1(line, 87, 90),
        cnes_terceiro=_slice1(line, 91, 97),
    )


def records_from_set_bytes(blob: bytes) -> tuple[str, list[PacienteSetRecord]]:
    """Reconstrói PacienteSetRecord a partir do SET gravado (round-trip layout)."""
    lines = _lines_from_bytes(blob)
    if not lines:
        raise SetLayoutError("arquivo SET vazio")
    if len(lines[0]) != LEN_HEADER:
        raise SetLayoutError(f"cabecalho len={len(lines[0])} esperado {LEN_HEADER}")
    competencia_hdr = _slice1(lines[0], 8, 13).strip()
    pacientes: list[PacienteSetRecord] = []
    i = 1
    while i < len(lines):
        if not lines[i].startswith("14"):
            raise SetLayoutError(f"linha inesperada tipo={lines[i][:2]!r}")
        corpo = _parse_corpo_14_full(lines[i])
        i += 1
        if i >= len(lines) or not lines[i].startswith("06"):
            raise SetLayoutError(f"paciente {corpo.numeracao} sem linha 06")
        cid = _parse_cid_06_full(lines[i])
        i += 1
        procs: list[ProcedimentoSet] = []
        while i < len(lines) and lines[i].startswith("13"):
            procs.append(_parse_proc_13_full(lines[i]))
            i += 1
        if not procs:
            raise SetLayoutError(f"paciente {corpo.numeracao} sem linha 13")
        pacientes.append(
            PacienteSetRecord(corpo=corpo, cid=cid, procedimentos=tuple(procs))
        )
    return competencia_hdr, pacientes


def records_from_set_file(path: Path) -> tuple[str, list[PacienteSetRecord]]:
    dest = Path(path)
    try:
        blob = dest.read_bytes()
    except OSError as exc:
        raise SetLayoutError(f"falha ao ler SET: {exc}") from exc
    return records_from_set_bytes(blob)
