"""CID principal por sufixo do procedimento (APAC Padrão)."""

from __future__ import annotations

import pytest

from apac_bot.cid_procedimento_padrao import (
    CID_POR_SUFIXO_PADRAO,
    CLASSIFICACAO_POR_SUFIXO_PADRAO,
    CidProcedimentoPadraoError,
    cid_principal_por_codigo_padrao,
    classificacao_por_codigo_padrao,
    normalizar_codigo_procedimento,
    sufixo_codigo,
)


@pytest.mark.parametrize(
    ("codigo", "cid"),
    [
        ("0405050224", "H112"),
        ("405050224", "H112"),
        ("0405050151", "A300"),
        ("0405050372", "H250"),
        ("0405050373", "H250"),
        ("0405050070", "H334"),
        ("0405050321", "H401"),
        ("0405050100", "A300"),
        ("0405050011", "H264"),
        ("0405050210", "H250"),
        ("0405050105", "H250"),
        ("0405050193", "H360"),
        ("0405050045", "H330"),
        ("0405050125", "A300"),
        ("0405050283", "H353"),
    ],
)
def test_cid_por_sufixo_tabela(codigo: str, cid: str) -> None:
    assert cid_principal_por_codigo_padrao(codigo) == cid


def test_todos_sufixos_mapeados_tem_entrada() -> None:
    assert len(CID_POR_SUFIXO_PADRAO) == 14


def test_sufixo_desconhecido() -> None:
    with pytest.raises(CidProcedimentoPadraoError) as exc:
        cid_principal_por_codigo_padrao("0405050999")
    assert "0999" in str(exc.value)
    assert "[cid-padrao]" in str(exc.value)


def test_codigo_vazio() -> None:
    with pytest.raises(Exception) as exc:
        cid_principal_por_codigo_padrao("")
    assert "ausente" in str(exc.value).lower()


def test_normalizar_e_sufixo() -> None:
    assert normalizar_codigo_procedimento("04.05.05-0372") == "0405050372"
    assert sufixo_codigo("0405050372") == "0372"


def test_classificacao_0283() -> None:
    assert classificacao_por_codigo_padrao("0405050283") == "001"


def test_classificacao_fallback_config() -> None:
    assert classificacao_por_codigo_padrao("0405050372", padrao="003") == "003"
    assert classificacao_por_codigo_padrao("0405050372", padrao="099") == "099"


def test_classificacao_mapa_minimo() -> None:
    assert CLASSIFICACAO_POR_SUFIXO_PADRAO["0283"] == "001"
