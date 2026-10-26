"""Testes do license-server (FastAPI TestClient)."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "license-server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.crypto import verify_signature  # noqa: E402
from app.main import app, reset_store_for_tests  # noqa: E402
from app.settings import DEFAULT_SIGNING_SECRET, admin_password  # noqa: E402


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LICENSE_ADMIN_PASSWORD", "test-admin")
    monkeypatch.setenv("LICENSE_SIGNING_SECRET", DEFAULT_SIGNING_SECRET)
    reset_store_for_tests(tmp_path / "licenses.db")
    with TestClient(app) as c:
        yield c


def _auth():
    return ("admin", "test-admin")


def test_health(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_check_active(client: TestClient):
    until = (date.today() + timedelta(days=30)).isoformat()
    create = client.post(
        "/admin/new",
        data={
            "clinica_id": "c1",
            "nome": "Clinica 1",
            "status": "active",
            "valid_until": until,
        },
        auth=_auth(),
        follow_redirects=False,
    )
    assert create.status_code == 303

    detail = client.get("/admin/c1", auth=_auth())
    assert detail.status_code == 200
    from app.main import get_store

    clinic = get_store().get("c1")
    assert clinic is not None
    assert clinic.license_key in detail.text

    resp = client.post(
        "/v1/license/check",
        json={
            "clinica_id": "c1",
            "license_key": clinic.license_key,
            "app_version": "1.0.0",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["clinica_id"] == "c1"
    assert verify_signature(body, DEFAULT_SIGNING_SECRET)


def test_check_wrong_key(client: TestClient):
    until = (date.today() + timedelta(days=30)).isoformat()
    client.post(
        "/admin/new",
        data={
            "clinica_id": "c2",
            "nome": "Clinica 2",
            "status": "active",
            "valid_until": until,
        },
        auth=_auth(),
        follow_redirects=False,
    )
    resp = client.post(
        "/v1/license/check",
        json={"clinica_id": "c2", "license_key": "errada", "app_version": ""},
    )
    assert resp.status_code == 403


def test_check_suspended(client: TestClient):
    until = (date.today() + timedelta(days=30)).isoformat()
    client.post(
        "/admin/new",
        data={
            "clinica_id": "c3",
            "nome": "Clinica 3",
            "status": "suspended",
            "valid_until": until,
        },
        auth=_auth(),
        follow_redirects=False,
    )
    from app.main import get_store

    clinic = get_store().get("c3")
    assert clinic is not None
    resp = client.post(
        "/v1/license/check",
        json={
            "clinica_id": "c3",
            "license_key": clinic.license_key,
            "app_version": "",
        },
    )
    assert resp.status_code == 403


def test_admin_requires_auth(client: TestClient):
    resp = client.get("/admin")
    assert resp.status_code == 401


def test_admin_list_shows_public_url(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("LICENSE_PUBLIC_URL", "https://lic.exemplo:8090")
    resp = client.get("/admin", auth=_auth())
    assert resp.status_code == 200
    assert "https://lic.exemplo:8090" in resp.text
    assert "licenca.server_url" in resp.text
