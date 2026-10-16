"""Stamp de autenticação BIODATA e renovação preventiva (>= 3h30)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from apac_bot.config import AppConfig
from apac_bot.connectors.biodata import (
    _abrir_ou_reusar_sessao,
    _renovar_sessao_preventiva,
)
from apac_bot.connectors.biodata_session_stamp import (
    SESSION_RENEW_AFTER,
    STAMP_FILENAME,
    gravar_last_auth_at,
    ler_last_auth_at,
    sessao_precisa_renovacao_preventiva,
    stamp_path,
)


def _cfg(tmp_path: Path, *, user_data: str = "browser_profile") -> AppConfig:
    return AppConfig(
        raw={
            "clinica_id": "c",
            "biodata": {
                "url": "https://exemplo.biodata.local/oftalmocentro91",
                "user_data_dir": user_data,
                "login": {
                    "locators": {
                        "campo_usuario": "#inputUsuario",
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


def test_stamp_ausente_precisa_renovar(tmp_path: Path):
    cfg = _cfg(tmp_path)
    assert ler_last_auth_at(cfg) is None
    assert sessao_precisa_renovacao_preventiva(cfg) is True


def test_stamp_recente_nao_precisa_renovar(tmp_path: Path):
    cfg = _cfg(tmp_path)
    agora = datetime.now(timezone.utc)
    gravar_last_auth_at(cfg, agora)
    assert sessao_precisa_renovacao_preventiva(cfg, agora) is False
    assert sessao_precisa_renovacao_preventiva(
        cfg, agora + timedelta(hours=3, minutes=29)
    ) is False


def test_stamp_antigo_precisa_renovar(tmp_path: Path):
    cfg = _cfg(tmp_path)
    agora = datetime.now(timezone.utc)
    gravar_last_auth_at(cfg, agora - SESSION_RENEW_AFTER)
    assert sessao_precisa_renovacao_preventiva(cfg, agora) is True
    gravar_last_auth_at(cfg, agora - SESSION_RENEW_AFTER - timedelta(minutes=1))
    assert sessao_precisa_renovacao_preventiva(cfg, agora) is True


def test_gravar_ler_roundtrip(tmp_path: Path):
    cfg = _cfg(tmp_path)
    when = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)
    gravar_last_auth_at(cfg, when)
    path = stamp_path(cfg)
    assert path.name == STAMP_FILENAME
    assert path.is_file()
    lido = ler_last_auth_at(cfg)
    assert lido is not None
    assert lido == when


def test_renovar_sessao_preventiva_sair_e_login(tmp_path: Path):
    cfg = _cfg(tmp_path)
    page = MagicMock()
    with patch(
        "apac_bot.connectors.biodata._pagina_autenticada", return_value=True
    ), patch(
        "apac_bot.connectors.biodata._menu_lateral_visivel", return_value=False
    ), patch(
        "apac_bot.connectors.biodata._sair_para_login"
    ) as mock_sair, patch(
        "apac_bot.connectors.biodata.ensure_biodata_login"
    ) as mock_login, patch(
        "apac_bot.connectors.biodata._sessao_biodata_ok", return_value=True
    ), patch(
        "apac_bot.connectors.biodata.gravar_last_auth_at"
    ) as mock_gravar, patch(
        "apac_bot.connectors.biodata.sessao_precisa_renovacao_preventiva",
        return_value=False,
    ):
        _renovar_sessao_preventiva(page, cfg)
    mock_sair.assert_called_once()
    mock_login.assert_called_once_with(page, cfg, force_full=True)
    mock_gravar.assert_not_called()


def test_abrir_ou_reusar_chama_renovacao_quando_stamp_antigo(tmp_path: Path):
    cfg = _cfg(tmp_path)
    agora = datetime.now(timezone.utc)
    gravar_last_auth_at(cfg, agora - SESSION_RENEW_AFTER - timedelta(minutes=5))
    page = MagicMock()
    with patch(
        "apac_bot.connectors.biodata._renovar_sessao_preventiva"
    ) as mock_renovar, patch(
        "apac_bot.connectors.biodata._url_home_biodata",
        return_value="https://exemplo.biodata.local/oftalmocentro91/home",
    ), patch(
        "apac_bot.connectors.biodata._dismiss_blocking_overlays"
    ), patch(
        "apac_bot.connectors.biodata.tratar_reauth_se_necessario"
    ), patch(
        "apac_bot.connectors.biodata._tem_application_error", return_value=False
    ), patch(
        "apac_bot.connectors.biodata._sessao_biodata_ok", return_value=True
    ):
        _abrir_ou_reusar_sessao(page, cfg)
    mock_renovar.assert_called_once_with(page, cfg)
    page.goto.assert_called()


def test_abrir_ou_reusar_nao_renova_com_stamp_recente(tmp_path: Path):
    cfg = _cfg(tmp_path)
    gravar_last_auth_at(cfg, datetime.now(timezone.utc))
    page = MagicMock()
    with patch(
        "apac_bot.connectors.biodata._renovar_sessao_preventiva"
    ) as mock_renovar, patch(
        "apac_bot.connectors.biodata._url_home_biodata",
        return_value="https://exemplo.biodata.local/oftalmocentro91/home",
    ), patch(
        "apac_bot.connectors.biodata._dismiss_blocking_overlays"
    ), patch(
        "apac_bot.connectors.biodata.tratar_reauth_se_necessario"
    ), patch(
        "apac_bot.connectors.biodata._tem_application_error", return_value=False
    ), patch(
        "apac_bot.connectors.biodata._sessao_biodata_ok", return_value=True
    ):
        _abrir_ou_reusar_sessao(page, cfg)
    mock_renovar.assert_not_called()
    page.goto.assert_called()
