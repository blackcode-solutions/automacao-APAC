"""CEP obrigatório: origem ou default 65010000."""

from __future__ import annotations

from pathlib import Path

from apac_bot.config import MODALIDADE_PADRAO, AppConfig
from apac_bot.models import Lancamento, PacienteDados
from apac_bot.normalize import CEP_PADRAO_APAC, cep_para_apac
from apac_bot.set_pipeline import montar_record_paciente


def test_cep_para_apac_preserva_valido():
    assert cep_para_apac("65085060") == "65085060"
    assert cep_para_apac("65085-060") == "65085060"


def test_cep_para_apac_default_quando_ausente():
    assert CEP_PADRAO_APAC == "65010000"
    assert cep_para_apac(None) == "65010000"
    assert cep_para_apac("") == "65010000"
    assert cep_para_apac("0") == "65010000"
    assert cep_para_apac("123") == "65010000"


def test_cep_para_apac_substitui_ceps_invalidos():
    assert cep_para_apac("65000000") == "65010000"
    assert cep_para_apac("65056500") == "65010000"


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
            },
        },
        path=Path("config.json"),
    )


def _lanc(**pac_overrides) -> Lancamento:
    base = dict(
        nome="PAC TESTE",
        nome_mae="MAE TESTE",
        cpf="03345250390",
        nascimento="19811027",
        sexo="M",
        logradouro="RUA TESTE",
        numero="10",
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


def test_montar_sem_cep_usa_default():
    rec = montar_record_paciente(_cfg(), _lanc(cep=None), competencia="202609")
    assert rec.corpo.cep == "65010000"


def test_montar_com_cep_preserva():
    rec = montar_record_paciente(
        _cfg(), _lanc(cep="65085-060"), competencia="202609"
    )
    assert rec.corpo.cep == "65085060"


def test_montar_substitui_ceps_invalidos():
    for cep in ("65000000", "65056500"):
        rec = montar_record_paciente(
            _cfg(), _lanc(cep=cep), competencia="202609"
        )
        assert rec.corpo.cep == "65010000"


def test_montar_sem_bairro_numero_usa_default():
    rec = montar_record_paciente(
        _cfg(), _lanc(bairro=None, numero=None), competencia="202609"
    )
    assert rec.corpo.bairro == "CENTRO"
    assert rec.corpo.numero == "SN"
    rec_vazio = montar_record_paciente(
        _cfg(), _lanc(bairro="", numero="  "), competencia="202609"
    )
    assert rec_vazio.corpo.bairro == "CENTRO"
    assert rec_vazio.corpo.numero == "SN"


def test_montar_com_bairro_numero_preserva():
    rec = montar_record_paciente(
        _cfg(),
        _lanc(bairro="VILA ESPERANCA", numero="124"),
        competencia="202609",
    )
    assert rec.corpo.bairro == "VILA ESPERANCA"
    assert rec.corpo.numero == "124"
