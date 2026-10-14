"""Testes do modal Autenticacao (reauth) sem browser real."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from apac_bot.config import AppConfig
from apac_bot.connectors.biodata import (
    _sessao_biodata_ok,
    _titulo_reauth,
    ensure_biodata_login,
    modal_reauth_visivel,
    tratar_reauth_se_necessario,
)


def _cfg(
    tmp_path: Path,
    *,
    titulo: str = "Autenticação",
    secrets: Path | None = None,
    url: str = "https://exemplo.biodata.local/login",
) -> AppConfig:
    return AppConfig(
        raw={
            "clinica_id": "c",
            "biodata": {
                "url": url,
                "reauth": {"titulo": titulo},
                "secrets_file": str(
                    secrets or (tmp_path / "missing-secrets.json")
                ),
                "login": {
                    "locators": {
                        "campo_usuario": "#inputUsuario",
                        "campo_senha": "input[name='password']",
                        "botao_entrar": "button[type='submit']",
                    }
                },
            },
            "planilha": {
                "caminho": "x.xlsx",
                "aba": "A",
                "colunas": {
                    "PACIENTE": "PACIENTE",
                    "COD": "COD.",
                    "AUDITOR": "AUDITOR",
                    "NUMERACAO": "NUMERAÇÃO",
                },
            },
        },
        path=tmp_path / "config.json",
    )


class _Locator:
    def __init__(self, n: int = 0):
        self._n = n
        self.first = self
        self.last = self

    def count(self) -> int:
        return self._n

    def filter(self, **_kwargs):
        return _Locator(self._n)

    def fill(self, *_a, **_k):
        return None

    def click(self, *_a, **_k):
        return None

    def wait_for(self, *_a, **_k):
        return None

    def is_visible(self) -> bool:
        return self._n > 0


def _page(
    *,
    heading: int = 0,
    text: int = 0,
    dialog: int = 0,
    textbox: int = 0,
    button: int = 0,
) -> MagicMock:
    page = MagicMock()

    def _by_role(role, **_kw):
        if role == "heading":
            return _Locator(heading)
        if role == "dialog":
            return _Locator(dialog)
        if role == "textbox":
            return _Locator(textbox)
        if role == "button":
            return _Locator(button)
        return _Locator(0)

    page.get_by_role.side_effect = _by_role
    page.get_by_text.return_value = _Locator(text)
    page.locator.return_value = _Locator(0)
    page.wait_for_timeout = MagicMock()
    page.reload = MagicMock()
    page.keyboard = SimpleNamespace(press=MagicMock())
    return page


def test_titulo_reauth_default_e_legado():
    assert _titulo_reauth(None) == "Autenticação"
    cfg = AppConfig(
        raw={"clinica_id": "c", "biodata": {"reauth": {"titulo": "text=Autenticação"}}},
        path=Path("x"),
    )
    assert _titulo_reauth(cfg) == "Autenticação"


def test_modal_reauth_ausente(tmp_path: Path):
    page = _page()
    assert modal_reauth_visivel(page, _cfg(tmp_path)) is False


def test_modal_reauth_por_heading(tmp_path: Path):
    page = _page(heading=1)
    assert modal_reauth_visivel(page, _cfg(tmp_path)) is True


def test_modal_reauth_por_texto(tmp_path: Path):
    page = _page(text=1)
    assert modal_reauth_visivel(page, _cfg(tmp_path)) is True


def test_tratar_reauth_sem_modal_nao_preenche(tmp_path: Path):
    page = _page()
    tratar_reauth_se_necessario(page, _cfg(tmp_path))
    page.get_by_role.assert_called()  # so deteccao
    # sem fill: textbox Senha nao deve ser preenchido via fill no fluxo ausente
    # (retorno cedo apos count==0)


def test_dismiss_nao_escapa_com_modal(tmp_path: Path):
    from apac_bot.connectors.biodata import _dismiss_blocking_overlays

    page = _page(heading=1)
    _dismiss_blocking_overlays(page, _cfg(tmp_path))
    page.keyboard.press.assert_not_called()


def test_tratar_reauth_login_e_reload(tmp_path: Path):
    secrets = tmp_path / "secrets.local.json"
    secrets.write_text(
        json.dumps({"usuario": "@EMANUELLE", "senha": "segredo"}, ensure_ascii=False),
        encoding="utf-8",
    )
    page = _page(heading=1, textbox=1, button=1)
    tratar_reauth_se_necessario(page, _cfg(tmp_path, secrets=secrets))
    page.reload.assert_called_once_with(wait_until="domcontentloaded")


def test_sessao_biodata_ok_false_com_modal(tmp_path: Path):
    page = _page(heading=1)
    page.url = "https://exemplo.biodata.local/home"
    assert _sessao_biodata_ok(page, _cfg(tmp_path)) is False


def test_ensure_biodata_login_force_full_goto_url(tmp_path: Path):
    secrets = tmp_path / "secrets.local.json"
    secrets.write_text(
        json.dumps({"usuario": "u", "senha": "s"}, ensure_ascii=False),
        encoding="utf-8",
    )
    login_url = "https://exemplo.biodata.local/login"
    page = _page()
    page.url = login_url
    # campo usuario visivel apos goto
    campo = _Locator(1)
    campo.is_visible = lambda timeout=0: True
    campo.is_enabled = lambda: True
    page.locator.return_value = campo
    page.fill = MagicMock()
    # evita esperar pos-login real
    from unittest.mock import patch

    with patch(
        "apac_bot.connectors.biodata._aguardar_login_ok",
        return_value=None,
    ), patch(
        "apac_bot.connectors.biodata._click_login",
        return_value=None,
    ), patch(
        "apac_bot.connectors.biodata._tem_application_error",
        return_value=False,
    ):
        ensure_biodata_login(
            page, _cfg(tmp_path, secrets=secrets, url=login_url), force_full=True
        )
    page.goto.assert_called_with(login_url, wait_until="domcontentloaded")
    page.fill.assert_any_call("#inputUsuario", "u")
    page.fill.assert_any_call("input[name='password']", "s")
