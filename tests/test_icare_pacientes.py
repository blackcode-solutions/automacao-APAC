"""Planilha de pacientes ICARE."""

from pathlib import Path

import pytest
from openpyxl import Workbook

from apac_bot.config import AppConfig
from apac_bot.icare_pacientes import IcareSheetError, carregar_icare_pacientes

from tests.conftest import raw_com_eyecare
from apac_bot.normalize import tem_cpf_valido

HEADERS = [
    "prontuários",
    "paciente",
    "cpf",
    "data nascimento",
    "genero",
    "cep",
    "endereço",
    "numero",
    "complemento",
    "bairro",
]


def _cfg(tmp_path: Path, xlsx: Path) -> AppConfig:
    raw = {
        "clinica_id": "IMO",
        "sistema_origem": "eyecare",
        "planilha": {"caminho": "x.xlsx", "colunas": {"PACIENTE": "P"}},
        "planilha_pacientes": {
            "caminho": str(xlsx.name),
            "linha_cabecalho": 1,
            "colunas": {},
        },
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}", encoding="utf-8")
    return AppConfig(raw=raw_com_eyecare(raw), path=cfg_path)


def _write_xlsx(path: Path, rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for row in rows:
        ws.append(row)
    wb.save(path)
    wb.close()


def test_carregar_por_prontuario(tmp_path: Path):
    xlsx = tmp_path / "pacientes.xlsx"
    _write_xlsx(
        xlsx,
        [
            [
                "12345",
                "MARIA SILVA",
                "529.982.247-25",
                "01/01/1980",
                "F",
                "30130000",
                "Rua A",
                "10",
                "ap 1",
                "Centro",
            ],
        ],
    )
    cfg = _cfg(tmp_path, xlsx)
    cfg.raw["planilha_pacientes"]["caminho"] = str(xlsx)
    idx = carregar_icare_pacientes(cfg)
    pac = idx.get_prontuario("12345")
    assert pac is not None
    assert pac.nome == "MARIA SILVA"
    assert tem_cpf_valido(pac.cpf)
    assert pac.sexo == "F"
    assert pac.cep == "30130000"


def test_genero_vazio_infere_pelo_nome(tmp_path: Path):
    xlsx = tmp_path / "pacientes.xlsx"
    _write_xlsx(
        xlsx,
        [
            [
                "100",
                "MARIA SILVA",
                "529.982.247-25",
                "01/01/1980",
                "",
                "",
                "",
                "",
                "",
                "",
            ],
            [
                "101",
                "JOSE DA SILVA",
                "529.982.247-25",
                "01/01/1980",
                "",
                "",
                "",
                "",
                "",
                "",
            ],
            [
                "102",
                "ANDRE COSTA",
                "529.982.247-25",
                "01/01/1980",
                "",
                "",
                "",
                "",
                "",
                "",
            ],
        ],
    )
    cfg = _cfg(tmp_path, xlsx)
    cfg.raw["planilha_pacientes"]["caminho"] = str(xlsx)
    idx = carregar_icare_pacientes(cfg)
    assert idx.get_prontuario("100").sexo == "F"
    assert idx.get_prontuario("101").sexo == "M"
    assert idx.get_prontuario("102").sexo is None


def test_genero_preenchido_nao_sobrescrito_por_nome(tmp_path: Path):
    xlsx = tmp_path / "pacientes.xlsx"
    _write_xlsx(
        xlsx,
        [
            [
                "200",
                "MARIA SILVA",
                "529.982.247-25",
                "01/01/1980",
                "M",
                "",
                "",
                "",
                "",
                "",
            ],
        ],
    )
    cfg = _cfg(tmp_path, xlsx)
    cfg.raw["planilha_pacientes"]["caminho"] = str(xlsx)
    pac = carregar_icare_pacientes(cfg).get_prontuario("200")
    assert pac.sexo == "M"


def test_carregar_sem_caminho(tmp_path: Path):
    cfg = _cfg(tmp_path, tmp_path / "x.xlsx")
    cfg.raw["planilha_pacientes"]["caminho"] = ""
    with pytest.raises(IcareSheetError, match="caminho"):
        carregar_icare_pacientes(cfg)


def test_data_nascimento_underscore_mes_extenso(tmp_path: Path):
    headers = [
        "prontuários",
        "paciente",
        "cpf",
        "data_nascimento",
        "genero",
        "cep",
        "endereço",
        "numero",
        "complemento",
        "bairro",
    ]
    xlsx = tmp_path / "pacientes.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    ws.append(
        [
            "999",
            "ANA TESTE",
            "529.982.247-25",
            "janeiro 16, 1950",
            "F",
            "",
            "",
            "",
            "",
            "",
        ]
    )
    wb.save(xlsx)
    wb.close()
    cfg = _cfg(tmp_path, xlsx)
    cfg.raw["planilha_pacientes"]["caminho"] = str(xlsx)
    idx = carregar_icare_pacientes(cfg)
    pac = idx.get_prontuario("999")
    assert pac is not None
    assert pac.nascimento == "16011950"


def test_data_nascimento_ddmm_com_barra_regressao(tmp_path: Path):
    xlsx = tmp_path / "pacientes.xlsx"
    _write_xlsx(
        xlsx,
        [
            [
                "888",
                "BETO",
                "529.982.247-25",
                "01/01/1980",
                "M",
                "",
                "",
                "",
                "",
                "",
            ],
        ],
    )
    cfg = _cfg(tmp_path, xlsx)
    cfg.raw["planilha_pacientes"]["caminho"] = str(xlsx)
    pac = carregar_icare_pacientes(cfg).get_prontuario("888")
    assert pac is not None
    assert pac.nascimento == "01011980"


def test_buscar_nome_desambigua_prontuario(tmp_path: Path):
    xlsx = tmp_path / "pacientes.xlsx"
    _write_xlsx(
        xlsx,
        [
            [
                "111",
                "JOAO DUPLICADO",
                "529.982.247-25",
                "01/01/1980",
                "M",
                "",
                "",
                "",
                "",
                "",
            ],
            [
                "222",
                "JOAO DUPLICADO",
                "390.533.447-05",
                "02/02/1981",
                "M",
                "",
                "",
                "",
                "",
                "",
            ],
        ],
    )
    cfg = _cfg(tmp_path, xlsx)
    cfg.raw["planilha_pacientes"]["caminho"] = str(xlsx)
    idx = carregar_icare_pacientes(cfg)
    um = idx.buscar_nome("JOAO DUPLICADO", prontuario="222")
    assert len(um) == 1
    assert idx.get_prontuario("222") is not None
