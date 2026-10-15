from apac_bot.apac import (
    AUTORIZADOR_CNS_PADRAO,
    AUTORIZADOR_NOME_PADRAO,
    MEDICO_SOLICITANTE_CNS_PADRAO,
    MEDICO_SOLICITANTE_NOME_PADRAO,
    MEDICO_SOLICITANTE_PADRAO,
    _cns_so_digitos,
    _nome_profissional_compativel,
    _nome_profissional_f1,
    _norm_nome_profissional,
)


def test_padroes_clinica_cns_e_nome():
    assert MEDICO_SOLICITANTE_CNS_PADRAO == "705609469670213"
    assert MEDICO_SOLICITANTE_NOME_PADRAO == "0RCELIO REZENDE"
    assert MEDICO_SOLICITANTE_PADRAO == MEDICO_SOLICITANTE_NOME_PADRAO
    assert AUTORIZADOR_CNS_PADRAO == "708107527671032"
    assert AUTORIZADOR_NOME_PADRAO == "MARQUES HENRIQUE MARTINS FEITO"
    assert _cns_so_digitos(MEDICO_SOLICITANTE_CNS_PADRAO) == "705609469670213"
    assert len(_cns_so_digitos(AUTORIZADOR_CNS_PADRAO)) == 15


def test_cns_so_digitos_limpa_mascara():
    assert _cns_so_digitos("705.609.469.670.213") == "705609469670213"
    assert _cns_so_digitos("") == ""


def test_cns_confirmacao_ignora_hifen_da_mascara_apac():
    """Tela mostra 70560946967021-3; config tem 705609469670213."""
    tela = "CNS: 70560946967021-3  NOME: ORCELIO REZENDE"
    esperado = "705609469670213"
    assert esperado in _cns_so_digitos(tela)
    # Autorizador tambem usa mascara com hifen
    tela_aut = "CNS: 70810752767103-2  NOME: MARQUES HENRIQUE"
    assert "708107527671032" in _cns_so_digitos(tela_aut)


def test_f1_converte_o_slash_para_zero():
    assert _nome_profissional_f1("ØRCELIO REZENDE") == "0RCELIO REZENDE"
    assert _nome_profissional_f1(MEDICO_SOLICITANTE_NOME_PADRAO) == "0RCELIO REZENDE"


def test_norm_nome_profissional():
    # O e 0 equivalem na comparacao
    assert _norm_nome_profissional("  Orcelio   Rezende ") == "0RCELI0 REZENDE"
    assert _norm_nome_profissional("0RCELIO REZENDE") == "0RCELI0 REZENDE"
    assert _norm_nome_profissional("José") == "J0SE"


def test_compativel_igual():
    assert _nome_profissional_compativel(
        "0RCELIO REZENDE", "0RCELIO REZENDE"
    )


def test_compativel_o_letra_vs_zero():
    """APAC exibe Ø/0; config antiga pode ter letra O."""
    assert _nome_profissional_compativel(
        "ORCELIO REZENDE", "0RCELIO REZENDE"
    )
    assert _nome_profissional_compativel(
        "0RCELIO REZENDE", "ØRCELIO REZENDE"
    )


def test_compativel_rejeita_outra_pessoa():
    assert not _nome_profissional_compativel(
        "0RCELIO REZENDE", "PAULA SEREJO AFONSO"
    )


def test_compativel_contencao_extensao():
    assert _nome_profissional_compativel(
        "0RCELIO REZENDE", "0RCELIO REZENDE SILVA"
    )
    assert _nome_profissional_compativel(
        "0RCELIO REZENDE SILVA", "0RCELIO REZENDE"
    )


def test_compativel_acento_e_espacos():
    assert _nome_profissional_compativel(
        "José da Silva", "JOSE DA SILVA"
    )


def test_compativel_vazio():
    assert not _nome_profissional_compativel("ORCELIO", "")
    assert not _nome_profissional_compativel("", "ORCELIO")
