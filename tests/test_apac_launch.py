import json
from pathlib import Path

import pytest

from apac_bot.apac import ApacBlockedError, pids_do_processo, resolver_caminho_exe
from apac_bot.config import AppConfig


def _cfg(tmp_path: Path, caminho_exe: str | None = None) -> AppConfig:
    example = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
    if caminho_exe is None:
        example["apac"].pop("caminho_exe", None)
    else:
        example["apac"]["caminho_exe"] = caminho_exe
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(example), encoding="utf-8")
    return AppConfig(raw=example, path=cfg_path)


def test_resolver_usa_caminho_configurado(tmp_path: Path):
    pasta = tmp_path / "MeuAPAC"
    pasta.mkdir()
    exe = pasta / "APAC.exe"
    exe.write_bytes(b"MZ")
    cfg = _cfg(tmp_path, str(exe))
    assert resolver_caminho_exe(cfg) == exe.resolve()


def test_resolver_ignora_config_inexistente_e_usa_fallback_pasta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Simula disco: raiz temporária com pasta APAC\APAC.exe
    root = tmp_path / "drive"
    pasta = root / "APAC"
    pasta.mkdir(parents=True)
    exe = pasta / "APAC.exe"
    exe.write_bytes(b"MZ")

    cfg = _cfg(tmp_path, r"C:\caminho\inexistente\APAC.exe")
    # Impede o DEFAULT_APAC_EXE real da máquina de “ganhar” o teste
    monkeypatch.setattr("apac_bot.apac.DEFAULT_APAC_EXE", root / "nao_existe" / "APAC.exe")
    found = resolver_caminho_exe(cfg, drive_root=root)
    assert found == exe.resolve()


def test_resolver_erro_quando_nao_acha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "vazio"
    root.mkdir()
    cfg = _cfg(tmp_path, r"C:\nao\existe\APAC.exe")
    monkeypatch.setattr("apac_bot.apac.DEFAULT_APAC_EXE", root / "x" / "APAC.exe")
    with pytest.raises(ApacBlockedError, match="não encontrado"):
        resolver_caminho_exe(cfg, drive_root=root)


def test_pids_do_processo_parseia_tasklist(monkeypatch: pytest.MonkeyPatch):
    csv = '"APAC.exe","4321","Console","1","10.000 K"\n'

    def fake_check_output(*_a, **_k):
        return csv

    monkeypatch.setattr("apac_bot.apac.subprocess.check_output", fake_check_output)
    assert pids_do_processo("APAC.exe") == [4321]


def test_pids_do_processo_vazio(monkeypatch: pytest.MonkeyPatch):
    def fake_check_output(*_a, **_k):
        return "INFORMAÇÕES: nenhuma tarefa em execução correspondente aos critérios especificados.\n"

    monkeypatch.setattr("apac_bot.apac.subprocess.check_output", fake_check_output)
    assert pids_do_processo("APAC.exe") == []
