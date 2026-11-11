"""Planilha de lista APAC IMO (faturamento ICARE)."""

from pathlib import Path

import pytest
from openpyxl import Workbook

from apac_bot.config import AppConfig
from apac_bot.icare_faturamento_sheet import load_lancamentos_icare
from apac_bot.sheet import SheetError, load_lancamentos

from tests.conftest import raw_com_eyecare

HEADERS = [
    "ORD",
    "PRONT",
    "DATA",
    "PACIENTES",
    "CNS",
    "PROCEDIMENTO",
    "TIPO",
    "MÉDICO",
    "CÓDIGO",
    "NUMERAÇÃO DE APACS",
]


def _cfg(tmp_path: Path, xlsx: Path) -> AppConfig:
    raw = {
        "clinica_id": "IMO",
        "sistema_origem": "eyecare",
        "planilha": {"caminho": str(xlsx)},
        "planilha_pacientes": {"caminho": str(tmp_path / "pac.xlsx")},
        "planilha_icare_faturamento": {"linha_cabecalho": 1},
        "colunas": {},
        "normalizacao": {},
    }
    return AppConfig(raw=raw_com_eyecare(raw), path=tmp_path / "config.json")


def _write_imo_xlsx(path: Path, rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for row in rows:
        ws.append(row)
    wb.save(path)
    wb.close()


def test_load_lancamentos_icare_linha_valida(tmp_path: Path):
    xlsx = tmp_path / "lista.xlsx"
    _write_imo_xlsx(
        xlsx,
        [
            [
                "1",
                "12345",
                "01/01/2026",
                "MARIA SILVA",
                "",
                "CONS",
                "T",
                "DR A",
                "0412345678",
                "1234567890123-4",
            ],
        ],
    )
    cfg = _cfg(tmp_path, xlsx)
    result = load_lancamentos_icare(cfg)
    assert result.ok
    assert len(result.lancamentos) == 1
    lanc = result.lancamentos[0]
    assert lanc.prontuario == "12345"
    assert lanc.paciente_nome == "MARIA SILVA"
    assert lanc.codigo_original == "0412345678"
    assert lanc.auditor == ""


def test_load_lancamentos_dispatch_icare(tmp_path: Path):
    xlsx = tmp_path / "lista.xlsx"
    _write_imo_xlsx(
        xlsx,
        [
            [
                "1",
                "99",
                "",
                "JOAO",
                "",
                "",
                "",
                "",
                "0400000123",
                "999-1",
            ],
        ],
    )
    cfg = _cfg(tmp_path, xlsx)
    result = load_lancamentos(cfg)
    assert result.ok
    assert result.lancamentos[0].prontuario == "99"


def test_load_lancamentos_icare_falta_numeracao(tmp_path: Path):
    xlsx = tmp_path / "lista.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(HEADERS)
    ws.append(["1", "1", "", "A", "", "", "", "", "04", ""])
    wb.save(xlsx)
    wb.close()
    cfg = _cfg(tmp_path, xlsx)
    result = load_lancamentos_icare(cfg)
    assert not result.ok
    assert any("NUMERAÇÃO" in e or "ausentes" in e for e in result.erros)


def test_biodata_nao_usa_loader_icare(tmp_path: Path):
    """Fixture padrão (mock/biodata) continua no leitor antigo."""
    from apac_bot.sheet import create_example_workbook

    xlsx = tmp_path / "planilha.xlsx"
    create_example_workbook(xlsx)
    raw = {
        "clinica_id": "oftalmocentro91",
        "sistema_origem": "biodata",
        "planilha": {
            "caminho": str(xlsx),
            "colunas": {
                "PACIENTE": "PACIENTE",
                "COD": "COD.",
                "AUDITOR": "AUDITOR",
                "NUMERACAO": "NUMERAÇÃO",
            },
        },
        "planilha_prontuarios": {"caminho": str(xlsx)},
    }
    cfg = AppConfig(raw=raw, path=tmp_path / "config.json")
    result = load_lancamentos(cfg)
    assert result.ok


def test_icare_cabecalho_linha_3(tmp_path: Path):
    xlsx = tmp_path / "lista.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["LISTA APAC IMO"])
    ws.append([])
    ws.append(HEADERS)
    ws.append(
        ["1", "7", "", "MARIA", "", "", "", "", "04000001", "1234567890123-4"]
    )
    wb.save(xlsx)
    wb.close()
    cfg = _cfg(tmp_path, xlsx)
    result = load_lancamentos_icare(cfg)
    assert result.ok
    assert result.lancamentos[0].paciente_nome == "MARIA"
    assert any("linha 3" in a.lower() for a in result.avisos)


def test_icare_ignora_aba_lancamentos_vazia(tmp_path: Path):
    xlsx = tmp_path / "lista.xlsx"
    wb = Workbook()
    ws_vazia = wb.active
    ws_vazia.title = "Lançamentos"
    ws_dados = wb.create_sheet("Dados")
    ws_dados.append(HEADERS)
    ws_dados.append(
        ["1", "9", "", "JOSE", "", "", "", "", "04000001", "1234567890123-4"]
    )
    wb.save(xlsx)
    wb.close()
    raw = {
        "clinica_id": "IMO",
        "sistema_origem": "eyecare",
        "planilha": {
            "caminho": str(xlsx),
            "aba": "Lançamentos",
        },
        "planilha_icare_faturamento": {"linha_cabecalho": 1},
        "colunas": {},
        "normalizacao": {},
    }
    cfg = AppConfig(raw=raw_com_eyecare(raw), path=tmp_path / "config.json")
    result = load_lancamentos(cfg)
    assert result.ok
    assert result.lancamentos[0].prontuario == "9"
    assert any("Dados" in a for a in result.avisos)


def test_biodata_nao_redireciona_lista_imo(tmp_path: Path):
    """oftalmocentro91 permanece no leitor BIODATA mesmo com xlsx no layout IMO."""
    xlsx = tmp_path / "lista.xlsx"
    _write_imo_xlsx(
        xlsx,
        [
            [
                "1",
                "42",
                "",
                "JOAO",
                "",
                "",
                "",
                "",
                "04000001",
                "1234567890123-4",
            ],
        ],
    )
    raw = {
        "clinica_id": "oftalmocentro91",
        "sistema_origem": "biodata",
        "planilha": {
            "caminho": str(xlsx),
            "colunas": {
                "PACIENTE": "PACIENTE",
                "COD": "COD.",
                "AUDITOR": "AUDITOR",
                "NUMERACAO": "NUMERAÇÃO",
            },
        },
        "planilha_prontuarios": {"caminho": str(xlsx)},
    }
    cfg = AppConfig(raw=raw, path=tmp_path / "config.json")
    result = load_lancamentos(cfg)
    assert not result.ok
    assert any("PACIENTE" in e or "AUDITOR" in e for e in result.erros)
    assert any("lista APAC IMO" in e for e in result.erros)
