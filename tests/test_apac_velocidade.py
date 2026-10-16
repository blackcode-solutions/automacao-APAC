"""Perfil apac.velocidade: tabela de pausas e digitacao."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from apac_bot.apac import (
    ApacAutomator,
    _TIMINGS_RAPIDO,
    _TIMINGS_SEGURO,
    aplicar_velocidade_apac,
    timing_apac,
)
from apac_bot.console_screen import CampoApac, ConsoleScreenError


def test_rapido_expoe_pausas_agressivas_e_char_keys():
    assert aplicar_velocidade_apac("rapido") == "rapido"
    assert timing_apac("pre_campo") == _TIMINGS_RAPIDO["pre_campo"]
    assert timing_apac("pre_campo") == 0.08
    assert timing_apac("pos_tab_apos_aceitar") == 0.12
    assert timing_apac("char_down") == 0.015
    assert timing_apac("char_up") == 0.020


def test_seguro_inalterado_inclui_char_keys():
    assert aplicar_velocidade_apac("seguro") == "seguro"
    assert timing_apac("pre_campo") == _TIMINGS_SEGURO["pre_campo"]
    assert timing_apac("pre_campo") == 1.0
    assert timing_apac("pos_tab_apos_aceitar") == 0.9
    assert timing_apac("char_down") == 0.035
    assert timing_apac("char_up") == 0.045


def test_aliases_rapido():
    for alias in ("rápido", "fast", "quick"):
        assert aplicar_velocidade_apac(alias) == "rapido"


def test_aguardar_avanco_campo_retorna_true_quando_cursor_muda():
    auto = object.__new__(ApacAutomator)
    auto._pids_apac = MagicMock(return_value=[1])
    with patch(
        "apac_bot.apac.identificar_campo_cursor",
        return_value=(CampoApac.NOME_MAE, "NOME DA MAE:", 0),
    ):
        assert auto._aguardar_avanco_campo(CampoApac.NOME, timeout_s=0.2) is True


def test_aguardar_avanco_campo_false_em_erro_de_buffer():
    auto = object.__new__(ApacAutomator)
    auto._pids_apac = MagicMock(return_value=[1])
    with patch(
        "apac_bot.apac.identificar_campo_cursor",
        side_effect=ConsoleScreenError("sem console"),
    ):
        assert auto._aguardar_avanco_campo(CampoApac.NOME, timeout_s=0.2) is False
