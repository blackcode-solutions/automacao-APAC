"""Persistência do horário da última autenticação BIODATA (renovação preventiva)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from apac_bot.config import AppConfig, config_dir, resolve_path
from apac_bot.logging_safe import setup_logging

log = setup_logging()

SESSION_RENEW_AFTER = timedelta(hours=3, minutes=30)
STAMP_FILENAME = "biodata_auth_stamp.json"


def stamp_path(cfg: AppConfig) -> Path:
    biodata = cfg.biodata
    user_data = resolve_path(
        config_dir(cfg), Path(str(biodata.get("user_data_dir", "browser_profile")))
    )
    return user_data / STAMP_FILENAME


def ler_last_auth_at(cfg: AppConfig) -> Optional[datetime]:
    path = stamp_path(cfg)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("[biodata-session-stamp] falha ao ler %s: %s", path, exc)
        return None
    iso = str(raw.get("last_auth_at") or "").strip()
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError as exc:
        log.warning(
            "[biodata-session-stamp] last_auth_at invalido em %s: %s", path, exc
        )
        return None


def gravar_last_auth_at(
    cfg: AppConfig, when: Optional[datetime] = None
) -> datetime:
    agora = when or datetime.now(timezone.utc)
    if agora.tzinfo is None:
        agora = agora.replace(tzinfo=timezone.utc)
    path = stamp_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"last_auth_at": agora.isoformat()}
    try:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        log.warning("[biodata-session-stamp] falha ao gravar %s: %s", path, exc)
        raise
    log.info(
        "[biodata-session-stamp] last_auth_at gravado: %s", agora.isoformat()
    )
    return agora


def sessao_precisa_renovacao_preventiva(
    cfg: AppConfig, agora: Optional[datetime] = None
) -> bool:
    """True se não há stamp ou se decorreram >= 3h30 desde a última auth."""
    last = ler_last_auth_at(cfg)
    if last is None:
        return True
    now = agora or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last) >= SESSION_RENEW_AFTER
