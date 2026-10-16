"""Confirmacao de paciente: sleep fixo apos Confirmar (tela demora a montar)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from apac_bot.connectors.biodata import BiodataConnector
from apac_bot.models import PacienteDados


def test_confirmar_opcao_usa_wait_1200_antes_de_extrair():
    conn = object.__new__(BiodataConnector)
    page = MagicMock()
    page.wait_for_timeout = MagicMock()

    def _locator(_sel, *_a, **_k):
        loc = MagicMock()
        loc.last = loc
        loc.first = loc
        loc.click = MagicMock()
        return loc

    page.locator.side_effect = _locator
    conn._page = page
    conn.cfg = SimpleNamespace(timeouts={"biodata_ms": 5000})
    conn._loc = MagicMock(
        return_value={
            "botao_confirmar_pesquisa": "button:has-text('Confirmar')",
            "campo_cpf": "#cpfCadastroClienteId",
            "campo_nome": "input[name='nome']",
        }
    )
    paciente = PacienteDados(nome="TESTE", cpf="12345678901")
    conn._tratar_reauth_se_necessario = MagicMock()
    conn._extrair_cadastro = MagicMock(return_value=paciente)

    opcao = MagicMock()
    resultado = BiodataConnector._confirmar_opcao_e_extrair(conn, opcao)

    assert resultado is paciente
    page.wait_for_timeout.assert_called_once_with(1200)
    conn._tratar_reauth_se_necessario.assert_called_once()
    conn._extrair_cadastro.assert_called_once()


def test_preencher_campo_busca_usa_fill_quando_dropdown_abre():
    conn = object.__new__(BiodataConnector)
    page = MagicMock()
    page.keyboard = SimpleNamespace(press=MagicMock())
    dropdown_opt = MagicMock()
    dropdown_opt.first = dropdown_opt
    dropdown_opt.wait_for = MagicMock()

    def _locator(sel, *_a, **_k):
        if "ts-dropdown" in sel:
            return dropdown_opt
        return MagicMock()

    page.locator.side_effect = _locator
    conn._page = page

    campo = MagicMock()
    campo.fill = MagicMock()
    campo.type = MagicMock()
    campo.click = MagicMock()

    BiodataConnector._preencher_campo_busca(conn, campo, "12345")

    campo.fill.assert_any_call("12345")
    page.keyboard.press.assert_called_with("End")
    campo.type.assert_not_called()


def test_preencher_campo_busca_fallback_type_se_dropdown_ausente():
    conn = object.__new__(BiodataConnector)
    page = MagicMock()
    page.keyboard = SimpleNamespace(press=MagicMock())
    dropdown_opt = MagicMock()
    dropdown_opt.first = dropdown_opt
    dropdown_opt.wait_for = MagicMock(side_effect=TimeoutError("no dropdown"))

    def _locator(sel, *_a, **_k):
        if "ts-dropdown" in sel:
            return dropdown_opt
        return MagicMock()

    page.locator.side_effect = _locator
    conn._page = page

    campo = MagicMock()
    campo.fill = MagicMock()
    campo.type = MagicMock()
    campo.click = MagicMock()

    BiodataConnector._preencher_campo_busca(conn, campo, "JOAO")

    campo.type.assert_called_once_with("JOAO", delay=20)
