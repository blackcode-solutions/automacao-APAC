from apac_bot.normalize import cell_as_text, normalize_codigo, normalize_numeracao


def test_cell_as_text_preserva_zeros_em_string():
    assert cell_as_text("0412345678") == "0412345678"


def test_cell_as_text_float_inteiro():
    assert cell_as_text(123.0) == "123"


def test_numeracao_hifen_para_barra():
    assert normalize_numeracao("1234567890123-4", {"hifen_para_barra": True}) == "1234567890123/4"


def test_numeracao_sem_regra_preserva():
    assert normalize_numeracao("1234567890123-4", {}) == "1234567890123-4"


def test_codigo_zfill_somente_se_configurado():
    assert normalize_codigo("412345678", {"preencher_zeros_esquerda": 10}) == "0412345678"
    assert normalize_codigo("0412345678", {"preencher_zeros_esquerda": None}) == "0412345678"
    assert normalize_codigo("0412345678", {}) == "0412345678"
