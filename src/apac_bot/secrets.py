from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from apac_bot.config import AppConfig, config_dir, resolve_path


class SecretsError(Exception):
    pass


@dataclass
class BiodataCredentials:
    usuario: str
    senha: str


def secrets_path(cfg: AppConfig) -> Path:
    biodata = cfg.biodata
    raw = biodata.get("secrets_file") or "secrets.local.json"
    return resolve_path(config_dir(cfg), Path(str(raw)))


def load_biodata_credentials(cfg: AppConfig) -> Optional[BiodataCredentials]:
    """
    Carrega credenciais de arquivo local (não versionado).
    Retorna None se o arquivo não existir — aí o login fica manual.
    """
    path = secrets_path(cfg)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SecretsError(f"JSON inválido em {path}: {exc}") from exc

    usuario = str(raw.get("usuario") or "").strip()
    senha = str(raw.get("senha") or "")
    if not usuario or not senha:
        raise SecretsError(
            f"{path} precisa ter 'usuario' e 'senha' preenchidos."
        )
    return BiodataCredentials(usuario=usuario, senha=senha)
