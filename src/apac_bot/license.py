"""Validação de licença: modo local (trial) ou online + cache com grace."""

from __future__ import annotations

import hmac
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from apac_bot.config import AppConfig

# "local" = chave embutida + data de corte (sem API). "online" = servidor.
LICENSE_MODE = "local"

# Chave e validade do build de validação (modo local).
LOCAL_LICENSE_KEY = "20744435-73cc-462d-ab29-059f51afa56d"
LOCAL_VALID_UNTIL = date(2026, 11, 23)  # neste dia já bloqueia

# Deve coincidir com LICENSE_SIGNING_SECRET do license-server em produção.
# Troque juntos ao publicar o servidor e uma nova build do app.
LICENSE_VERIFY_KEY = "dev-only-change-me-license-hmac"

DEFAULT_GRACE_DIAS = 14
DEFAULT_CACHE_REL = "data/license_cache.json"
CHECK_TIMEOUT_S = 8

log = logging.getLogger("apac_bot.license")


class LicenseError(Exception):
    """Licença inválida ou indisponível além do grace."""


@dataclass(frozen=True)
class LicenseResult:
    ok: bool
    source: str  # online | cache | skipped | local
    message: str
    status: str = ""
    valid_until: str = ""

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(raw: str) -> Optional[datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            dt = datetime.fromisoformat(text)
            return dt.replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def mask_license_key(key: str) -> str:
    text = str(key or "").strip()
    if len(text) <= 8:
        return "***"
    return f"{text[:4]}…{text[-4:]}"


def licenca_block(cfg: AppConfig) -> dict[str, Any]:
    return dict(cfg.raw.get("licenca") or {})


def license_enabled(cfg: AppConfig) -> bool:
    """Modo local: sempre ativo. Online: exige server_url."""
    if LICENSE_MODE == "local":
        return True
    url = str(licenca_block(cfg).get("server_url") or "").strip()
    return bool(url)

def grace_dias(cfg: AppConfig) -> int:
    raw = licenca_block(cfg).get("grace_dias", DEFAULT_GRACE_DIAS)
    try:
        dias = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_GRACE_DIAS
    return max(0, dias)


def cache_path(cfg: AppConfig) -> Path:
    bloco = licenca_block(cfg)
    rel = str(bloco.get("cache_path") or DEFAULT_CACHE_REL).strip()
    path = Path(rel)
    if not path.is_absolute():
        path = cfg.path.parent / path
    return path


def _canonical_payload(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_payload(payload: dict[str, Any], secret: str) -> str:
    import hashlib
    import hmac

    message = _canonical_payload(payload).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_signature(payload: dict[str, Any], secret: str = LICENSE_VERIFY_KEY) -> bool:
    import hmac

    expected = str(payload.get("signature") or "")
    if not expected or not secret:
        return False
    actual = sign_payload(payload, secret)
    return hmac.compare_digest(actual, expected)


def _read_cache(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("[license] cache ilegível: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    return data


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _cache_usable(
    cache: dict[str, Any],
    *,
    clinica_id: str,
    grace: int,
    now: Optional[datetime] = None,
    verify_key: str = LICENSE_VERIFY_KEY,
) -> tuple[bool, str]:
    if not verify_signature(cache, verify_key):
        return False, "cache com assinatura inválida"
    if str(cache.get("clinica_id") or "") != clinica_id:
        return False, "cache de outra clínica"
    if str(cache.get("status") or "") != "active":
        return False, "cache não está active"
    now = now or _utc_now()
    until = _parse_iso(str(cache.get("valid_until") or ""))
    if until is not None and until < now:
        return False, "valid_until expirado no cache"
    checked = _parse_iso(str(cache.get("checked_at") or cache.get("server_time") or ""))
    if checked is None:
        return False, "cache sem checked_at"
    age = now - checked
    if age > timedelta(days=grace):
        return False, f"grace de {grace} dia(s) esgotado"
    if age < timedelta(0):
        return False, "checked_at no futuro"
    return True, "ok"


MSG_SUSPENSA = (
    "Sua chave de acesso está suspensa. Entre em contato com o suporte da DG."
)
MSG_EXPIRADA = (
    "Sua chave de acesso expirou. Entre em contato com o suporte da DG."
)
MSG_INVALIDA = (
    "Chave de acesso inválida. Verifique a chave ou fale com o suporte da DG."
)
MSG_SEM_CONEXAO = (
    "Não foi possível conectar ao servidor de licença e não há autorização "
    "salva neste computador. Verifique a rede ou fale com o suporte da DG."
)
MSG_LOCAL_EXPIRADA = (
    "O período de avaliação deste sistema encerrou. "
    "Entre em contato com o suporte da DG."
)


def _ensure_license_local(
    cfg: AppConfig,
    *,
    today: Optional[date] = None,
) -> LicenseResult:
    """Valida chave embutida + data de corte (sem API)."""
    license_key = str(licenca_block(cfg).get("license_key") or "").strip()
    if not license_key:
        raise LicenseError(
            "Licença não configurada: preencha licenca.license_key no config."
        )
    if not hmac.compare_digest(license_key, LOCAL_LICENSE_KEY):
        raise LicenseError(MSG_INVALIDA)
    current = today if today is not None else date.today()
    if current >= LOCAL_VALID_UNTIL:
        raise LicenseError(MSG_LOCAL_EXPIRADA)
    return LicenseResult(
        ok=True,
        source="local",
        message="Licença ok (modo local).",
        status="active",
        valid_until=LOCAL_VALID_UNTIL.isoformat(),
    )

def _extract_detail(body: str) -> str:
    text = (body or "").strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict):
        return str(data.get("detail") or text)
    return text


def _mensagem_recusa_licenca(status_code: int, body: str) -> str:
    """Converte HTTP 403/etc. em texto para a clínica (sem JSON técnico)."""
    detail = _extract_detail(body).lower()
    if "suspended" in detail or "suspensa" in detail:
        return MSG_SUSPENSA
    if "expired" in detail or "expirad" in detail:
        return MSG_EXPIRADA
    if status_code in {401, 403}:
        return MSG_INVALIDA
    return MSG_INVALIDA


def _post_check(
    server_url: str,
    *,
    clinica_id: str,
    license_key: str,
    app_version: str,
) -> dict[str, Any]:
    base = server_url.rstrip("/")
    url = f"{base}/v1/license/check"
    body = json.dumps(
        {
            "clinica_id": clinica_id,
            "license_key": license_key,
            "app_version": app_version,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except OSError:
            detail = str(exc.reason)
        raise LicenseError(_mensagem_recusa_licenca(exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise ConnectionError(f"falha de rede ao checar licença: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LicenseError("resposta de licença inválida (JSON)") from exc
    if not isinstance(data, dict):
        raise LicenseError("resposta de licença inválida")
    return data


def ensure_license(
    cfg: AppConfig,
    *,
    app_version: str = "",
    verify_key: str = LICENSE_VERIFY_KEY,
    today: Optional[date] = None,
) -> LicenseResult:
    """
    Modo local: chave embutida + data de corte (sem API).
    Modo online: valida no servidor; em falha de rede usa cache no grace.
    Sem server_url no online → skipped (ok) para dev/legado.
    """
    if LICENSE_MODE == "local":
        return _ensure_license_local(cfg, today=today)

    if not license_enabled(cfg):
        return LicenseResult(
            ok=True,
            source="skipped",
            message="Checagem de licença desligada (licenca.server_url vazio).",
        )

    bloco = licenca_block(cfg)
    server_url = str(bloco.get("server_url") or "").strip()
    license_key = str(bloco.get("license_key") or "").strip()
    clinica_id = str(cfg.clinica_id or "").strip()
    if not license_key:
        raise LicenseError(
            "Licença não configurada: preencha licenca.license_key no config."
        )
    if not clinica_id:
        raise LicenseError("clinica_id é obrigatório para validar a licença.")

    path = cache_path(cfg)
    grace = grace_dias(cfg)

    try:
        data = _post_check(
            server_url,
            clinica_id=clinica_id,
            license_key=license_key,
            app_version=app_version,
        )
    except ConnectionError as exc:
        cache = _read_cache(path)
        if cache is None:
            raise LicenseError(MSG_SEM_CONEXAO) from exc
        ok, reason = _cache_usable(
            cache,
            clinica_id=clinica_id,
            grace=grace,
            verify_key=verify_key,
        )
        if not ok:
            raise LicenseError(
                f"Servidor de licença inacessível e cache inutilizável ({reason})."
            ) from exc
        log.warning("[license] usando cache offline: %s", exc)
        return LicenseResult(
            ok=True,
            source="cache",
            message="Licença ok (cache offline dentro do grace).",
            status=str(cache.get("status") or ""),
            valid_until=str(cache.get("valid_until") or ""),
        )
    except LicenseError:
        raise

    if not verify_signature(data, verify_key):
        raise LicenseError("Resposta de licença com assinatura inválida.")
    if str(data.get("status") or "") != "active":
        raise LicenseError(f"Licença não ativa: {data.get('status')}")
    if str(data.get("clinica_id") or "") != clinica_id:
        raise LicenseError("Resposta de licença não corresponde à clínica.")

    _write_cache(path, data)
    return LicenseResult(
        ok=True,
        source="online",
        message="Licença ok (online).",
        status="active",
        valid_until=str(data.get("valid_until") or ""),
    )
