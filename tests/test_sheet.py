import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from apac_bot.config import AppConfig
from apac_bot.sheet import create_example_workbook, load_lancamentos


@pytest.fixture
def cfg_tmp(tmp_path: Path) -> AppConfig:
    example = json.loads(
        Path("config.example.json").read_text(encoding="utf-8")
    )
    xlsx = tmp_path / "planilha.xlsx"
    create_example_workbook(xlsx)
    example["planilha"]["caminho"] = str(xlsx)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(example), encoding="utf-8")
    return AppConfig(raw=example, path=cfg_path)


def test_preserva_zeros_e_numeracao(cfg_tmp: AppConfig):
    result = load_lancamentos(cfg_tmp)
    assert result.ok
    primeiro = result.lancamentos[0]
    assert primeiro.codigo_original == "0412345678"
    assert primeiro.numeracao_original == "1234567890123-4"
    assert primeiro.numeracao_apac == "1234567890123/4"
    assert primeiro.id_paciente == "BIO-1001"


def test_duplicidade_numeracao(cfg_tmp: AppConfig, tmp_path: Path):
    path = tmp_path / "dup.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Lançamentos"
    ws.append(["PACIENTE", "COD.", "AUDITOR", "NUMERAÇÃO", "QUANT.", "ID_PACIENTE"])
    ws.append(["A", "01", "AUD", "111-1", "", "X"])
    ws.append(["B", "02", "AUD", "111-1", "", "Y"])
    for row in (2, 3):
        for col in (2, 4, 6):
            ws.cell(row, col).number_format = "@"
    wb.save(path)
    cfg_tmp.raw["planilha"]["caminho"] = str(path)
    result = load_lancamentos(cfg_tmp)
    assert not result.ok
    assert any("duplicada" in e.lower() for e in result.erros)


def test_quant_lido_sem_interpretacao(cfg_tmp: AppConfig):
    result = load_lancamentos(cfg_tmp)
    assert result.lancamentos[0].quant == "1"
    # segundo registro sem QUANT.
    assert result.lancamentos[1].quant is None


def test_linha_cabecalho_customizada(tmp_path: Path):
    path = tmp_path / "cab.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Prod"
    ws.append(["titulo"])
    ws.append([])
    ws.append(["QUANT.", "PACIENTE", "COD.", "AUDITOR", "NUMERAÇÃO"])
    ws.append(["1", "TESTE", "04123", "AUD", "111-1"])
    for col in (3, 5):
        ws.cell(4, col).number_format = "@"
        ws.cell(4, col).value = str(ws.cell(4, col).value)
    wb.save(path)

    example = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
    example["planilha"]["caminho"] = str(path)
    example["planilha"]["aba"] = "Prod"
    example["planilha"]["linha_cabecalho"] = 3
    example["planilha"]["colunas"] = {
        "PACIENTE": "PACIENTE",
        "COD": "COD.",
        "AUDITOR": "AUDITOR",
        "NUMERACAO": "NUMERAÇÃO",
        "QUANT": "QUANT.",
        "ID_PACIENTE": "ID_PACIENTE",
    }
    cfg_path = tmp_path / "c.json"
    cfg_path.write_text(json.dumps(example), encoding="utf-8")
    cfg = AppConfig(raw=example, path=cfg_path)
    result = load_lancamentos(cfg)
    assert result.ok
    assert len(result.lancamentos) == 1
    assert result.lancamentos[0].codigo_original == "04123"


def test_apenas_ativos_ignora_linhas_ocultas(tmp_path: Path):
    path = tmp_path / "filtro.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Lançamentos"
    ws.append(["PACIENTE", "COD.", "AUDITOR", "NUMERAÇÃO", "QUANT.", "ID_PACIENTE"])
    ws.append(["OCULTO UM", "01", "AUD", "111-1", "1", ""])
    ws.append(["VISIVEL UM", "02", "AUD", "222-2", "1", ""])
    ws.append(["OCULTO DOIS", "01", "AUD", "333-3", "1", ""])
    ws.append(["VISIVEL DOIS", "02", "AUD", "444-4", "1", ""])
    for row in range(2, 6):
        for col in (2, 4):
            ws.cell(row, col).number_format = "@"
            ws.cell(row, col).value = str(ws.cell(row, col).value)
    ws.row_dimensions[2].hidden = True
    ws.row_dimensions[4].hidden = True
    wb.save(path)

    example = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
    example["planilha"]["caminho"] = str(path)
    example["planilha"]["apenas_ativos"] = True
    cfg_path = tmp_path / "c.json"
    cfg_path.write_text(json.dumps(example), encoding="utf-8")
    cfg = AppConfig(raw=example, path=cfg_path)

    result = load_lancamentos(cfg)
    assert result.ok
    assert len(result.lancamentos) == 2
    assert [l.paciente_nome for l in result.lancamentos] == ["VISIVEL UM", "VISIVEL DOIS"]
    assert any("oculta" in a.lower() for a in result.avisos)

    example["planilha"]["apenas_ativos"] = False
    cfg_all = AppConfig(raw=example, path=cfg_path)
    result_all = load_lancamentos(cfg_all)
    assert result_all.ok
    assert len(result_all.lancamentos) == 4
