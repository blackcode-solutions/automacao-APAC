"""Paths do app em desenvolvimento vs PyInstaller (frozen)."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def bundle_dir() -> Path:
    """Raiz dos arquivos empacotados (MEIPASS) ou pasta do pacote `apac_bot`."""
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def app_dir() -> Path:
    """Pasta gravável ao lado do .exe (frozen) ou cwd (dev)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def ui_assets_dir() -> Path:
    """Splash/logos: empacotados em `apac_bot/ui/assets`."""
    if is_frozen():
        return bundle_dir() / "apac_bot" / "ui" / "assets"
    return Path(__file__).resolve().parent / "ui" / "assets"
