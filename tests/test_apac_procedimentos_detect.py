from apac_bot.apac import (
    VK_TAB,
    _SCAN_TAB,
    _texto_indica_tela_procedimentos,
)


def test_constantes_tab():
    assert VK_TAB == 0x09
    assert _SCAN_TAB == 0x0F



def test_detecta_codigo_procedimento():
    assert _texto_indica_tela_procedimentos("15.12.19.753-0")
    assert _texto_indica_tela_procedimentos("  15.12.19.753-0  ")


def test_detecta_titulo_procedimentos():
    assert _texto_indica_tela_procedimentos("APAC MAGNETICO PROCEDIMENTOS REALIZADOS")
    assert _texto_indica_tela_procedimentos("CID Princ.")


def test_nao_detecta_cep_nem_nome():
    assert not _texto_indica_tela_procedimentos("74000000")
    assert not _texto_indica_tela_procedimentos("74000-000")
    assert not _texto_indica_tela_procedimentos("ELMO CASTELO BRANCO")
    assert not _texto_indica_tela_procedimentos("")
