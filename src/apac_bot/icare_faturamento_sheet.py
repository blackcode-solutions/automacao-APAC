"""
Leitura da planilha de faturamento / lista APAC da clínica IMO (ICARE).

Usado somente quando ``sistema_origem`` é ICARE ou ``clinica_id`` é IMO —
não participa do fluxo BIODATA (oftalmocentro91).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from openpyxl import load_workbook

from apac_bot.config import AppConfig, config_dir, resolve_path
from apac_bot.models import Lancamento
from apac_bot.normalize import cell_as_text, normalize_codigo, normalize_numeracao
from apac_bot.sheet import (
    SheetError,
    SheetValidation,
    _linha_oculta,
    nome_chave_prontuario,
    prontuario_so_digitos,
)
log = logging.getLogger(__name__)
MODULE = "[icare-faturamento]"

PLANILHA_ICARE_FATURAMENTO_DEFAULTS: dict[str, Any] = {
    "linha_cabecalho": 1,
    "colunas": {
        "PRONT": "PRONT",
        "PACIENTE": "PACIENTES",
        "COD": "CÓDIGO",
        "NUMERACAO": "NUMERAÇÃO DE APACS",
        "ORD": "ORD",
        "DATA": "DATA",
        "CNS": "CNS",
        "PROCEDIMENTO": "PROCEDIMENTO",
        "TIPO": "TIPO",
        "MEDICO": "MÉDICO",
    },
}

_COL_SYNONYMS: dict[str, tuple[str, ...]] = {
    "PRONT": ("pront", "prontuario", "prontuarios"),
    "PACIENTE": ("pacientes", "paciente"),
    "COD": ("codigo", "cod"),
    "NUMERACAO": (
        "numeracao de apacs",
        "numeracao",
        "numeracao apacs",
        "numeracao de apac",
        "numero de apacs",
        "numero apacs",
        "n apacs",
    ),
    "ORD": ("ord",),
    "DATA": ("data",),
    "CNS": ("cns",),
    "PROCEDIMENTO": ("procedimento",),
    "TIPO": ("tipo",),
    "MEDICO": ("medico",),
}

_COL_OBRIGATORIAS: tuple[str, ...] = ("PRONT", "PACIENTE", "COD", "NUMERACAO")

_OPCIONAIS: tuple[str, ...] = (
    "ORD",
    "DATA",
    "CNS",
    "PROCEDIMENTO",
    "TIPO",
    "MEDICO",
)


def _hdr_key(h: Any) -> str:
    return nome_chave_prontuario(cell_as_text(h))


def _match_col_indices(
    headers_raw: list[Any], colunas_cfg: dict[str, str]
) -> dict[str, int]:
    """Mapeia colunas conhecidas; não exige todas as obrigatórias."""
    indices: dict[str, int] = {}
    header_keys = [_hdr_key(h) for h in headers_raw]
    todas_chaves = frozenset(_COL_SYNONYMS) | frozenset(colunas_cfg)

    for chave_interna in todas_chaves:
        sinonimos = _COL_SYNONYMS.get(chave_interna, ())
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
    return indices


def _score_obrigatorias(indices: dict[str, int]) -> int:
    return sum(1 for c in _COL_OBRIGATORIAS if c in indices)


def _headers_rotulos_visiveis(headers_raw: list[Any], limite: int = 12) -> str:
    partes: list[str] = []
    for h in headers_raw:
        t = cell_as_text(h).strip()
        if t:
            partes.append(t)
        if len(partes) >= limite:
            break
    return ", ".join(partes) if partes else "(vazio)"


def _scan_primeiras_linhas(
    ws, *, max_linhas: int = 30
) -> list[tuple[int, list[Any]]]:
    out: list[tuple[int, list[Any]]] = []
    for i, row in enumerate(
        ws.iter_rows(max_row=max_linhas, values_only=True),
        1,
    ):
        out.append((i, list(row or ())))
    return out


def _localizar_cabecalho_icare(
    linhas: list[tuple[int, list[Any]]],
    colunas_cfg: dict[str, str],
    *,
    linha_preferida: int,
) -> tuple[int, list[Any], dict[str, int]]:
    """
    Encontra a linha com mais colunas IMO obrigatórias reconhecidas.
    Planilhas reais costumam ter título/logo acima do cabeçalho (linha > 1).
    """
    melhor: tuple[int, list[Any], dict[str, int]] | None = None
    melhor_score = 0
    preferida: tuple[int, list[Any], dict[str, int]] | None = None

    for row_num, headers in linhas:
        if not any(cell_as_text(h).strip() for h in headers):
            continue
        indices = _match_col_indices(headers, colunas_cfg)
        score = _score_obrigatorias(indices)
        if score > melhor_score:
            melhor_score = score
            melhor = (row_num, headers, indices)
        if row_num == linha_preferida and score >= melhor_score:
            preferida = (row_num, headers, indices)

    if melhor is not None and melhor_score >= len(_COL_OBRIGATORIAS):
        if preferida is not None and _score_obrigatorias(preferida[2]) == len(
            _COL_OBRIGATORIAS
        ):
            return preferida
        return melhor
    if melhor is not None and melhor_score > 0:
        return melhor
    if preferida is not None:
        return preferida
    if linhas:
        row_num, headers = linhas[0]
        return row_num, headers, _match_col_indices(headers, colunas_cfg)
    return linha_preferida, [], {}


def _escolher_aba_e_cabecalho(
    wb,
    colunas_cfg: dict[str, str],
    *,
    aba_preferida: str,
    linha_preferida: int,
    aba_cfg_planilha: str,
) -> tuple[str, int, list[Any], dict[str, int]]:
    """
    Seleciona aba com melhor cabeçalho IMO. Ignora `planilha.aba` de outro cliente
    se a aba nomeada não existir ou tiver pior correspondência de colunas.
    """
    candidatos: list[str] = []
    if aba_cfg_planilha and aba_cfg_planilha in wb.sheetnames:
        candidatos.append(aba_cfg_planilha)
    if aba_preferida and aba_preferida in wb.sheetnames and aba_preferida not in candidatos:
        candidatos.append(aba_preferida)
    if wb.active and wb.active.title not in candidatos:
        candidatos.append(wb.active.title)
    for nome in wb.sheetnames:
        if nome not in candidatos:
            candidatos.append(nome)

    melhor_aba = candidatos[0] if candidatos else wb.sheetnames[0]
    melhor: tuple[int, list[Any], dict[str, int]] = (linha_preferida, [], {})
    melhor_score = -1

    for nome in candidatos:
        ws = wb[nome]
        linhas = _scan_primeiras_linhas(ws)
        row_num, headers, indices = _localizar_cabecalho_icare(
            linhas, colunas_cfg, linha_preferida=linha_preferida
        )
        score = _score_obrigatorias(indices)
        if score > melhor_score:
            melhor_score = score
            melhor_aba = nome
            melhor = (row_num, headers, indices)

    row_num, headers, indices = melhor
    return melhor_aba, row_num, headers, indices


def _resolve_col_indices(
    headers_raw: list[Any], colunas_cfg: dict[str, str]
) -> dict[str, int]:
    indices = _match_col_indices(headers_raw, colunas_cfg)
    faltam = [c for c in _COL_OBRIGATORIAS if c not in indices]
    if faltam:
        rotulos = [str(colunas_cfg.get(c, c)) for c in faltam]
        visivel = _headers_rotulos_visiveis(headers_raw)
        raise SheetError(
            f"{MODULE} colunas obrigatórias ausentes: {', '.join(rotulos)}. "
            f"Cabeçalhos lidos na linha: {visivel}"
        )
    return indices


def _bloco_faturamento(cfg: AppConfig) -> dict[str, Any]:
    defaults = dict(PLANILHA_ICARE_FATURAMENTO_DEFAULTS)
    bloco = dict(cfg.planilha_icare_faturamento or {})
    cols = dict(defaults.get("colunas") or {})
    cols.update(dict(bloco.get("colunas") or {}))
    defaults.update(bloco)
    defaults["colunas"] = cols
    return defaults


def _cell_row(row: tuple[Any, ...], idx: int) -> str:
    if idx >= len(row):
        return ""
    return cell_as_text(row[idx]).strip()


def load_lancamentos_icare(
    cfg: AppConfig,
    planilha_override: Optional[Path] = None,
) -> SheetValidation:
    """Lista APAC IMO: PRONT + PACIENTES + CÓDIGO + NUMERAÇÃO DE APACS."""
    base = config_dir(cfg)
    caminho = planilha_override or resolve_path(base, cfg.planilha_caminho)
    if not caminho.is_file():
        raise SheetError(f"Planilha não encontrada: {caminho}")

    bloco = _bloco_faturamento(cfg)
    try:
        header_row = int(bloco.get("linha_cabecalho") or 1)
    except (TypeError, ValueError) as exc:
        raise SheetError(f"{MODULE} linha_cabecalho inválida.") from exc
    colunas = dict(bloco.get("colunas") or {})

    apenas_ativos = cfg.planilha_apenas_ativos
    # Modo normal: permite reler linhas, filtro «apenas ativos» e auto-detecção de aba.
    wb = load_workbook(caminho, data_only=True, read_only=False)
    erros: list[str] = []
    avisos: list[str] = []
    try:
        aba_cfg_planilha = str((cfg.raw.get("planilha") or {}).get("aba") or "").strip()
        aba_bloco = str(bloco.get("aba") or "").strip()
        aba_preferida = aba_bloco or (
            wb.active.title if wb.active else wb.sheetnames[0]
        )
        aba, header_row, headers_raw, indices_parcial = _escolher_aba_e_cabecalho(
            wb,
            colunas,
            aba_preferida=aba_preferida,
            linha_preferida=header_row,
            aba_cfg_planilha=aba_cfg_planilha,
        )
        avisos.append(f"Aba de lançamentos IMO: '{aba}'.")
        if header_row != int(bloco.get("linha_cabecalho") or 1):
            avisos.append(
                f"Cabeçalho detectado na linha {header_row} "
                f"(configurado: {bloco.get('linha_cabecalho') or 1})."
            )
        if aba_cfg_planilha and aba != aba_cfg_planilha:
            avisos.append(
                f"Aba «{aba_cfg_planilha}» ignorada — usando «{aba}» "
                "(melhor correspondência de colunas IMO)."
            )
        ws = wb[aba]

        if not headers_raw:
            erros.append(f"Cabeçalho vazio na linha {header_row}.")
            return SheetValidation([], erros, avisos)

        if _score_obrigatorias(indices_parcial) == len(_COL_OBRIGATORIAS):
            indices = indices_parcial
        else:
            try:
                indices = _resolve_col_indices(headers_raw, colunas)
            except SheetError as exc:
                erros.append(str(exc))
                return SheetValidation([], erros, avisos)

        regras_num = (cfg.normalizacao.get("numeracao") or {})
        regras_cod = (cfg.normalizacao.get("codigo") or {})
        lancamentos: list[Lancamento] = []
        vistas: dict[str, int] = {}
        ignorados_filtro = 0

        for row_num, row in enumerate(
            ws.iter_rows(min_row=header_row + 1, values_only=True),
            start=header_row + 1,
        ):
            tup = tuple(row or ())
            if not tup:
                continue

            def val(key: str) -> str:
                return _cell_row(tup, indices[key])

            pront_raw = val("PRONT")
            paciente = val("PACIENTE")
            codigo = val("COD")
            numeracao = val("NUMERACAO")
            opcionais = {k: val(k) for k in _OPCIONAIS if k in indices}

            if not any([paciente, codigo, numeracao, pront_raw, *opcionais.values()]):
                continue

            if apenas_ativos and _linha_oculta(ws, row_num):
                ignorados_filtro += 1
                continue

            pront = prontuario_so_digitos(pront_raw) or pront_raw.strip()
            faltando = []
            if not pront:
                faltando.append("PRONT")
            if not paciente:
                faltando.append("PACIENTES")
            if not codigo:
                faltando.append("CÓDIGO")
            if not numeracao:
                faltando.append("NUMERAÇÃO DE APACS")
            if faltando:
                erros.append(
                    f"Linha {row_num}: campos ausentes: {', '.join(faltando)}"
                )
                continue

            if numeracao in vistas:
                erros.append(
                    f"NUMERAÇÃO duplicada '{numeracao}' nas linhas "
                    f"{vistas[numeracao]} e {row_num}"
                )
                continue
            vistas[numeracao] = row_num

            extras: dict[str, Any] = {k: v for k, v in opcionais.items() if v}
            cns_linha = opcionais.get("CNS", "").strip()
            if cns_linha:
                extras["cns_faturamento"] = cns_linha

            lancamentos.append(
                Lancamento(
                    clinica_id=cfg.clinica_id,
                    numeracao_original=numeracao,
                    numeracao_apac=normalize_numeracao(numeracao, regras_num),
                    codigo_original=codigo,
                    codigo_apac=normalize_codigo(codigo, regras_cod),
                    auditor="",
                    paciente_nome=paciente,
                    id_paciente=pront or None,
                    prontuario=pront or None,
                    quant="1",
                    linha_planilha=row_num,
                    extras=extras,
                )
            )

        if apenas_ativos and ignorados_filtro:
            avisos.append(
                f"Apenas ativos: {len(lancamentos)} lançamento(s); "
                f"{ignorados_filtro} linha(s) oculta(s) ignorada(s)."
            )
        if not lancamentos and not erros:
            erros.append("Planilha IMO sem lançamentos válidos.")

        log.info("%s %s lançamento(s) em %s", MODULE, len(lancamentos), caminho.name)
        return SheetValidation(lancamentos, erros, avisos)
    finally:
        wb.close()
