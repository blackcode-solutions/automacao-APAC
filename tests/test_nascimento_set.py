"""Conversão de nascimento para AAAAMMDD no SET (dias 19/20)."""

from __future__ import annotations

from pathlib import Path

from apac_bot.config import MODALIDADE_PADRAO, AppConfig
from apac_bot.models import Lancamento, PacienteDados
from apac_bot.normalize import nascimento_ddmmaaaa
from apac_bot.set_layout import nascimento_aaaammdd
from apac_bot.set_pipeline import montar_record_paciente


def test_aaaammdd_dia_19_via_ddmmaaaa():
    """19/12/1967 não pode ficar como 19121967 no SET."""
    dd = nascimento_ddmmaaaa("19/12/1967")
    assert dd == "19121967"
    assert nascimento_aaaammdd(dd) == "19671219"


def test_aaaammdd_dia_20_via_ddmmaaaa():
    dd = nascimento_ddmmaaaa("20/06/1948")
    assert dd == "20061948"
    assert nascimento_aaaammdd(dd) == "19480620"


def test_aaaammdd_regressao_27_out():
    dd = nascimento_ddmmaaaa("27/10/1981")
    assert dd == "27101981"
    assert nascimento_aaaammdd(dd) == "19811027"


def test_aaaammdd_ja_yyyymmdd():
    assert nascimento_aaaammdd("19671219") == "19671219"


def test_aaaammdd_com_barras():
    assert nascimento_aaaammdd("19/12/1967") == "19671219"
    assert nascimento_aaaammdd("20/06/1948") == "19480620"


def test_ddmmaaaa_oito_digitos_yyyymmdd():
    """20011222 (YYYYMMDD) não vira 20/01/1222."""
    assert nascimento_ddmmaaaa("20011222") == "22122001"


def test_pipeline_dia_19():
    cfg = AppConfig(
        raw={
            "clinica_id": "oftalmocentro91",
            "apac": {"modalidade": MODALIDADE_PADRAO},
            "dados_fixos": {
                "cnes_solicitante": "6618839",
                "cnes_executante": "6618839",
                "codigo_procedimento": "0405050372",
                "cid_principal": "H250",
                "medico_solicitante_nome": "ORCELIO",
                "medico_solicitante_cns": "705609469670213",
                "autorizador_nome": "MARQUES",
                "autorizador_cns": "708107527671032",
                "cns_executante": "701003891196892",
                "cod_orgao_emiss": "M211130001",
                "cbo": "225265",
            },
        },
        path=Path("config.json"),
    )
    lanc = Lancamento(
        clinica_id="oftalmocentro91",
        numeracao_original="2126205409218",
        numeracao_apac="2126205409218",
        codigo_original="0405050372",
        codigo_apac="0405050372",
        auditor="A",
        paciente_nome="MARIA DE JESUS COSTA",
        prontuario="123",
        paciente=PacienteDados(
            nome="MARIA DE JESUS COSTA",
            nome_mae="MAE TESTE",
            cpf="03345250390",
            nascimento="19/12/1967",
            sexo="F",
            logradouro="RUA TESTE",
            numero="10",
            cep="65763000",
            bairro="CENTRO",
        ),
    )
    rec = montar_record_paciente(cfg, lanc, competencia="202609")
    assert rec.corpo.nascimento == "19671219"
