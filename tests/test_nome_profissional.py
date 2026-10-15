from apac_bot.apac import (
    _nome_profissional_compativel,
    _norm_nome_profissional,
)


def test_norm_nome_profissional():
    assert _norm_nome_profissional("  Orcelio   Rezende ") == "ORCELIO REZENDE"
    assert _norm_nome_profissional("José") == "JOSE"


def test_compativel_igual():
    assert _nome_profissional_compativel(
        "ORCELIO REZENDE", "ORCELIO REZENDE"
    )


def test_compativel_rejeita_outra_pessoa():
    assert not _nome_profissional_compativel(
        "ORCELIO REZENDE", "PAULA SEREJO AFONSO"
    )


def test_compativel_contencao_extensao():
    assert _nome_profissional_compativel(
        "ORCELIO REZENDE", "ORCELIO REZENDE SILVA"
    )
    assert _nome_profissional_compativel(
        "ORCELIO REZENDE SILVA", "ORCELIO REZENDE"
    )


def test_compativel_acento_e_espacos():
    assert _nome_profissional_compativel(
        "José da Silva", "JOSE DA SILVA"
    )


def test_compativel_vazio():
    assert not _nome_profissional_compativel("ORCELIO", "")
    assert not _nome_profissional_compativel("", "ORCELIO")
