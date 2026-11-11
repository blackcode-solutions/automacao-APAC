"""Heurística inferir_sexo_por_nome (Eyecare)."""

from apac_bot.normalize import inferir_sexo_por_nome


def test_inferir_feminino_sufixo_a():
    assert inferir_sexo_por_nome("MARIA SILVA") == "F"
    assert inferir_sexo_por_nome("Fernanda Costa") == "F"


def test_inferir_masculino_sufixo_o():
    assert inferir_sexo_por_nome("JOSE DA SILVA") == "M"
    assert inferir_sexo_por_nome("Paulo Roberto") == "M"
    assert inferir_sexo_por_nome("MARCOS ANTUNES") == "M"


def test_inferir_lista_fixa_e_excecao_luca():
    assert inferir_sexo_por_nome("ANA PAULA") == "F"
    assert inferir_sexo_por_nome("PEDRO HENRIQUE") == "M"
    assert inferir_sexo_por_nome("LUCA GOMES") == "M"


def test_inferir_ambiguo_retorna_none():
    assert inferir_sexo_por_nome("ANDRE COSTA") is None
    assert inferir_sexo_por_nome("GABRIEL SANTOS") is None


def test_inferir_nome_vazio():
    assert inferir_sexo_por_nome("") is None
    assert inferir_sexo_por_nome(None) is None
