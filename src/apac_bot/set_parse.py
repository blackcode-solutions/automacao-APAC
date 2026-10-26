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
