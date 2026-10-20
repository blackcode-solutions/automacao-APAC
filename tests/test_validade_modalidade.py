"""Offset de fim de validade conforme apac.modalidade."""

from __future__ import annotations

from pathlib import Path

from apac_bot.config import (
    MODALIDADE_GLAUCOMA,
    MODALIDADE_PADRAO,
    AppConfig,
    fim_offset_meses,
    normalizar_modalidade_cfg,
)


def test_fim_offset_meses_por_modalidade():
    assert fim_offset_meses(MODALIDADE_PADRAO) == 0
    assert fim_offset_meses(MODALIDADE_GLAUCOMA) == 2
    assert fim_offset_meses("APAC Glaucoma") == 2
    assert fim_offset_meses("") == 0


def test_normalizar_modalidade_cfg():
    assert normalizar_modalidade_cfg("glaucoma") == MODALIDADE_GLAUCOMA
    assert normalizar_modalidade_cfg("padrao") == MODALIDADE_PADRAO
    assert normalizar_modalidade_cfg(None) == MODALIDADE_PADRAO


def test_appconfig_modalidade(tmp_path: Path):
    cfg = AppConfig(
        raw={"clinica_id": "x", "apac": {"modalidade": "glaucoma"}},
        path=tmp_path / "c.json",
    )
    assert cfg.modalidade == MODALIDADE_GLAUCOMA
    assert fim_offset_meses(cfg.modalidade) == 2

    cfg_padrao = AppConfig(raw={"clinica_id": "x"}, path=tmp_path / "c.json")
    assert cfg_padrao.modalidade == MODALIDADE_PADRAO
