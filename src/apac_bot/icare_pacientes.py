"""Carga da planilha de pacientes ICARE (substitui consulta BIODATA)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from openpyxl import load_workbook

from apac_bot.config import AppConfig, config_dir, resolve_path
from apac_bot.models import PacienteDados
from apac_bot.normalize import (
    cell_as_text,
    inferir_sexo_por_nome,
    normalizar_nascimento_origem,
    sexo_para_apac,
)
from apac_bot.sheet import SheetError, nome_chave_prontuario, prontuario_so_digitos

log = logging.getLogger(__name__)
MODULE = "[icare-pacientes]"

# Sinônimos de cabeçalho (chave interna → tokens aceitos após normalização).
_COL_SYNONYMS: dict[str, tuple[str, ...]] = {
    "PRONTUARIO": ("prontuarios", "prontuario"),
    "PACIENTE": ("paciente",),
    "CPF": ("cpf",),
    "NASCIMENTO": (
        "data nascimento",
        "data_nascimento",
        "nascimento",
        "dt nascimento",
    ),
    "GENERO": ("genero", "sexo"),
    "CEP": ("cep",),
    "ENDERECO": ("endereco", "logradouro"),
    "NUMERO": ("numero", "num"),
    "COMPLEMENTO": ("complemento",),
    "BAIRRO": ("bairro",),
    "NOME_MAE": (
        "nome da mae",
        "nome da mãe",
        "nome_mae",
        "nomemae",
        "mae",
        "mãe",
    ),
}


class IcareSheetError(Exception):
    """Falha ao ler planilha de pacientes ICARE."""


def _hdr_key(h: Any) -> str:
    base = nome_chave_prontuario(cell_as_text(h))
    return base.replace("_", " ")


def _resolve_col_indices(
    headers_raw: list[Any], colunas_cfg: dict[str, str]
) -> dict[str, int]:
    indices: dict[str, int] = {}
    header_keys = [_hdr_key(h) for h in headers_raw]

    for chave_interna, sinonimos in _COL_SYNONYMS.items():
        rotulo = str(colunas_cfg.get(chave_interna) or "").strip()
        alvos: set[str] = set(sinonimos)
        if rotulo:
            alvos.add(_hdr_key(rotulo))
        for j, hk in enumerate(header_keys):
            if not hk:
                continue
            if hk in alvos:
                indices[chave_interna] = j
                break
            for alvo in alvos:
                if hk.startswith(alvo) or alvo.startswith(hk):
                    indices[chave_interna] = j
                    break
            if chave_interna in indices:
                break

    if "PRONTUARIO" not in indices:
        raise IcareSheetError(
            f"{MODULE} coluna de prontuário não encontrada no cabeçalho."
        )
    if "PACIENTE" not in indices:
        raise IcareSheetError(
            f"{MODULE} coluna paciente não encontrada no cabeçalho."
        )
    return indices


def _cell(row: tuple[Any, ...], idx: Optional[int]) -> str:
    if idx is None or idx >= len(row):
        return ""
    return cell_as_text(row[idx]).strip()


def _cell_raw(row: tuple[Any, ...], idx: Optional[int]) -> Any:
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def _paciente_from_row(
    row: tuple[Any, ...], indices: dict[str, int]
) -> Optional[PacienteDados]:
    pront = prontuario_so_digitos(_cell(row, indices.get("PRONTUARIO")))
    nome = _cell(row, indices.get("PACIENTE"))
    if not pront and not nome:
        return None
    endereco = _cell(row, indices.get("ENDERECO"))
    sexo = sexo_para_apac(_cell(row, indices.get("GENERO")))
    if not sexo:
        sexo = inferir_sexo_por_nome(nome)
    return PacienteDados(
        id_paciente=pront or None,
        cpf=_cell(row, indices.get("CPF")) or None,
        nome=nome or None,
        nascimento=normalizar_nascimento_origem(
            _cell_raw(row, indices.get("NASCIMENTO"))
        ),
        sexo=sexo,
        endereco=endereco or None,
        cep=_cell(row, indices.get("CEP")) or None,
        logradouro=endereco or None,
        bairro=_cell(row, indices.get("BAIRRO")) or None,
        numero=_cell(row, indices.get("NUMERO")) or None,
        complemento=_cell(row, indices.get("COMPLEMENTO")) or None,
        nome_mae=_cell(row, indices.get("NOME_MAE")) or None,
    )


@dataclass
class IcarePacientesIndex:
    por_prontuario: dict[str, PacienteDados]
    por_nome: dict[str, list[PacienteDados]]

    def get_prontuario(self, prontuario: str) -> Optional[PacienteDados]:
        alvo = prontuario_so_digitos(prontuario)
        if not alvo:
            return None
        return self.por_prontuario.get(alvo)

    def buscar_nome(
        self, nome: str, prontuario: Optional[str] = None
    ) -> list[PacienteDados]:
        chave = nome_chave_prontuario(nome)
        if not chave:
            return []
        candidatos = list(self.por_nome.get(chave, []))
        if len(candidatos) <= 1 or not prontuario:
            return candidatos
        pront = prontuario_so_digitos(prontuario)
        if not pront:
            return candidatos
        filtrados = [
            p
            for p in candidatos
            if p.id_paciente and prontuario_so_digitos(p.id_paciente) == pront
        ]
        return filtrados if filtrados else candidatos


def carregar_icare_pacientes(cfg: AppConfig) -> IcarePacientesIndex:
    """Lê planilha_pacientes e monta índices por prontuário e nome."""
    bloco = cfg.planilha_pacientes
    caminho_rel = str(bloco.get("caminho") or "").strip()
    if not caminho_rel:
        raise IcareSheetError(
            f"{MODULE} planilha_pacientes.caminho é obrigatório."
        )

    caminho = resolve_path(config_dir(cfg), Path(caminho_rel))
    if not caminho.is_file():
        raise IcareSheetError(f"{MODULE} planilha não encontrada: {caminho}")

    try:
        header_row = int(bloco.get("linha_cabecalho") or 1)
    except (TypeError, ValueError) as exc:
        raise IcareSheetError(
            f"{MODULE} linha_cabecalho inválida."
        ) from exc
    if header_row < 1:
        raise IcareSheetError(f"{MODULE} linha_cabecalho deve ser >= 1.")

    colunas = dict(bloco.get("colunas") or {})
    aba_cfg = str(bloco.get("aba") or "").strip()

    wb = load_workbook(caminho, read_only=True, data_only=True)
    try:
        ws = wb.active
        if aba_cfg:
            for nome in wb.sheetnames:
                if (
                    nome == aba_cfg
                    or nome.strip() == aba_cfg
                    or nome.casefold() == aba_cfg.casefold()
                ):
                    ws = wb[nome]
                    break
            else:
                raise IcareSheetError(
                    f"{MODULE} aba {aba_cfg!r} não encontrada em {caminho.name}."
                )

        headers_raw: list[Any] = []
        for i, row in enumerate(ws.iter_rows(values_only=True), 1):
            if i == header_row:
                headers_raw = list(row or ())
                break
        if not headers_raw:
            raise IcareSheetError(f"{MODULE} cabeçalho vazio na linha {header_row}.")

        indices = _resolve_col_indices(headers_raw, colunas)
        por_pront: dict[str, PacienteDados] = {}
        por_nome: dict[str, list[PacienteDados]] = {}

        for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
            if not row:
                continue
            pac = _paciente_from_row(tuple(row), indices)
            if pac is None:
                continue
            pront = prontuario_so_digitos(pac.id_paciente or "")
            if pront:
                if pront in por_pront:
                    log.warning(
                        "%s prontuário duplicado %s — mantendo primeira linha",
                        MODULE,
                        pront,
                    )
                else:
                    por_pront[pront] = pac
            if pac.nome:
                chave = nome_chave_prontuario(pac.nome)
                por_nome.setdefault(chave, []).append(pac)

        if not por_pront and not por_nome:
            raise IcareSheetError(
                f"{MODULE} nenhum paciente válido em {caminho.name}."
            )

        log.info(
            "%s carregados %s prontuário(s), %s nome(s) distintos de %s",
            MODULE,
            len(por_pront),
            len(por_nome),
            caminho.name,
        )
        return IcarePacientesIndex(por_prontuario=por_pront, por_nome=por_nome)
    except IcareSheetError:
        raise
    except SheetError as exc:
        raise IcareSheetError(str(exc)) from exc
    except OSError as exc:
        raise IcareSheetError(
            f"{MODULE} falha ao ler {caminho}: {exc}"
        ) from exc
    finally:
        wb.close()
