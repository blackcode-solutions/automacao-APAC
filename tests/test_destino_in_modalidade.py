"""CBC-DST-IN (destino_in) conforme apac.modalidade."""

from apac_bot.config import MODALIDADE_GLAUCOMA, MODALIDADE_PADRAO
from apac_bot.set_pipeline import destino_in_para_modalidade


def test_destino_in_padrao_m():
    assert destino_in_para_modalidade(MODALIDADE_PADRAO) == "M"
    assert destino_in_para_modalidade("padrao") == "M"
    assert destino_in_para_modalidade("") == "M"


def test_destino_in_glaucoma_e():
    assert destino_in_para_modalidade(MODALIDADE_GLAUCOMA) == "E"
    assert destino_in_para_modalidade("glaucoma") == "E"
