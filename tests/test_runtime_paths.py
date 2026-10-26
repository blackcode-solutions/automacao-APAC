"""Paths em modo desenvolvimento (não frozen)."""

from pathlib import Path

from apac_bot.runtime_paths import app_dir, bundle_dir, is_frozen, ui_assets_dir


def test_not_frozen_in_pytest():
    assert is_frozen() is False


def test_bundle_and_assets_exist():
    assert (bundle_dir() / "runtime_paths.py").is_file()
    assets = ui_assets_dir()
    assert assets.is_dir()
    assert any(assets.glob("splash_welcome.*"))


def test_app_dir_is_cwd(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert app_dir() == tmp_path.resolve()
