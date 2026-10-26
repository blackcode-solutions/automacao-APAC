"""Testes do cliente de licença (local, cache, grace, online)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from apac_bot.config import AppConfig
from apac_bot.license import (
    LICENSE_VERIFY_KEY,
    LOCAL_LICENSE_KEY,
    LOCAL_VALID_UNTIL,
    MSG_EXPIRADA,
    MSG_INVALIDA,
    MSG_LOCAL_EXPIRADA,
    MSG_SEM_CONEXAO,
    MSG_SUSPENSA,
    LicenseError,
    _mensagem_recusa_licenca,
    _post_check,
    ensure_license,
    license_enabled,
    sign_payload,
    verify_signature,
)


def _cfg(tmp_path: Path, **licenca) -> AppConfig:
    raw = {
        "clinica_id": "clinica_teste",
        "sistema_origem": "mock",
        "planilha": {
            "caminho": "data/x.xlsx",
            "aba": "Lançamentos",
            "colunas": {
                "PACIENTE": "PACIENTE",
                "COD": "COD",
                "AUDITOR": "AUDITOR",
                "NUMERACAO": "NUMERAÇÃO",
            },
        },
        "apac": {"titulo_janela": "APAC", "passos": []},
        "licenca": {
            "server_url": licenca.get("server_url", "http://127.0.0.1:8090"),
            "license_key": licenca.get("license_key", "key-abc"),
            "grace_dias": licenca.get("grace_dias", 14),
            "cache_path": str(tmp_path / "license_cache.json"),
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return AppConfig(raw=raw, path=path)


def _active_payload(clinica_id: str = "clinica_teste", *, days_ago: int = 0) -> dict:
    now = datetime.now(timezone.utc) - timedelta(days=days_ago)
    payload = {
        "clinica_id": clinica_id,
        "status": "active",
        "valid_until": (now + timedelta(days=30)).date().isoformat(),
        "server_time": now.isoformat(),
        "checked_at": now.isoformat(),
    }
    payload["signature"] = sign_payload(payload, LICENSE_VERIFY_KEY)
    return payload


def _online_mode():
    return patch("apac_bot.license.LICENSE_MODE", "online")


def test_verify_signature_roundtrip():
    payload = _active_payload()
    assert verify_signature(payload)
    payload["status"] = "suspended"
    assert not verify_signature(payload)


def test_local_ok_with_embedded_key(tmp_path: Path):
    cfg = _cfg(tmp_path, license_key=LOCAL_LICENSE_KEY, server_url="")
    with patch("apac_bot.license.LICENSE_MODE", "local"):
        result = ensure_license(cfg, today=date(2026, 11, 22))
    assert result.ok
    assert result.source == "local"
    assert result.valid_until == LOCAL_VALID_UNTIL.isoformat()


def test_local_rejects_wrong_key(tmp_path: Path):
    cfg = _cfg(tmp_path, license_key="chave-errada", server_url="")
    with patch("apac_bot.license.LICENSE_MODE", "local"):
        with pytest.raises(LicenseError, match="inválida"):
            ensure_license(cfg, today=date(2026, 11, 22))


def test_local_rejects_on_cutoff_date(tmp_path: Path):
    cfg = _cfg(tmp_path, license_key=LOCAL_LICENSE_KEY, server_url="")
    with patch("apac_bot.license.LICENSE_MODE", "local"):
        with pytest.raises(LicenseError) as exc_info:
            ensure_license(cfg, today=LOCAL_VALID_UNTIL)
    assert str(exc_info.value) == MSG_LOCAL_EXPIRADA


def test_local_enabled_without_server_url(tmp_path: Path):
    cfg = _cfg(tmp_path, server_url="")
    with patch("apac_bot.license.LICENSE_MODE", "local"):
        assert license_enabled(cfg) is True


def test_skipped_when_server_url_empty(tmp_path: Path):
    cfg = _cfg(tmp_path, server_url="")
    with _online_mode():
        result = ensure_license(cfg)
    assert result.ok
    assert result.source == "skipped"


def test_online_success_writes_cache(tmp_path: Path):
    cfg = _cfg(tmp_path)
    payload = _active_payload()

    with _online_mode():
        with patch("apac_bot.license._post_check", return_value=payload):
            result = ensure_license(cfg)

    assert result.source == "online"
    cache_file = Path(cfg.raw["licenca"]["cache_path"])
    assert cache_file.is_file()
    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cached["signature"] == payload["signature"]


def test_403_raises_license_error(tmp_path: Path):
    cfg = _cfg(tmp_path)
    with _online_mode():
        with patch(
            "apac_bot.license._post_check",
            side_effect=LicenseError(MSG_SUSPENSA),
        ):
            with pytest.raises(LicenseError, match="suspensa"):
                ensure_license(cfg)


@pytest.mark.parametrize(
    ("detail", "esperado"),
    [
        ('{"detail":"Licença suspended"}', MSG_SUSPENSA),
        ('{"detail":"Licença expired"}', MSG_EXPIRADA),
        ('{"detail":"Licença inválida"}', MSG_INVALIDA),
        ("qualquer coisa", MSG_INVALIDA),
    ],
)
def test_mensagem_recusa_licenca_amigavel(detail: str, esperado: str):
    assert _mensagem_recusa_licenca(403, detail) == esperado
    assert "HTTP" not in esperado
    assert "{" not in esperado


def test_post_check_403_suspended_mensagem_amigavel():
    import io
    import urllib.error

    body = '{"detail":"Licença suspended"}'.encode("utf-8")
    err = urllib.error.HTTPError(
        url="http://127.0.0.1:8090/v1/license/check",
        code=403,
        msg="Forbidden",
        hdrs=None,
        fp=io.BytesIO(body),
    )
    with patch("apac_bot.license.urllib.request.urlopen", side_effect=err):
        with pytest.raises(LicenseError) as exc_info:
            _post_check(
                "http://127.0.0.1:8090",
                clinica_id="c1",
                license_key="k",
                app_version="1.0",
            )
    assert str(exc_info.value) == MSG_SUSPENSA


def test_offline_sem_cache_mensagem_amigavel(tmp_path: Path):
    cfg = _cfg(tmp_path)
    with _online_mode():
        with patch(
            "apac_bot.license._post_check",
            side_effect=ConnectionError("down"),
        ):
            with pytest.raises(LicenseError) as exc_info:
                ensure_license(cfg)
    assert str(exc_info.value) == MSG_SEM_CONEXAO


def test_offline_uses_cache_within_grace(tmp_path: Path):
    cfg = _cfg(tmp_path, grace_dias=14)
    payload = _active_payload(days_ago=2)
    cache_file = Path(cfg.raw["licenca"]["cache_path"])
    cache_file.write_text(json.dumps(payload), encoding="utf-8")

    with _online_mode():
        with patch(
            "apac_bot.license._post_check",
            side_effect=ConnectionError("down"),
        ):
            result = ensure_license(cfg)

    assert result.source == "cache"
    assert result.ok


def test_offline_rejects_expired_grace(tmp_path: Path):
    cfg = _cfg(tmp_path, grace_dias=14)
    payload = _active_payload(days_ago=20)
    cache_file = Path(cfg.raw["licenca"]["cache_path"])
    cache_file.write_text(json.dumps(payload), encoding="utf-8")

    with _online_mode():
        with patch(
            "apac_bot.license._post_check",
            side_effect=ConnectionError("down"),
        ):
            with pytest.raises(LicenseError, match="grace"):
                ensure_license(cfg)


def test_offline_rejects_tampered_cache(tmp_path: Path):
    cfg = _cfg(tmp_path)
    payload = _active_payload()
    payload["status"] = "active"
    payload["signature"] = "deadbeef"
    cache_file = Path(cfg.raw["licenca"]["cache_path"])
    cache_file.write_text(json.dumps(payload), encoding="utf-8")

    with _online_mode():
        with patch(
            "apac_bot.license._post_check",
            side_effect=ConnectionError("down"),
        ):
            with pytest.raises(LicenseError, match="assinatura|inutilizável"):
                ensure_license(cfg)


def test_missing_license_key_raises(tmp_path: Path):
    cfg = _cfg(tmp_path, license_key="")
    with _online_mode():
        with pytest.raises(LicenseError, match="license_key"):
            ensure_license(cfg)


def test_local_missing_license_key_raises(tmp_path: Path):
    cfg = _cfg(tmp_path, license_key="", server_url="")
    with patch("apac_bot.license.LICENSE_MODE", "local"):
        with pytest.raises(LicenseError, match="license_key"):
            ensure_license(cfg, today=date(2026, 11, 22))
