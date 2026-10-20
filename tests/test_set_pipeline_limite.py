"""Limite de pacientes no gerar-set e merge de config export_set."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from apac_bot.config import AppConfig
from apac_bot.models import Lancamento, PacienteDados
from apac_bot.set_pipeline import cmd_gerar_set
from apac_bot.ui.config_io import DADOS_FIXOS_UI_KEYS, load_form, save_form


def _cfg(tmp_path: Path) -> AppConfig:
    raw = {
        "clinica_id": "oftalmocentro91",
        "sistema_origem": "mock",
        "planilha": {
            "caminho": str(tmp_path / "x.xlsx"),
            "aba": "A",
            "linha_cabecalho": 1,
            "colunas": {
                "PACIENTE": "PACIENTE",
                "COD": "COD.",
                "AUDITOR": "AUDITOR",
                "NUMERACAO": "NUMERAÇÃO",
            },
        },
        "dados_fixos": {
            "cnes_solicitante": "6618839",
            "cnes_executante": "6618839",
            "tipo_apac": "3",
            "codigo_procedimento": "0405050372",
            "cbo": "225265",
            "quantidade_procedimento": "1",
            "cns_executante": "701003891196892",
            "medico_solicitante_cns": "705609469670213",
            "medico_solicitante_nome": "ORCELIO REZENDE",
            "autorizador_cns": "708107527671032",
            "autorizador_nome": "MARQUES HENRIQUE MARTINS FEITO",
            "motivo_saida": "12",
            "carater_atend": "01",
            "cod_orgao_emiss": "M211130001",
            "cid_principal": "H250",
            "codigo_servico": "131",
            "codigo_classificacao": "003",
            "uf_ibge": "21",
            "nacionalidade": "010",
            "raca": "03",
            "codigo_logradouro": "008",
            "municipio_ibge_padrao": "211230",
            "nome_responsavel_padrao": "O MESMO",
            "tipo_atendimento": "00",
        },
        "export_set": {
            "limite_pacientes": 5,
            "pasta_saida": str(tmp_path / "export_set"),
            "competencia_padrao": "202609",
            "orgao_origem": "CLINICA DE SERVICOS MEDICOS GE",
            "sigla": "CSMG",
            "cgc": "01192155000210",
            "orgao_destino": "SECRETARIA DE SAUDE",
            "versao": "Versao 04.01",
        },
        "apac": {"paciente_inicio": "PAC 0"},
        "progresso": {"caminho_db": str(tmp_path / "progress.db")},
        "biodata": {"url": "https://exemplo.local"},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return AppConfig(raw=raw, path=path)


def _lanc(i: int) -> Lancamento:
    return Lancamento(
        clinica_id="oftalmocentro91",
        numeracao_original=f"21262054092{i}-{i}",
        numeracao_apac=f"21262054092{i}/{i}",
        codigo_original="0405050372",
        codigo_apac="0405050372",
        auditor="A",
        paciente_nome=f"PAC {i}",
        prontuario=str(1000 + i),
    )


def _paciente(i: int) -> PacienteDados:
    return PacienteDados(
        nome=f"PAC {i}",
        nome_mae=f"MAE {i}",
        cpf=f"{i:011d}"[:11].ljust(11, "0") if False else f"0334525039{i % 10}",
        nascimento="19811027",
        sexo="M",
        logradouro="RUA TESTE",
        numero="10",
        cep="65763000",
        bairro="CENTRO",
    )


def test_gerar_set_respeita_limite_5(tmp_path: Path):
    cfg = _cfg(tmp_path)
    fila = [_lanc(i) for i in range(8)]

    connector = MagicMock()
    connector.buscar_por_prontuario = MagicMock(
        side_effect=lambda p: _paciente(int(p) - 1000)
    )
    connector.close = MagicMock()

    # Pacientes com CPF validos (11 digitos)
    def _pac_ok(pront: str):
        idx = int(pront) - 1000
        return PacienteDados(
            nome=f"PAC {idx}",
            nome_mae=f"MAE DO PAC {idx}",
            cpf="03345250390",
            nascimento="27/10/1981",
            sexo="M",
            logradouro="JOACY PINHEIRO",
            numero="124",
            cep="65763000",
            bairro="CENTRO",
        )

    connector.buscar_por_prontuario = MagicMock(side_effect=_pac_ok)

    with patch(
        "apac_bot.set_pipeline.listar_lancamentos_a_partir", return_value=fila
    ), patch(
        "apac_bot.set_pipeline.build_connector", return_value=connector
    ):
        code = cmd_gerar_set(cfg)

    assert code == 0
    assert connector.buscar_por_prontuario.call_count == 5
    staging = tmp_path / "export_set" / "lote_atual.SET"
    assert staging.is_file()
    text = staging.read_bytes().decode("latin-1")
    assert text.startswith("01#APAC")
    assert "000005" in text[:30]
    assert text.count("\r\n14") == 5


def test_save_form_preserva_biodata_e_export_set(tmp_path: Path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "clinica_id": "oftalmocentro91",
                "sistema_origem": "biodata",
                "biodata": {"url": "https://keep.me", "locators": {"campo_cpf": "#x"}},
                "export_set": {"limite_pacientes": 5},
                "planilha": {
                    "caminho": "a.xlsx",
                    "aba": "A",
                    "colunas": {
                        "PACIENTE": "PACIENTE",
                        "COD": "COD.",
                        "AUDITOR": "AUDITOR",
                        "NUMERACAO": "NUMERAÇÃO",
                    },
                },
                "planilha_prontuarios": {
                    "caminho": "pront.xlsx",
                    "aba": "APAC ",
                    "linha_cabecalho": 3,
                    "colunas": {
                        "PRONTUARIO": "Prontuário",
                        "CLIENTE": "Cliente",
                    },
                },
                "dados_fixos": {
                    "cnes_solicitante": "6618839",
                    "cnes_executante": "6618839",
                    "tipo_apac": "3",
                    "codigo_procedimento": "0405050372",
                    "cbo": "225265",
                    "quantidade_procedimento": "1",
                    "cns_executante": "701003891196892",
                    "medico_solicitante_cns": "705609469670213",
                    "medico_solicitante_nome": "ORCELIO",
                    "autorizador_cns": "708107527671032",
                    "autorizador_nome": "MARQUES",
                    "motivo_saida": "12",
                    "carater_atend": "01",
                    "cod_orgao_emiss": "M211130001",
                    "cid_principal": "H250",
                    "codigo_servico": "131",
                    "codigo_classificacao": "003",
                },
                "apac": {"paciente_inicio": "X"},
            }
        ),
        encoding="utf-8",
    )
    form = load_form(cfg_path)
    form.dados_fixos["motivo_saida"] = "12"
    save_form(cfg_path, form)
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert raw["biodata"]["url"] == "https://keep.me"
    assert raw["export_set"]["limite_pacientes"] == 5
    # CID oculto por modalidade (padrão H250); serviço/classif só no config.
    assert raw["dados_fixos"]["cid_principal"] == "H250"
    assert "cid_principal" in DADOS_FIXOS_UI_KEYS
    assert "codigo_servico" not in DADOS_FIXOS_UI_KEYS
