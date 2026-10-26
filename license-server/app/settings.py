"""Configuração via variáveis de ambiente."""

from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT_DIR / "data" / "licenses.db"

# Default só para desenvolvimento local; produção DEVE sobrescrever via env.
DEFAULT_SIGNING_SECRET = "dev-only-change-me-license-hmac"


def admin_password() -> str:
    return os.environ.get("LICENSE_ADMIN_PASSWORD", "admin")


def signing_secret() -> str:
    return os.environ.get("LICENSE_SIGNING_SECRET", DEFAULT_SIGNING_SECRET)


def db_path() -> Path:
    raw = os.environ.get("LICENSE_DB_PATH", "").strip()
    if raw:
        return Path(raw)
    return DEFAULT_DB


def public_url() -> str:
    """URL que a clínica coloca em licenca.server_url (só exibida no admin)."""
    return os.environ.get("LICENSE_PUBLIC_URL", "").strip().rstrip("/")
