from apac_bot.sheet import nome_mae_valido, sanitizar_nome_opcao


def test_sanitizar_nome_opcao_remove_prontuario():
    assert (
        sanitizar_nome_opcao("1763812 SANDRA MARIA PEREIRA SILVA", "1763812")
        == "SANDRA MARIA PEREIRA SILVA"
    )
    assert (
        sanitizar_nome_opcao("1763812 SANDRA MARIA", None)
        == "SANDRA MARIA"
    )


def test_sanitizar_nome_opcao_so_digitos_vazio():
    assert sanitizar_nome_opcao("1763812", "1763812") == ""
    assert sanitizar_nome_opcao("20152", None) == ""


def test_nome_mae_valido_rejeita_igual_paciente():
    assert nome_mae_valido("MARIA DA SILVA", "SANDRA MARIA PEREIRA SILVA")
    assert not nome_mae_valido(
        "SANDRA MARIA PEREIRA SILVA", "SANDRA MARIA PEREIRA SILVA"
    )
    assert not nome_mae_valido("", "SANDRA")
    assert not nome_mae_valido(None, "SANDRA")
    assert not nome_mae_valido("1763812", "SANDRA")
