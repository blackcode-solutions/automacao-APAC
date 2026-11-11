"""EyecareConnector lê dados só da planilha (ex.: nome_mae)."""

from pathlib import Path

from openpyxl import Workbook

from apac_bot.config import AppConfig
from apac_bot.connectors.icare_sheet import EyecareConnector
from apac_bot.sheet import nome_mae_valido

from tests.conftest import raw_com_eyecare


def test_nome_mae_vem_da_planilha(tmp_path: Path):
    xlsx = tmp_path / "pacientes.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(
        [
            "prontuários",
            "paciente",
            "cpf",
            "data nascimento",
            "genero",
            "nome da mae",
        ]
    )
    ws.append(["1", "MARIA FILHA", "529.982.247-25", "01/01/1980", "F", "JOANA MAE"])
    wb.save(xlsx)
    wb.close()

    raw = raw_com_eyecare(
        {
            "clinica_id": "IMO",
            "sistema_origem": "eyecare",
            "planilha": {"caminho": "p.xlsx", "colunas": {"PACIENTE": "P"}},
            "planilha_pacientes": {"caminho": str(xlsx), "linha_cabecalho": 1},
        }
    )
    cfg = AppConfig(raw=raw, path=tmp_path / "config.json")

    conn = EyecareConnector(cfg)
    pac = conn.buscar_por_prontuario("1")
    assert pac is not None
    assert pac.nome_mae == "JOANA MAE"
    assert nome_mae_valido(pac.nome_mae, pac.nome)
    conn.close()
