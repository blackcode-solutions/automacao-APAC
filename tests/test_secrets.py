import json
from pathlib import Path

from apac_bot.config import AppConfig
from apac_bot.secrets import load_biodata_credentials


def test_load_credentials(tmp_path: Path):
    secrets = tmp_path / "secrets.local.json"
    secrets.write_text(
        json.dumps({"usuario": "demo", "senha": "x"}, ensure_ascii=False),
        encoding="utf-8",
    )
    cfg = AppConfig(
        raw={
            "clinica_id": "c",
            "biodata": {"secrets_file": str(secrets)},
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
    creds = load_biodata_credentials(cfg)
    assert creds is not None
    assert creds.usuario == "demo"
    assert creds.senha == "x"


def test_missing_secrets_returns_none(tmp_path: Path):
    cfg = AppConfig(
        raw={
            "clinica_id": "c",
            "biodata": {"secrets_file": "nao_existe.json"},
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
    assert load_biodata_credentials(cfg) is None
