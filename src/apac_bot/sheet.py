from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from openpyxl import Workbook, load_workbook

from apac_bot.config import AppConfig, config_dir, resolve_path
from apac_bot.models import Lancamento
from apac_bot.normalize import cell_as_text, normalize_codigo, normalize_numeracao, optional_text


class SheetError(Exception):
    pass


@dataclass
class SheetValidation:
    lancamentos: list[Lancamento]
    erros: list[str]
    avisos: list[str]

    @property
    def ok(self) -> bool:
        return not self.erros


def resolver_lancamento_inicio(
    cfg: AppConfig,
    planilha_override: Optional[Path] = None,
) -> Lancamento:
    """
    Localiza o lançamento de partida por apac.paciente_inicio (nome exato, case-insensitive).
    """
    nome_alvo = (cfg.apac.get("paciente_inicio") or "").strip()
    if not nome_alvo:
        raise SheetError(
            "apac.paciente_inicio não configurado — defina o nome do primeiro paciente."
        )

    result = load_lancamentos(cfg, planilha_override)
    if not result.ok:
        raise SheetError(
            "Falha ao carregar planilha: " + "; ".join(result.erros[:5])
        )
    if not result.lancamentos:
        raise SheetError("Planilha sem lançamentos ativos.")

    alvo_norm = nome_alvo.casefold()
    for lanc in result.lancamentos:
        if (lanc.paciente_nome or "").strip().casefold() == alvo_norm:
            return lanc

    raise SheetError(
        f"Paciente início '{nome_alvo}' não encontrado na planilha "
        f"({len(result.lancamentos)} lançamento(s) ativos)."
    )


def _header_map(ws, header_row: int = 1) -> dict[str, int]:
    headers: dict[str, int] = {}
    max_col = ws.max_column or 1
    for col in range(1, max_col + 1):
        raw = ws.cell(header_row, col).value
        if raw is None:
            continue
        name = cell_as_text(raw)
        if name:
            headers[name] = col
    return headers


def _cell(ws, row: int, col: Optional[int]) -> str:
    if col is None:
        return ""
    return cell_as_text(ws.cell(row, col).value)


def _linha_oculta(ws, row: int) -> bool:
    """True se a linha estiver oculta (filtro do Excel / hide manual)."""
    try:
        return bool(ws.row_dimensions[row].hidden)
    except Exception:
        return False


def load_lancamentos(cfg: AppConfig, planilha_override: Optional[Path] = None) -> SheetValidation:
    base = config_dir(cfg)
    caminho = planilha_override or resolve_path(base, cfg.planilha_caminho)
    if not caminho.is_file():
        raise SheetError(f"Planilha não encontrada: {caminho}")

    apenas_ativos = cfg.planilha_apenas_ativos
    # read_only=True não expõe bem row_dimensions.hidden; use modo normal com apenas_ativos
    wb = load_workbook(caminho, data_only=True, read_only=not apenas_ativos)
    aba = cfg.planilha_aba
    if aba not in wb.sheetnames:
        raise SheetError(f"Aba '{aba}' não encontrada. Disponíveis: {wb.sheetnames}")
    ws = wb[aba]

    colmap = cfg.colunas
    header_row = cfg.planilha_linha_cabecalho
    headers = _header_map(ws, header_row)
    erros: list[str] = []
    avisos: list[str] = []

    required_headers = {
        "PACIENTE": colmap["PACIENTE"],
        "COD": colmap["COD"],
        "AUDITOR": colmap["AUDITOR"],
        "NUMERACAO": colmap["NUMERACAO"],
    }
    indices: dict[str, Optional[int]] = {}
    for key, header_name in required_headers.items():
        if header_name not in headers:
            erros.append(f"Coluna obrigatória ausente na planilha: '{header_name}'")
            indices[key] = None
        else:
            indices[key] = headers[header_name]

    for opt_key in ("QUANT", "ID_PACIENTE"):
        header_name = colmap.get(opt_key)
        if header_name and header_name in headers:
            indices[opt_key] = headers[header_name]
        else:
            indices[opt_key] = None
            if opt_key == "ID_PACIENTE" and header_name:
                avisos.append(
                    f"Coluna opcional '{header_name}' não encontrada; busca priorizará nome."
                )

    if erros:
        wb.close()
        return SheetValidation([], erros, avisos)

    regras_num = (cfg.normalizacao.get("numeracao") or {})
    regras_cod = (cfg.normalizacao.get("codigo") or {})
    fixos = cfg.dados_fixos

    lancamentos: list[Lancamento] = []
    vistas: dict[str, int] = {}
    ignorados_filtro = 0

    data_start = header_row + 1
    max_row = ws.max_row or data_start
    for row in range(data_start, max_row + 1):
        paciente = _cell(ws, row, indices["PACIENTE"])
        codigo = _cell(ws, row, indices["COD"])
        auditor = _cell(ws, row, indices["AUDITOR"])
        numeracao = _cell(ws, row, indices["NUMERACAO"])
        quant = _cell(ws, row, indices.get("QUANT"))
        id_paciente = _cell(ws, row, indices.get("ID_PACIENTE"))

        if not any([paciente, codigo, auditor, numeracao, quant, id_paciente]):
            continue

        if apenas_ativos and _linha_oculta(ws, row):
            ignorados_filtro += 1
            continue

        faltando = []
        if not paciente:
            faltando.append("PACIENTE")
        if not codigo:
            faltando.append("COD")
        if not auditor:
            faltando.append("AUDITOR")
        if not numeracao:
            faltando.append("NUMERACAO")
        if faltando:
            erros.append(f"Linha {row}: campos ausentes: {', '.join(faltando)}")
            continue

        if numeracao in vistas:
            erros.append(
                f"NUMERAÇÃO duplicada '{numeracao}' nas linhas {vistas[numeracao]} e {row}"
            )
            continue
        vistas[numeracao] = row

        # QUANT. é lido sem interpretação como quantidade de procedimentos
        lancamentos.append(
            Lancamento(
                clinica_id=cfg.clinica_id,
                numeracao_original=numeracao,
                numeracao_apac=normalize_numeracao(numeracao, regras_num),
                codigo_original=codigo,
                codigo_apac=normalize_codigo(codigo, regras_cod),
                auditor=auditor,
                paciente_nome=paciente,
                id_paciente=optional_text(id_paciente),
                quant=optional_text(quant),
                competencia=optional_text(fixos.get("competencia")),
                validade=optional_text(fixos.get("validade")),
                linha_planilha=row,
            )
        )

    if apenas_ativos and ignorados_filtro:
        avisos.append(
            f"Apenas ativos: {len(lancamentos)} lançamento(s) visível(is); "
            f"{ignorados_filtro} linha(s) oculta(s) ignorada(s) pelo filtro do Excel."
        )

    wb.close()
    return SheetValidation(lancamentos, erros, avisos)


def create_example_workbook(path: Path) -> None:
    """Gera planilha fictícia para testes e exemplos."""
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Lançamentos"
    headers = ["PACIENTE", "COD.", "AUDITOR", "NUMERAÇÃO", "QUANT.", "ID_PACIENTE"]
    ws.append(headers)
    rows = [
        ["MARIA SILVA FICTICIA", "0412345678", "AUD01", "1234567890123-4", "1", "BIO-1001"],
        ["JOAO SOUZA FICTICIO", "0412345678", "AUD01", "1234567890124-5", "", "BIO-1002"],
        ["ANA COSTA FICTICIA", "0400000123", "AUD02", "1234567890125-6", "2", ""],
        ["PACIENTE AMBIGUO", "0412345678", "AUD01", "1234567890126-7", "", ""],
    ]
    for r in rows:
        ws.append(r)
    # Garantir que códigos/numerações com zero à esquerda sejam texto
    for row_idx in range(2, 2 + len(rows)):
        for col_idx in (2, 4, 6):  # COD., NUMERAÇÃO, ID_PACIENTE
            cell = ws.cell(row_idx, col_idx)
            if cell.value is not None and cell.value != "":
                cell.value = str(cell.value)
                cell.number_format = "@"
    wb.save(path)
