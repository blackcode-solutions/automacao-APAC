"""sair_ao_finalizar: logout UI antes de fechar o browser."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from apac_bot.config import AppConfig
from apac_bot.connectors.biodata import BiodataConnector


def _cfg(tmp_path: Path, *, sair: bool) -> AppConfig:
    return AppConfig(
        raw={
            "clinica_id": "c",
            "biodata": {
                "url": "https://exemplo.biodata.local/login",
                "sair_ao_finalizar": sair,
                "logout": {
                    "menu_usuario": "text=Usuário:",
                    "botao_sair": "button:has-text('Sair')",
                },
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


def _connector(cfg: AppConfig) -> BiodataConnector:
    conn = object.__new__(BiodataConnector)
    conn.cfg = cfg
    conn._page = MagicMock()
    conn._context = MagicMock()
    conn._pw = None
    conn._cadastro_aberto = True
    conn._fechar_dialogo_pesquisa = MagicMock()
    return conn


def test_close_com_flag_chama_sair(tmp_path: Path):
    conn = _connector(_cfg(tmp_path, sair=True))
    ctx = conn._context
    conn.sair_para_login = MagicMock()
    conn.close()
    conn.sair_para_login.assert_called_once()
    ctx.close.assert_called_once()
    assert conn._page is None


def test_close_sem_flag_nao_chama_sair(tmp_path: Path):
    conn = _connector(_cfg(tmp_path, sair=False))
    ctx = conn._context
    conn.sair_para_login = MagicMock()
    conn.close()
    conn.sair_para_login.assert_not_called()
    ctx.close.assert_called_once()
