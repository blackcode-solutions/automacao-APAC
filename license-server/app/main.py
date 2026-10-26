"""API de licença + admin HTML (Basic Auth)."""

from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.crypto import sign_payload
from app.db import STATUSES, LicenseStore
from app.settings import admin_password, db_path, public_url, signing_secret

log = logging.getLogger("license-server")

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
security = HTTPBasic()

app = FastAPI(title="SIS DG License Server", version="0.1.0")
_store: Optional[LicenseStore] = None


def get_store() -> LicenseStore:
    global _store
    if _store is None:
        _store = LicenseStore(db_path())
    return _store


def reset_store_for_tests(path: Path) -> LicenseStore:
    """Recria o store apontando para um DB de teste."""
    global _store
    _store = LicenseStore(path)
    return _store


def require_admin(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
) -> str:
    expected_user = "admin"
    expected_pass = admin_password()
    user_ok = secrets.compare_digest(credentials.username, expected_user)
    pass_ok = secrets.compare_digest(credentials.password, expected_pass)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


class CheckRequest(BaseModel):
    clinica_id: str = Field(min_length=1)
    license_key: str = Field(min_length=1)
    app_version: str = ""


def _parse_valid_until(raw: str) -> datetime:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("valid_until vazio")
    if len(text) == 10:
        # YYYY-MM-DD → fim do dia UTC
        d = date.fromisoformat(text)
        return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _effective_status(status_raw: str, valid_until: str, now: datetime) -> str:
    if status_raw == "suspended":
        return "suspended"
    try:
        until = _parse_valid_until(valid_until)
    except ValueError:
        log.warning("[license-server] valid_until inválido: %s", valid_until)
        return "expired"
    if until < now:
        return "expired"
    if status_raw == "expired":
        return "expired"
    return "active"


def _flash(request: Request) -> Optional[dict[str, str]]:
    kind = request.query_params.get("flash")
    msg = request.query_params.get("msg")
    if kind and msg:
        return {"kind": kind, "message": msg}
    return None


def _admin_ctx(**extra: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = {"public_url": public_url()}
    ctx.update(extra)
    return ctx


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/license/check")
def license_check(body: CheckRequest) -> dict[str, Any]:
    store = get_store()
    clinic = store.get_by_key(body.clinica_id.strip(), body.license_key.strip())
    now = datetime.now(timezone.utc)
    server_time = now.isoformat()

    if clinic is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Licença inválida",
        )

    eff = _effective_status(clinic.status, clinic.valid_until, now)
    store.touch_last_seen(clinic.clinica_id)

    if eff != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Licença {eff}",
        )

    payload: dict[str, Any] = {
        "clinica_id": clinic.clinica_id,
        "status": "active",
        "valid_until": clinic.valid_until,
        "server_time": server_time,
        "checked_at": server_time,
    }
    payload["signature"] = sign_payload(payload, signing_secret())
    return payload


@app.get("/admin", response_class=HTMLResponse)
def admin_list(
    request: Request,
    _: Annotated[str, Depends(require_admin)],
) -> HTMLResponse:
    clinics = get_store().list_all()
    return templates.TemplateResponse(
        request,
        "list.html",
        _admin_ctx(clinics=clinics, flash=_flash(request)),
    )


@app.get("/admin/new", response_class=HTMLResponse)
def admin_new_form(
    request: Request,
    _: Annotated[str, Depends(require_admin)],
) -> HTMLResponse:
    default_until = (date.today() + timedelta(days=30)).isoformat()
    return templates.TemplateResponse(
        request,
        "form.html",
        _admin_ctx(
            clinic=None,
            action="/admin/new",
            statuses=sorted(STATUSES),
            default_until=default_until,
            flash=_flash(request),
        ),
    )


@app.post("/admin/new")
def admin_create(
    _: Annotated[str, Depends(require_admin)],
    clinica_id: Annotated[str, Form()],
    nome: Annotated[str, Form()],
    status_value: Annotated[str, Form(alias="status")],
    valid_until: Annotated[str, Form()],
) -> RedirectResponse:
    cid = clinica_id.strip()
    if not cid or not nome.strip():
        return RedirectResponse(
            "/admin/new?flash=err&msg=ID+e+nome+s%C3%A3o+obrigat%C3%B3rios",
            status_code=303,
        )
    if get_store().get(cid) is not None:
        return RedirectResponse(
            "/admin/new?flash=err&msg=clinica_id+j%C3%A1+existe",
            status_code=303,
        )
    try:
        _parse_valid_until(valid_until)
        clinic = get_store().create(
            clinica_id=cid,
            nome=nome.strip(),
            status=status_value.strip(),
            valid_until=valid_until.strip(),
        )
    except ValueError as exc:
        return RedirectResponse(
            f"/admin/new?flash=err&msg={str(exc)}",
            status_code=303,
        )
    return RedirectResponse(
        f"/admin/{clinic.clinica_id}?flash=ok&msg=Cl%C3%ADnica+criada",
        status_code=303,
    )


@app.get("/admin/{clinica_id}", response_class=HTMLResponse)
def admin_edit_form(
    request: Request,
    clinica_id: str,
    _: Annotated[str, Depends(require_admin)],
) -> HTMLResponse:
    clinic = get_store().get(clinica_id)
    if clinic is None:
        raise HTTPException(status_code=404, detail="Clínica não encontrada")
    return templates.TemplateResponse(
        request,
        "form.html",
        _admin_ctx(
            clinic=clinic,
            action=f"/admin/{clinica_id}",
            statuses=sorted(STATUSES),
            default_until="",
            flash=_flash(request),
        ),
    )


@app.post("/admin/{clinica_id}")
def admin_update(
    clinica_id: str,
    _: Annotated[str, Depends(require_admin)],
    nome: Annotated[str, Form()],
    status_value: Annotated[str, Form(alias="status")],
    valid_until: Annotated[str, Form()],
    regenerate_key: Annotated[Optional[str], Form()] = None,
) -> RedirectResponse:
    try:
        _parse_valid_until(valid_until)
        updated = get_store().update(
            clinica_id,
            nome=nome.strip(),
            status=status_value.strip(),
            valid_until=valid_until.strip(),
            regenerate_key=bool(regenerate_key),
        )
    except ValueError as exc:
        return RedirectResponse(
            f"/admin/{clinica_id}?flash=err&msg={str(exc)}",
            status_code=303,
        )
    if updated is None:
        raise HTTPException(status_code=404, detail="Clínica não encontrada")
    return RedirectResponse(
        f"/admin/{clinica_id}?flash=ok&msg=Salvo",
        status_code=303,
    )


@app.post("/admin/{clinica_id}/delete")
def admin_delete(
    clinica_id: str,
    _: Annotated[str, Depends(require_admin)],
) -> RedirectResponse:
    get_store().delete(clinica_id)
    return RedirectResponse(
        "/admin?flash=ok&msg=Cl%C3%ADnica+exclu%C3%ADda",
        status_code=303,
    )
