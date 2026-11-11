from apac_bot.normalize import tipo_logradouro_do_endereco
from apac_bot.tipos_logradouro import TIPOS_LOGRADOURO_APAC


def test_lista_f1_completa_carregada():
    assert len(TIPOS_LOGRADOURO_APAC) >= 400
    assert "VIA LOCAL" in TIPOS_LOGRADOURO_APAC
    assert "MIRANTE" in TIPOS_LOGRADOURO_APAC


def test_tipo_travessa_no_endereco():
    assert (
        tipo_logradouro_do_endereco("SEGUNDA TRAVESSA BOM JESSUS") == "TRAVESSA"
    )


def test_tipo_rua_e_avenida():
    assert tipo_logradouro_do_endereco("RUA BOM JESUS") == "RUA"
    assert tipo_logradouro_do_endereco("AVENIDA X") == "AVENIDA"
    assert tipo_logradouro_do_endereco("AV PAULISTA") == "AVENIDA"
    assert tipo_logradouro_do_endereco("TV DO COMERCIO") == "TRAVESSA"


def test_tipo_via_local_mais_especifico():
    assert tipo_logradouro_do_endereco("VIA LOCAL 305") == "VIA LOCAL"
    assert tipo_logradouro_do_endereco("VIA EXPRESSA NORTE") == "VIA EXPRESSA"
    assert tipo_logradouro_do_endereco("VIA MARGINAL SUL") == "VIA MARGINAL"


def test_tipo_ausente():
    assert tipo_logradouro_do_endereco("BOM JESUS") is None
    assert tipo_logradouro_do_endereco("") is None
    assert tipo_logradouro_do_endereco(None) is None


def test_tipo_povoado_com_acento():
    assert tipo_logradouro_do_endereco("Povoado São José") == "POVOADO"
