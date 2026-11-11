"""Conector Eyecare + resolver_paciente."""

from pathlib import Path

from openpyxl import Workbook

from apac_bot.config import AppConfig
from apac_bot.connectors import EyecareConnector, build_connector

from tests.conftest import raw_com_eyecare
from apac_bot.models import Lancamento
from apac_bot.pipeline import resolver_paciente

HEADERS = [
    "prontuários",
    "paciente",
    "cpf",
    "data nascimento",
    "genero",
]


def _lanc(**kw) -> Lancamento:
    base = dict(
        clinica_id="IMO",
        numeracao_original="1-1",
        numeracao_apac="1/1",
        codigo_original="01",
        codigo_apac="01",
        auditor="A",
        paciente_nome="MARIA SILVA",
        prontuario="999",
    )
    base.update(kw)
    return Lancamento(**base)


def _setup(tmp_path: Path) -> tuple[AppConfig, EyecareConnector]:
    xlsx = tmp_path / "pacientes.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(HEADERS)
    ws.append(["999", "MARIA SILVA", "529.982.247-25", "01/01/1980", "F"])
    wb.save(xlsx)
    wb.close()

    raw = {
        "clinica_id": "IMO",
        "sistema_origem": "eyecare",
        "planilha": {"caminho": "p.xlsx", "colunas": {"PACIENTE": "P"}},
        "planilha_pacientes": {"caminho": str(xlsx), "linha_cabecalho": 1},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}", encoding="utf-8")
    cfg = AppConfig(raw=raw_com_eyecare(raw), path=cfg_path)
    conn = build_connector("eyecare", cfg)
    assert isinstance(conn, EyecareConnector)
    return cfg, conn


def test_resolver_por_prontuario(tmp_path: Path):
    _cfg, conn = _setup(tmp_path)
    pac, motivo = resolver_paciente(conn, _lanc(), origem="eyecare")
    assert motivo is None
    assert pac is not None
    assert pac.nome == "MARIA SILVA"
    conn.close()


def test_resolver_prontuario_inexistente(tmp_path: Path):
    _cfg, conn = _setup(tmp_path)
    pac, motivo = resolver_paciente(
        conn, _lanc(prontuario="000", paciente_nome="INEXISTENTE"), origem="eyecare"
    )
    assert pac is None
    assert motivo is not None
    conn.close()
