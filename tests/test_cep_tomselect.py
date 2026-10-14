from apac_bot.connectors.biodata import (
    mesclar_endereco_tomselect_cep,
    normalizar_cep_biodata,
)


def test_normalizar_cep_biodata_8_digitos():
    assert normalizar_cep_biodata("65085060") == "65085060"
    assert normalizar_cep_biodata("65085-060") == "65085060"
    assert normalizar_cep_biodata("0") is None
    assert normalizar_cep_biodata("") is None
    assert normalizar_cep_biodata(None) is None


def test_mesclar_tomselect_preenche_cep_e_endereco_quando_vazios():
    cep, endereco, bairro = mesclar_endereco_tomselect_cep(
        cep=None,
        endereco=None,
        bairro=None,
        data_value="65085060",
        data_endereco="Rua Bom Jesus",
        data_bairro="Anjo da Guarda",
        item_text="65085060",
    )
    assert cep == "65085060"
    assert endereco == "Rua Bom Jesus"
    assert bairro == "Anjo da Guarda"


def test_mesclar_tomselect_nao_sobrescreve_existentes():
    cep, endereco, bairro = mesclar_endereco_tomselect_cep(
        cep="65041235",
        endereco="RUA JA EXISTE",
        bairro="CENTRO",
        data_value="65085060",
        data_endereco="Rua Bom Jesus",
        data_bairro="Anjo da Guarda",
    )
    assert cep == "65041235"
    assert endereco == "RUA JA EXISTE"
    assert bairro == "CENTRO"


def test_mesclar_tomselect_cep_pelo_texto_do_item():
    cep, _, _ = mesclar_endereco_tomselect_cep(
        cep=None,
        endereco=None,
        bairro=None,
        item_text="65085060",
    )
    assert cep == "65085060"
