# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — onedir windowed SIS-DG-APAC."""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

SPECDIR = Path(SPECPATH).resolve()
ROOT = SPECDIR.parent
SRC = ROOT / "src"
ASSETS = SRC / "apac_bot" / "ui" / "assets"

ctk_datas, ctk_binaries, ctk_hidden = collect_all("customtkinter")

asset_datas = []
if ASSETS.is_dir():
    asset_datas.append((str(ASSETS), "apac_bot/ui/assets"))

a = Analysis(
    [str(SPECDIR / "frozen_main.py")],
    pathex=[str(SRC)],
    binaries=ctk_binaries,
    datas=ctk_datas + asset_datas,
    hiddenimports=list(ctk_hidden)
    + [
        "apac_bot",
        "apac_bot.cli",
        "apac_bot.ui.app",
        "apac_bot.runtime_paths",
        "playwright",
        "playwright.sync_api",
        "PIL",
        "fpdf",
        "openpyxl",
        "customtkinter",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SIS-DG-APAC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(SPECDIR / "sis-dg-apac.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SIS-DG-APAC",
)
