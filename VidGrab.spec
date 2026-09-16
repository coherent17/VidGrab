# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for VidGrab (Windows).

ffmpeg.exe / ffprobe.exe are embedded into the single-file exe and
extracted to a temp folder at runtime (sys._MEIPASS). Embedding is
skipped if they are missing so dev builds on Linux still work.
"""

import os
import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

# Embed the static (DLL-free) Windows ffmpeg builds next to the app.
_datas: list[tuple[str, str]] = []
for _name in ("ffmpeg.exe", "ffprobe.exe"):
    _src = str(ROOT / "ffmpeg" / _name)
    if os.path.isfile(_src):
        _datas.append((_src, "ffmpeg"))

# Bundle icon files so the running app can set the window icon from
# sys._MEIPASS / assets/ without needing a separate file next to the exe.
for _name in ("icon.ico", "icon.png"):
    _src = str(ROOT / "assets" / _name)
    if os.path.isfile(_src):
        _datas.append((_src, "assets"))

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        "yt_dlp",
        "yt_dlp.extractor",
        "certifi",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="VidGrab",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico") if sys.platform == "win32" else None,
)
