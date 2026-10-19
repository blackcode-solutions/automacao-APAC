from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from apac_bot.config import AppConfig, ConfigError, biodata_modo, validate_config
from apac_bot.connectors import build_connector
from apac_bot.connectors.biodata_api import (
    BiodataApiConnector,
    BiodataApiError,
    paciente_from_api_row,
    password_sha512_hex,
    sha512_hex,
)


def _cfg(tmp_path: Path, *, modo: str | None = "api", api: dict | None = None) -> AppConfig:
    secrets = tmp_path / "secrets.local.json"
    secrets.write_text(
        json.dumps({"usuario": "@teste", "senha": "espiral"}),
        encoding="utf-8",
    )
    biodata: dict[str, Any] = {
        "secrets_file": str(secrets.name),
        "url": "https://exemplo.local/login",
    }
    if modo is not None:
        biodata["modo"] = modo
    if api is not None:
        biodata["api"] = api
    elif modo == "api":
        biodata["api"] = {
            "base_url": "https://apis.example.test/clinica/biodata",
            "id_sac": 91,
            "param_nome": "strCliente",
            "paginacao_nome": "0,20",
            "authorization_prefix": "",
        }
    raw = {
        "clinica_id": "clinica_teste",
        "sistema_origem": "biodata",
        "biodata": biodata,
        "planilha": {
            "caminho": str(tmp_path / "p.xlsx"),
            "aba": "Sheet1",
            "colunas": {
                "PACIENTE": "A",
                "COD": "B",
                "AUDITOR": "C",
                "NUMERACAO": "D",
            },
        },
        "planilha_prontuarios": {
            "caminho": str(tmp_path / "pront.xlsx"),
            "aba": "APAC ",
            "linha_cabecalho": 3,
            "colunas": {
                "PRONTUARIO": "Prontuário",
                "CLIENTE": "Cliente",
            },
        },
    }
    return AppConfig(raw=raw, path=tmp_path / "config.json")


def _paciente_json(**overrides: Any) -> dict[str, Any]:
    base = {
        "intClienteId": 1991955,
        "strCliente": "PACIENTE TESTE",
        "strCPF": "03345250390",
        "strCNS": "700604986333770",
        "strMae": "MAE TESTE",
        "datNascimento": "27/10/1981 00:00:00",
        "strSexo": "MASCULINO",
        "strEndereco": "RUA TESTE",
        "strBairro": "CENTRO",
        "strComplemento": "AP 1",
        "strCep": "65763000",
        "strNumero": "124",
    }
    base.update(overrides)
    return base


class _FakeResp:
    def __init__(self, payload: Any, status: int = 200):
        self._body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        self.status = status

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


def test_sha512_hex_known_value():
    assert len(sha512_hex("espiral")) == 128
    assert sha512_hex("espiral") == sha512_hex("espiral")


def test_password_sha512_uppercases_before_hash():
    assert password_sha512_hex("espiral") == sha512_hex("ESPIRAL")
    assert password_sha512_hex("espiral") != sha512_hex("espiral")
    assert password_sha512_hex("ESPIRAL") == password_sha512_hex("espiral")


def test_paciente_from_api_row_mapping():
    p = paciente_from_api_row(_paciente_json())
    assert p.id_paciente == "1991955"
    assert p.cpf == "03345250390"
    assert p.cns == "700604986333770"
    assert p.nome == "PACIENTE TESTE"
    assert p.nome_mae == "MAE TESTE"
    assert p.nascimento == "27/10/1981"
    assert p.sexo == "M"
    assert p.endereco == "RUA TESTE"
    assert p.cep == "65763000"
    assert p.bairro == "CENTRO"
    assert p.numero == "124"
    assert p.complemento == "AP 1"


def test_biodata_modo_defaults(tmp_path: Path):
    cfg_api = _cfg(tmp_path, modo=None, api={"base_url": "https://x/y", "id_sac": 1})
    assert biodata_modo(cfg_api) == "api"
    cfg_browser = _cfg(tmp_path, modo=None, api=None)
    cfg_browser.raw["biodata"].pop("api", None)
    assert biodata_modo(cfg_browser) == "browser"
    assert biodata_modo(_cfg(tmp_path, modo="browser")) == "browser"


def test_validate_api_skips_locators(tmp_path: Path):
    cfg = _cfg(tmp_path, modo="api")
    avisos = validate_config(cfg, for_biodata_real=True)
    assert avisos == []


def test_validate_biodata_exige_planilha_prontuarios(tmp_path: Path):
    cfg = _cfg(tmp_path, modo="api")
    cfg.raw.pop("planilha_prontuarios", None)
    with pytest.raises(ConfigError) as exc:
        validate_config(cfg)
    assert "planilha_prontuarios.caminho" in str(exc.value)


def test_validate_api_requires_secrets(tmp_path: Path):
    cfg = _cfg(tmp_path, modo="api")
    (tmp_path / "secrets.local.json").unlink()
    with pytest.raises(ConfigError) as exc:
        validate_config(cfg, for_biodata_real=True)
    assert "secrets.local.json" in str(exc.value)


def test_build_connector_api(tmp_path: Path):
    cfg = _cfg(tmp_path, modo="api")
    conn = build_connector("biodata", cfg)
    assert isinstance(conn, BiodataApiConnector)
    conn.close()


def test_autenticar_uses_sha512_and_listar_sends_authorization(tmp_path: Path):
    cfg = _cfg(tmp_path, modo="api")
    cfg.raw["biodata"]["api"]["authorization_prefix"] = "Bearer"
    calls: list[Any] = []

    def opener(request: Any, timeout: float = 0):
        calls.append(request)
        url = request.full_url
        if "/autenticar" in url:
            qs = parse_qs(urlparse(url).query)
            assert qs["username"] == ["@teste"]
            assert qs["password"] == [password_sha512_hex("espiral")]
            assert qs["password"] == [sha512_hex("ESPIRAL")]
            assert qs["idSAC"] == ["91"]
            return _FakeResp({"token": "tok-abc", "nome_usuario": "TESTE"})
        if "/clientes/listar" in url:
            assert request.get_header("Authorization") == "Bearer tok-abc"
            qs = parse_qs(urlparse(url).query)
            assert qs["clienteId"] == ["1991955"]
            return _FakeResp(_paciente_json())
        raise AssertionError(f"URL inesperada: {url}")

    conn = BiodataApiConnector(cfg, opener=opener)
    encontrado = conn.buscar_por_prontuario("1991955")
    assert encontrado is not None
    assert encontrado.nome == "PACIENTE TESTE"
    assert any("/autenticar" in c.full_url for c in calls)
    assert any("/clientes/listar" in c.full_url for c in calls)


def test_buscar_por_nome_lista_e_objeto(tmp_path: Path):
    cfg = _cfg(tmp_path, modo="api")
    state = {"n": 0}

    def opener(request: Any, timeout: float = 0):
        if "/autenticar" in request.full_url:
            return _FakeResp({"token": "t1"})
        state["n"] += 1
        if state["n"] == 1:
            return _FakeResp(
                [
                    _paciente_json(intClienteId=1, strCliente="A"),
                    _paciente_json(intClienteId=2, strCliente="B"),
                ]
            )
        return _FakeResp(_paciente_json(intClienteId=3, strCliente="UNICO"))

    conn = BiodataApiConnector(cfg, opener=opener)
    lista = conn.buscar_por_nome("QUALQUER")
    assert len(lista) == 2
    unico = conn.buscar_por_nome("UNICO")
    assert len(unico) == 1
    assert unico[0].id_paciente == "3"


def test_token_renovado_apos_401(tmp_path: Path):
    cfg = _cfg(tmp_path, modo="api")
    auth_count = {"n": 0}
    listar_count = {"n": 0}

    def opener(request: Any, timeout: float = 0):
        if "/autenticar" in request.full_url:
            auth_count["n"] += 1
            return _FakeResp({"token": f"tok-{auth_count['n']}"})
        listar_count["n"] += 1
        if listar_count["n"] == 1:
            assert request.get_header("Authorization") == "tok-stale"
            raise HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                hdrs=None,  # type: ignore[arg-type]
                fp=io.BytesIO(b"unauthorized"),
            )
        # Após 401, autenticar roda uma vez e o retry usa o token novo
        assert request.get_header("Authorization") == "tok-1"
        return _FakeResp(_paciente_json())

    conn = BiodataApiConnector(cfg, opener=opener)
    conn._token = "tok-stale"
    conn._token_expires_at = 1e12
    p = conn.buscar_por_prontuario("1991955")
    assert p is not None
    assert auth_count["n"] == 1
    assert listar_count["n"] == 2


def test_missing_base_url_raises(tmp_path: Path):
    cfg = _cfg(tmp_path, modo="api", api={"id_sac": 91})
    with pytest.raises(BiodataApiError, match="base_url"):
        BiodataApiConnector(cfg, opener=MagicMock())


def test_ler_cadastro_aberto_reconsulta(tmp_path: Path):
    cfg = _cfg(tmp_path, modo="api")

    def opener(request: Any, timeout: float = 0):
        if "/autenticar" in request.full_url:
            return _FakeResp({"token": "t"})
        return _FakeResp(_paciente_json())

    conn = BiodataApiConnector(cfg, opener=opener)
    assert conn.ler_cadastro_aberto() is None
    conn.buscar_por_prontuario("1991955")
    again = conn.ler_cadastro_aberto()
    assert again is not None
    assert again.id_paciente == "1991955"
