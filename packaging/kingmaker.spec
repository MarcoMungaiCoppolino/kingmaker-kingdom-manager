# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: one folder, windowed, the whole NiceGUI package and the
app's data files kept in their package layout.

    pyinstaller packaging/kingmaker.spec      (build.py does this)

`nicegui-pack` would build the same command line; the spec is kept in the
repository so the build is the same on this machine and in CI.
"""
import sys
from pathlib import Path

import nicegui

ROOT = Path(SPECPATH).resolve().parent
NAME = "Kingmaker Kingdom Manager" if sys.platform == "win32" else "kingmaker-kingdom-manager"
ICON = str(ROOT / "packaging" / "icon" / "kingmaker.ico") if sys.platform == "win32" else None

datas = [
    (str(Path(nicegui.__file__).parent), "nicegui"),
    (str(ROOT / "kingmaker" / "rules" / "data"), "kingmaker/rules/data"),
    (str(ROOT / "kingmaker" / "locale" / "lang"), "kingmaker/locale/lang"),
    (str(ROOT / "kingmaker" / "ui" / "static"), "kingmaker/ui/static"),
    (str(ROOT / "packaging" / "icon" / "kingmaker.ico"), "icon"),
    (str(ROOT / "packaging" / "icon" / "kingmaker.png"), "icon"),
    (str(ROOT / "kingmaker" / "launcher" / "guide"), "guide"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "OPEN_GAME_LICENSE.md"), "."),
    (str(ROOT / "NOTICE.md"), "."),
]

a = Analysis(
    [str(ROOT / "packaging" / "frozen_entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=["ifaddr", "engineio.async_drivers.asgi", "socketio", "PIL.Image",
                   "kingmaker.launcher.window", "kingmaker.main"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tests", "tools", "docs", "pytest", "IPython", "matplotlib", "numpy", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=ICON,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=NAME,
)
