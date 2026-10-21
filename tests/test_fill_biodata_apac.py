from unittest.mock import MagicMock

from apac_bot.apac import (
    CEP_PADRAO_APAC,
    ApacAutomator,
    refrescar_paciente_biodata,
)
from apac_bot.config import AppConfig
from apac_bot.models import Lancamento, PacienteDados


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


def _lanc() -> Lancamento:
    return Lancamento(
        clinica_id="t",
        numeracao_original="1-1",
        numeracao_apac="1/1",
        codigo_original="01",
        codigo_apac="01",
        auditor="A",
        paciente_nome="TESTE SEM CADASTRO APAC",
        paciente=PacienteDados(
            nome="TESTE SEM CADASTRO APAC",
            nome_mae="MAE TESTE",
            cep="65041235",
            endereco="RUA EXEMPLO",
            bairro="CENTRO",
            numero="10",
        ),
    )


def test_paciente_dados_campos_preenchidos_inclui_cep():
    p = PacienteDados(nome="X", cep="65000000", bairro="Y")
    filled = p.campos_preenchidos()
    assert filled["cep"] == "65000000"
    assert filled["bairro"] == "Y"
    assert "numero" not in filled


def test_responsavel_dry_run_o_mesmo():
    automator = ApacAutomator(_cfg(), dry_run=True)
    automator.aceitar_nome_responsavel_se_preenchido(_lanc())
    assert automator._nome_responsavel_aceito is True


def test_aceitadores_endereco_dry_run_com_origem():
    automator = ApacAutomator(_cfg(), dry_run=True)
    lanc = _lanc()
    automator.aceitar_cep_se_preenchido(lanc)
    automator.aceitar_logradouro_se_preenchido(lanc)
    automator.aceitar_endereco_se_preenchido(lanc)
    automator.aceitar_numero_endereco_se_preenchido(lanc)
    automator.aceitar_bairro_se_preenchido(lanc)
    assert automator._cep_aceito
    assert automator._logradouro_aceito
    assert automator._endereco_aceito
    assert automator._numero_end_aceito
    assert automator._bairro_aceito


def test_normalizar_cep_logradouro_zero_vira_vazio():
    a = ApacAutomator(_cfg(), dry_run=True)
    assert a._normalizar_leitura_campo("CEP", "LOGRADOURO : 0") == ""
    assert a._normalizar_leitura_campo("CEP", "0") == ""
    assert a._normalizar_leitura_campo("CEP", "65041235") == "65041235"
    assert a._normalizar_leitura_campo("CEP", "65041-235") == "65041-235"
    assert a._normalizar_leitura_campo("CEP", "65041235 LOGRADOURO : 0") == "65041235"
    assert a._normalizar_leitura_campo("LOGRADOURO", "0") == ""
    assert a._normalizar_leitura_campo("LOGRADOURO", "00") == ""
    assert a._normalizar_leitura_campo("LOGRADOURO", "RUA A") == "RUA A"


def test_normalizar_endereco_numero_rotulo_vira_vazio():
    a = ApacAutomator(_cfg(), dry_run=True)
    assert a._normalizar_leitura_campo("ENDERECO", "NUMERO:") == ""
    assert a._normalizar_leitura_campo("ENDERECO", "NUMERO") == ""
    assert (
        a._normalizar_leitura_campo("ENDERECO", "SEGUNDA TRAVESSA BOM JESSUS")
        == "SEGUNDA TRAVESSA BOM JESSUS"
    )
    assert (
        a._normalizar_leitura_campo(
            "ENDERECO", "SEGUNDA TRAVESSA BOM JESSUS NUMERO: 10"
        )
        == "SEGUNDA TRAVESSA BOM JESSUS"
    )
    assert a._normalizar_leitura_campo("NUMERO", "NUMERO:") == ""
    assert a._normalizar_leitura_campo("NUMERO", "0") == ""
    assert a._normalizar_leitura_campo("NUMERO", "10 A") == "10 A"


def test_normalizar_nascimento_sexo_mascara_vazia():
    a = ApacAutomator(_cfg(), dry_run=True)
    assert a._normalizar_leitura_campo("DATA DE NASCIMENTO", "/ /") == ""
    assert a._normalizar_leitura_campo("DATA DE NASCIMENTO", "//") == ""
    assert (
        a._normalizar_leitura_campo("DATA DE NASCIMENTO", "15/12/1975")
        == "15/12/1975"
    )
    assert (
        a._normalizar_leitura_campo(
            "DATA DE NASCIMENTO", "15/12/1975 SEXO: ETNIA :"
        )
        == "15/12/1975"
    )
    assert a._normalizar_leitura_campo("SEXO", "ETNIA :") == ""
    assert a._normalizar_leitura_campo("SEXO", "E") == ""
    assert a._normalizar_leitura_campo("SEXO", "F") == "F"
    assert a._normalizar_leitura_campo("SEXO", "M ETNIA :") == "M"


def test_cep_para_digitar_usa_biodata():
    a = ApacAutomator(_cfg(), dry_run=True)
    lanc = _lanc()
    lanc.paciente = PacienteDados(cep="65058-864")
    assert a._cep_para_digitar_apac(lanc) == "65058864"


def test_cep_para_digitar_usa_padrao_sem_origem():
    a = ApacAutomator(_cfg(), dry_run=True)
    lanc = _lanc()
    lanc.paciente = PacienteDados(nome="SEM CEP")
    assert a._cep_para_digitar_apac(lanc) == CEP_PADRAO_APAC
    assert CEP_PADRAO_APAC == "65010000"


def test_refrescar_usa_cadastro_aberto_sem_buscar_prontuario():
    lanc = _lanc()
    lanc.paciente = PacienteDados(nome="SEM CEP")
    lanc.prontuario = "12345"
    aberto = PacienteDados(
        nome="COM CEP",
        cep="65041235",
        endereco="RUA X",
        bairro="CENTRO",
    )
    conn = MagicMock()
    conn.ler_cadastro_aberto.return_value = aberto

    refrescar_paciente_biodata(conn, lanc)

    conn.ler_cadastro_aberto.assert_called_once_with()
    conn.buscar_por_prontuario.assert_not_called()
    conn.buscar_por_id.assert_not_called()
    conn.buscar_por_nome.assert_not_called()
    assert lanc.paciente is aberto
    assert lanc.paciente.cep == "65041235"
