"""Resolução de paciente ICARE por PRONT."""

from pathlib import Path

from openpyxl import Workbook

from apac_bot.config import AppConfig
from apac_bot.connectors import build_connector
from apac_bot.models import Lancamento
from apac_bot.pipeline import resolver_paciente, resolver_paciente_eyecare

from tests.conftest import raw_com_eyecare


def _lanc(**kw) -> Lancamento:
    base = dict(
        clinica_id="IMO",
        numeracao_original="1-1",
        numeracao_apac="1/1",
        codigo_original="01",
        codigo_apac="01",
        auditor="",
        paciente_nome="MARIA SILVA",
        prontuario="999",
    )
    base.update(kw)
    return Lancamento(**base)


def _setup(tmp_path: Path) -> tuple[AppConfig, object]:
    pac_xlsx = tmp_path / "pacientes.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["prontuários", "paciente", "cpf", "data nascimento", "genero"])
    ws.append(["999", "MARIA SILVA", "529.982.247-25", "01/01/1980", "F"])
    wb.save(pac_xlsx)
    wb.close()

    raw = {
        "clinica_id": "IMO",
        "sistema_origem": "eyecare",
        "planilha": {"caminho": "p.xlsx", "colunas": {"PACIENTE": "P"}},
        "planilha_pacientes": {"caminho": str(pac_xlsx), "linha_cabecalho": 1},
    }
    cfg = AppConfig(raw=raw_com_eyecare(raw), path=tmp_path / "config.json")
    conn = build_connector("eyecare", cfg)
    return cfg, conn


def test_icare_match_por_pront(tmp_path: Path):
    _cfg, conn = _setup(tmp_path)
    pac, motivo = resolver_paciente_eyecare(conn, _lanc())
    assert motivo is None
    assert pac is not None
    assert pac.nome == "MARIA SILVA"
    conn.close()


def test_icare_pront_inexistente(tmp_path: Path):
    _cfg, conn = _setup(tmp_path)
    pac, motivo = resolver_paciente_eyecare(conn, _lanc(prontuario="000"))
    assert pac is None
    assert motivo is not None
    assert "não encontrado" in motivo
    conn.close()


def test_icare_nome_divergente(tmp_path: Path):
    _cfg, conn = _setup(tmp_path)
    pac, motivo = resolver_paciente_eyecare(
        conn, _lanc(paciente_nome="OUTRO NOME")
    )
    assert pac is None
    assert motivo is not None
    assert "divergente" in motivo
    conn.close()


def test_icare_sem_fallback_nome(tmp_path: Path):
    _cfg, conn = _setup(tmp_path)
    pac, motivo = resolver_paciente(
        conn,
        _lanc(prontuario="", paciente_nome="MARIA SILVA"),
        origem="eyecare",
    )
    assert pac is None
    assert "PRONT ausente" in (motivo or "")
    conn.close()
