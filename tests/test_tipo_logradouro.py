from apac_bot.apac import ApacAutomator
from apac_bot.config import AppConfig
from apac_bot.models import Lancamento, PacienteDados
from apac_bot.normalize import tipo_logradouro_do_endereco


def test_tipo_travessa_no_endereco():
    assert (
        tipo_logradouro_do_endereco("SEGUNDA TRAVESSA BOM JESSUS") == "TRAVESSA"
    )


def test_tipo_rua_e_avenida():
    assert tipo_logradouro_do_endereco("RUA BOM JESUS") == "RUA"
    assert tipo_logradouro_do_endereco("AVENIDA X") == "AVENIDA"
    assert tipo_logradouro_do_endereco("AV PAULISTA") == "AVENIDA"
    assert tipo_logradouro_do_endereco("TV DO COMERCIO") == "TRAVESSA"


def test_tipo_ausente():
    assert tipo_logradouro_do_endereco("BOM JESUS") is None
    assert tipo_logradouro_do_endereco("") is None
    assert tipo_logradouro_do_endereco(None) is None


def test_tipo_povoado_com_acento():
    assert tipo_logradouro_do_endereco("Povoado São José") == "POVOADO"


def _cfg() -> AppConfig:
    return AppConfig(
        raw={
            "clinica_id": "t",
            "sistema_origem": "mock",
            "planilha": {
                "caminho": "data/x.xlsx",
                "aba": "L",
                "colunas": {
                    "PACIENTE": "P",
                    "COD": "C",
                    "AUDITOR": "A",
                    "NUMERACAO": "N",
                },
            },
            "apac": {"titulo_janela": "APAC", "passos": []},
        },
        path=__file__,
    )


def test_aceitar_logradouro_dry_run():
    automator = ApacAutomator(_cfg(), dry_run=True)
    lanc = Lancamento(
        clinica_id="t",
        numeracao_original="1-1",
        numeracao_apac="1/1",
        codigo_original="01",
        codigo_apac="01",
        auditor="A",
        paciente_nome="TESTE",
        paciente=PacienteDados(
            nome="TESTE",
            endereco="SEGUNDA TRAVESSA BOM JESSUS",
        ),
    )
    automator.aceitar_logradouro_se_preenchido(lanc)
    assert automator._logradouro_aceito is True
