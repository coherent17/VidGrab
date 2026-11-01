# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for VidGrab (Windows + Linux).

ffmpeg is embedded from a platform folder (`ffmpeg/win/ffmpeg.exe` on
Windows, `ffmpeg/linux/ffmpeg` on Linux, legacy `ffmpeg/` as fallback)
and extracted to sys._MEIPASS/ffmpeg at runtime. Assets (icon, CJK font,
flags) are bundled too.
"""

import os
import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

# --- icon / assets -------------------------------------------------------
_datas: list[tuple[str, str]] = []
# NotoSansTC renders the zh UI and burned-in Chinese subtitles (Studio).
for _name in ("icon.ico", "icon.png", "NotoSansTC-Regular.otf"):
    _src = str(ROOT / "assets" / _name)
    if os.path.isfile(_src):
        _datas.append((_src, "assets"))

_win_icon = str(ROOT / "assets" / "icon.ico")

# --- country flag icons (language picker) ---------------------------------
_flags_dir = ROOT / "assets" / "flags"
if _flags_dir.is_dir():
    for _f in sorted(_flags_dir.glob("*.png")):
        _datas.append((str(_f), "assets/flags"))

# --- ffmpeg: platform-aware, with legacy fallback ------------------------
if sys.platform == "win32":
    _ffmpeg_names = ("ffmpeg.exe", "ffprobe.exe")
    _platform_subdir = "win"
else:
    _ffmpeg_names = ("ffmpeg", "ffprobe")
    _platform_subdir = "linux"

for _name in _ffmpeg_names:
    for _sub in (_platform_subdir, ""):
        _src = str(ROOT / "ffmpeg" / _sub / _name) if _sub else str(ROOT / "ffmpeg" / _name)
        if os.path.isfile(_src):
            _datas.append((_src, "ffmpeg"))
            break

# --- auto captions: faster-whisper's voice-filter model + native libraries ---
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

_datas += collect_data_files("faster_whisper")  # assets/silero_vad*.onnx
_binaries = collect_dynamic_libs("ctranslate2")

a = Analysis(
    [str(ROOT / "vidgrab" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=[
        "yt_dlp",
        "yt_dlp.extractor",
        "certifi",
        "packaging",
        "vidgrab",
        "vidgrab.app",
        "vidgrab.captions",
        "vidgrab.downloader",
        "vidgrab.downloads_panel",
        "vidgrab.i18n",
        "vidgrab.jobs",
        "vidgrab.network",
        "vidgrab.preview",
        "vidgrab.studio",
        "vidgrab.studio_page",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtMultimedia",
        "PySide6.QtWidgets",
        "faster_whisper",
        "ctranslate2",
        "onnxruntime",
        "tokenizers",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # PyAV bundles a second ffmpeg (~130 MB); captions decode with ours
        "av",
        # PySide6 modules we don't use — keeps the bundle smaller
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
        "PySide6.QtBluetooth",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtHelp",
        "PySide6.QtLocation",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtNfc",
        "PySide6.QtPositioning",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtQuickWidgets",
        "PySide6.QtRemoteObjects",
        "PySide6.QtSensors",
        "PySide6.QtSerialBus",
        "PySide6.QtSerialPort",
        "PySide6.QtSql",
        "PySide6.QtSvg",
        "PySide6.QtSvgWidgets",
        "PySide6.QtTest",
        "PySide6.QtTextToSpeech",
        "PySide6.QtUiTools",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngine",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets",
    ],
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
    icon=_win_icon if (sys.platform == "win32" and os.path.isfile(_win_icon)) else None,
    version=str(ROOT / "version_info.txt") if sys.platform == "win32" else None,
)
