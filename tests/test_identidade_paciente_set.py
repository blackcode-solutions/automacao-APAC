"""CPF e CNS do paciente mutuamente exclusivos (prioridade CPF)."""

from __future__ import annotations

from pathlib import Path

from apac_bot.config import MODALIDADE_PADRAO, AppConfig
from apac_bot.models import Lancamento, PacienteDados
from apac_bot.normalize import identidade_paciente_set
from apac_bot.set_pipeline import montar_record_paciente

CNS_OK = "708107527671032"
CPF_OK = "03345250390"


def test_identidade_prioridade_cpf_zera_cns():
    cpf, cns = identidade_paciente_set(CPF_OK, CNS_OK)
    assert cpf == CPF_OK
    assert cns == ""


def test_identidade_so_cns():
    cpf, cns = identidade_paciente_set(None, CNS_OK)
    assert cpf == ""
    assert cns == CNS_OK


def test_identidade_so_cpf():
    cpf, cns = identidade_paciente_set(CPF_OK, None)
    assert cpf == CPF_OK
    assert cns == ""


def test_identidade_nenhum():
    assert identidade_paciente_set(None, None) == ("", "")
    assert identidade_paciente_set("", "123") == ("", "")


def _cfg() -> AppConfig:
    return AppConfig(
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
                "codigo_servico": "131",
                "codigo_classificacao": "003",
            },
        },
        path=Path("config.json"),
    )


def _lanc(**pac_overrides) -> Lancamento:
    base = dict(
        nome="PAC TESTE",
        nome_mae="MAE TESTE",
        cpf=CPF_OK,
        nascimento="19811027",
        sexo="M",
        logradouro="RUA TESTE",
        numero="10",
        cep="65763000",
        bairro="CENTRO",
    )
    base.update(pac_overrides)
    return Lancamento(
        clinica_id="oftalmocentro91",
        numeracao_original="2126205409218",
        numeracao_apac="2126205409218",
        codigo_original="0405050372",
        codigo_apac="0405050372",
        auditor="A",
        paciente_nome="PAC TESTE",
        prontuario="123",
        paciente=PacienteDados(**base),
    )


def test_montar_cpf_e_cns_grava_so_cpf():
    rec = montar_record_paciente(
        _cfg(), _lanc(cpf=CPF_OK, cns=CNS_OK), competencia="202609"
    )
    assert rec.corpo.cpf == CPF_OK
    assert rec.corpo.cns_paciente == ""
    assert rec.corpo.sem_cpf == "N"


def test_montar_so_cns():
    rec = montar_record_paciente(
        _cfg(), _lanc(cpf=None, cns=CNS_OK), competencia="202609"
    )
    assert rec.corpo.cpf == ""
    assert rec.corpo.cns_paciente == CNS_OK
    assert rec.corpo.sem_cpf == "S"


def test_montar_so_cpf():
    rec = montar_record_paciente(
        _cfg(), _lanc(cpf=CPF_OK, cns=None), competencia="202609"
    )
    assert rec.corpo.cpf == CPF_OK
    assert rec.corpo.cns_paciente == ""
    assert rec.corpo.sem_cpf == "N"
