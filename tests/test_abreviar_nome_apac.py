from apac_bot.normalize import APAC_MAX_NOME, abreviar_nome_apac


def test_nome_curto_inalterado():
    nome = "MARIA SILVA"
    assert abreviar_nome_apac(nome) == "MARIA SILVA"
    assert len(abreviar_nome_apac(nome)) <= APAC_MAX_NOME


def test_caso_claudia_abreviado_ultimo():
    nome = "CLAUDIA MARQUILENE SILVA CUTRIM"
    assert len(nome) == 31
    out = abreviar_nome_apac(nome)
    assert out == "CLAUDIA MARQUILENE SILVA C"
    assert len(out) <= APAC_MAX_NOME
    assert out.endswith(" C")


def test_abreviar_ultimo_depois_penultimo():
    # 37 chars: so abrevia o ultimo -> 28; precisa mais longo para penultimo
    nome = "AAAA BBBBBBBBBB CCCCCCCCCC DDDDDDDDDD"
    assert len(nome) == 37
    out = abreviar_nome_apac(nome)
    assert out == "AAAA BBBBBBBBBB CCCCCCCCCC D"
    assert len(out) <= APAC_MAX_NOME

    # Ainda maior: abrevia ultimo e penultimo
    nome2 = "AAAAAAAAAA BBBBBBBBBB CCCCCCCCCC DDDDDDDDDD"
    assert len(nome2) > APAC_MAX_NOME
    out2 = abreviar_nome_apac(nome2)
    assert len(out2) <= APAC_MAX_NOME
    partes = out2.split()
    assert partes[0] == "AAAAAAAAAA"
    assert len(partes[-1]) == 1
    assert len(partes[-2]) == 1


def test_token_unico_maior_que_limite_trunca():
    nome = "A" * 40
    out = abreviar_nome_apac(nome)
    assert out == "A" * APAC_MAX_NOME
    assert len(out) == APAC_MAX_NOME


def test_nome_mae_mesma_funcao():
    mae = "RITA MARIA DA CONCEICAO SILVA CUTRIM EXTRA"
    out = abreviar_nome_apac(mae)
    assert len(out) <= APAC_MAX_NOME
    assert out.startswith("RITA")
