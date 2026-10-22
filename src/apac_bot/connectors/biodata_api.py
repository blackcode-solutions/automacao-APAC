"""Conector HTTP para consulta de pacientes no BIODATA (sem Playwright)."""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from apac_bot.config import AppConfig
from apac_bot.connectors.biodata import normalizar_cep_biodata
from apac_bot.models import PacienteDados
from apac_bot.normalize import sexo_para_apac
from apac_bot.secrets import load_biodata_credentials

log = logging.getLogger(__name__)

MODULE = "[biodata-api]"
TOKEN_TTL_S = 4 * 60 * 60
TOKEN_REFRESH_MARGIN_S = 5 * 60
DEFAULT_PARAM_NOME = "strCliente"
DEFAULT_PAGINACAO_ID = "0,1"
DEFAULT_PAGINACAO_NOME = "0,20"
DEFAULT_AUTH_PREFIX = "Bearer"
HTTP_TIMEOUT_S = 30
DEFAULT_INTERVALO_MS = 2500
DEFAULT_RETRY_REDE = 3
RETRY_BACKOFF_BASE_S = 0.5
# WinError: 10054 connection reset, 10053 aborted, 10060 timed out
_WINERRORS_REDE = frozenset({10054, 10053, 10060})
_ERRNOS_REDE = frozenset(
    {
        errno.ECONNRESET,
        errno.ETIMEDOUT,
        getattr(errno, "ECONNABORTED", 103),
    }
)


class BiodataApiError(Exception):
    """Falha de configuração ou chamada à API BIODATA."""


def sha512_hex(senha: str) -> str:
    return hashlib.sha512(senha.encode("utf-8")).hexdigest()


def password_sha512_hex(senha: str) -> str:
    """BIODATA: senha em maiúsculas antes do SHA-512."""
    return sha512_hex((senha or "").upper())


def _str_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalizar_nascimento_api(valor: Any) -> Optional[str]:
    """Extrai dd/mm/yyyy de datNascimento (pode vir com hora)."""
    text = _str_or_none(valor)
    if not text:
        return None
    parte = text.split()[0] if " " in text else text
    return parte or None


def paciente_from_api_row(row: dict[str, Any]) -> PacienteDados:
    """Mapeia um registro de clientes/listar para PacienteDados."""
    endereco = _str_or_none(row.get("strEndereco"))
    return PacienteDados(
        id_paciente=_str_or_none(row.get("intClienteId")),
        cpf=_str_or_none(row.get("strCPF")),
        cns=_str_or_none(row.get("strCNS")),
        nome=_str_or_none(row.get("strCliente")),
        nome_mae=_str_or_none(row.get("strMae")),
        nascimento=normalizar_nascimento_api(row.get("datNascimento")),
        sexo=sexo_para_apac(_str_or_none(row.get("strSexo"))),
        endereco=endereco,
        cep=normalizar_cep_biodata(_str_or_none(row.get("strCep"))),
        logradouro=endereco,
        bairro=_str_or_none(row.get("strBairro")),
        numero=_str_or_none(row.get("strNumero")),
        complemento=_str_or_none(row.get("strComplemento")),
    )


def _rows_from_listar_payload(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        for key in ("data", "dados", "items", "result", "lista", "clientes"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return [r for r in nested if isinstance(r, dict)]
        if "intClienteId" in payload or "strCliente" in payload:
            return [payload]
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    return []


def _int_config(valor: Any, default: int, *, minimo: int = 0) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return default
    return max(minimo, n)


def _eh_falha_rede(exc: BaseException) -> bool:
    """True para erros transitórios de rede (reset, timeout, etc.)."""
    if isinstance(exc, urllib.error.HTTPError):
        return False
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, OSError):
        win = getattr(exc, "winerror", None)
        if win in _WINERRORS_REDE:
            return True
        if getattr(exc, "errno", None) in _ERRNOS_REDE:
            return True
    return False


class BiodataApiConnector:
    """Consulta pacientes via API REST do BIODATA."""

    def __init__(
        self,
        cfg: AppConfig,
        *,
        opener: Any = None,
    ):
        self.cfg = cfg
        self._opener = opener or urllib.request.urlopen
        api = dict((cfg.biodata.get("api") or {}))
        base = str(api.get("base_url") or "").strip().rstrip("/")
        if not base:
            raise BiodataApiError(
                "biodata.api.base_url é obrigatório no modo API."
            )
        id_sac = api.get("id_sac")
        if id_sac is None or str(id_sac).strip() == "":
            raise BiodataApiError("biodata.api.id_sac é obrigatório no modo API.")
        self._base_url = base
        self._id_sac = str(id_sac).strip()
        self._param_nome = str(api.get("param_nome") or DEFAULT_PARAM_NOME).strip()
        self._paginacao_id = str(api.get("paginacao_id") or DEFAULT_PAGINACAO_ID)
        self._paginacao_nome = str(
            api.get("paginacao_nome") or DEFAULT_PAGINACAO_NOME
        )
        if "authorization_prefix" in api:
            self._auth_prefix = str(api.get("authorization_prefix") or "")
        else:
            self._auth_prefix = DEFAULT_AUTH_PREFIX
        self._intervalo_ms = _int_config(
            api.get("intervalo_ms", DEFAULT_INTERVALO_MS),
            DEFAULT_INTERVALO_MS,
        )
        self._retry_rede = _int_config(
            api.get("retry_rede", DEFAULT_RETRY_REDE),
            DEFAULT_RETRY_REDE,
        )
        self._last_request_mono: float = 0.0
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._ultimo_cliente_id: Optional[str] = None
        creds = load_biodata_credentials(cfg)
        if creds is None:
            raise BiodataApiError(
                "Modo API exige secrets.local.json com usuario e senha."
            )
        self._usuario = creds.usuario
        self._senha = creds.senha

    def close(self) -> None:
        self._token = None
        self._token_expires_at = 0.0

    def _aguardar_intervalo(self) -> None:
        """Espaça requests para não saturar a API (~24/min com 2500 ms)."""
        if self._intervalo_ms <= 0:
            self._last_request_mono = time.monotonic()
            return
        now = time.monotonic()
        if self._last_request_mono > 0:
            elapsed = now - self._last_request_mono
            need = self._intervalo_ms / 1000.0
            if elapsed < need:
                time.sleep(need - elapsed)
        self._last_request_mono = time.monotonic()

    def buscar_por_id(self, id_paciente: str) -> Optional[PacienteDados]:
        return self.buscar_por_prontuario(id_paciente)

    def buscar_por_prontuario(self, prontuario: str) -> Optional[PacienteDados]:
        pront = "".join(ch for ch in str(prontuario or "") if ch.isdigit())
        if not pront:
            return None
        log.info("%s buscando clienteId=%s", MODULE, pront)
        rows = self._listar({"clienteId": pront, "paginacao": self._paginacao_id})
        if not rows:
            return None
        paciente = paciente_from_api_row(rows[0])
        self._ultimo_cliente_id = pront
        return paciente

    def buscar_por_nome(
        self,
        nome: str,
        prontuario: Optional[str] = None,
    ) -> list[PacienteDados]:
        alvo = " ".join((nome or "").strip().split())
        if not alvo:
            return []
        log.info("%s buscando por nome (len=%s)", MODULE, len(alvo))
        rows = self._listar(
            {self._param_nome: alvo, "paginacao": self._paginacao_nome}
        )
        lista = [paciente_from_api_row(r) for r in rows]
        pront = "".join(ch for ch in str(prontuario or "") if ch.isdigit())
        if pront and len(lista) > 1:
            filtrados = [
                p
                for p in lista
                if p.id_paciente
                and "".join(ch for ch in p.id_paciente if ch.isdigit()) == pront
            ]
            if filtrados:
                lista = filtrados
        if len(lista) == 1 and lista[0].id_paciente:
            self._ultimo_cliente_id = "".join(
                ch for ch in lista[0].id_paciente if ch.isdigit()
            )
        return lista

    def ler_cadastro_aberto(self) -> Optional[PacienteDados]:
        """Reconsulta o último clienteId (refresh sem tela aberta)."""
        if not self._ultimo_cliente_id:
            return None
        return self.buscar_por_prontuario(self._ultimo_cliente_id)

    def _listar(self, extra_params: dict[str, str]) -> list[dict[str, Any]]:
        params = {
            "target_url": "null",
            "idSAC": self._id_sac,
            **extra_params,
        }
        try:
            payload = self._get_json("/clientes/listar", params, auth=True)
        except BiodataApiError:
            raise
        except Exception as exc:
            log.error("%s listar falhou: %s", MODULE, exc)
            raise BiodataApiError(f"Falha ao listar clientes: {exc}") from exc
        return _rows_from_listar_payload(payload)

    def _ensure_token(self, *, force: bool = False) -> str:
        now = time.time()
        if (
            not force
            and self._token
            and now < (self._token_expires_at - TOKEN_REFRESH_MARGIN_S)
        ):
            return self._token
        return self._autenticar()

    def _autenticar(self) -> str:
        password_hash = password_sha512_hex(self._senha)
        params = {
            "target_url": "null",
            "username": self._usuario,
            "password": password_hash,
            "specialuser": "",
            "externo": "",
            "idsac": self._id_sac,
            "idSAC": self._id_sac,
        }
        log.info("%s autenticando usuario (hash SHA-512)", MODULE)
        try:
            payload = self._get_json("/autenticar", params, auth=False)
        except BiodataApiError:
            raise
        except Exception as exc:
            log.error("%s autenticar falhou: %s", MODULE, exc)
            raise BiodataApiError(f"Falha na autenticação BIODATA: {exc}") from exc

        if not isinstance(payload, dict):
            raise BiodataApiError("Resposta de autenticar inválida (não é objeto).")
        token = _str_or_none(payload.get("token"))
        if not token:
            raise BiodataApiError("Resposta de autenticar sem token.")
        self._token = token
        self._token_expires_at = time.time() + TOKEN_TTL_S
        return token

    def _authorization_header(self, token: str) -> str:
        prefix = self._auth_prefix
        if prefix and not prefix.endswith(" "):
            return f"{prefix} {token}"
        return f"{prefix}{token}"

    def _get_json(
        self,
        path: str,
        params: dict[str, str],
        *,
        auth: bool,
        _retried: bool = False,
        _rede_attempt: int = 0,
    ) -> Any:
        self._aguardar_intervalo()

        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{self._base_url}{path}?{query}"
        headers: dict[str, str] = {"Accept": "application/json"}
        if auth:
            token = self._ensure_token()
            headers["Authorization"] = self._authorization_header(token)

        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with self._opener(request, timeout=HTTP_TIMEOUT_S) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                body = resp.read()
        except urllib.error.HTTPError as exc:
            if auth and exc.code == 401 and not _retried:
                log.warning("%s 401 - renovando token e repetindo", MODULE)
                self._autenticar()
                return self._get_json(
                    path, params, auth=auth, _retried=True, _rede_attempt=0
                )
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                # Corpo da resposta de erro pode estar indisponível
                detail = ""
            log.error("%s HTTP %s em %s: %s", MODULE, exc.code, path, detail)
            raise BiodataApiError(f"HTTP {exc.code} em {path}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            if _eh_falha_rede(exc) and _rede_attempt < self._retry_rede:
                wait = RETRY_BACKOFF_BASE_S * (2**_rede_attempt)
                motivo = getattr(exc, "reason", None) or exc
                log.warning(
                    "%s rede falhou em %s: %s — retry %s/%s em %.1fs",
                    MODULE,
                    path,
                    motivo,
                    _rede_attempt + 1,
                    self._retry_rede,
                    wait,
                )
                time.sleep(wait)
                return self._get_json(
                    path,
                    params,
                    auth=auth,
                    _retried=_retried,
                    _rede_attempt=_rede_attempt + 1,
                )
            motivo = getattr(exc, "reason", None) or exc
            log.error("%s rede falhou em %s: %s", MODULE, path, motivo)
            raise BiodataApiError(f"Falha de rede em {path}: {motivo}") from exc

        if status and int(status) >= 400:
            raise BiodataApiError(f"HTTP {status} em {path}")

        text = body.decode("utf-8", errors="replace").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            log.error("%s JSON inválido em %s", MODULE, path)
            raise BiodataApiError(f"JSON inválido em {path}") from exc


__all__ = [
    "BiodataApiConnector",
    "BiodataApiError",
    "DEFAULT_INTERVALO_MS",
    "DEFAULT_RETRY_REDE",
    "paciente_from_api_row",
    "password_sha512_hex",
    "sha512_hex",
]
