# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for VidGrab (Windows + Linux + macOS).

ffmpeg is embedded from a platform folder (`ffmpeg/win/ffmpeg.exe` on
Windows, `ffmpeg/linux/ffmpeg` on Linux, legacy `ffmpeg/` as fallback)
and extracted to sys._MEIPASS/ffmpeg at runtime. Assets (icon, CJK font,
flags) are bundled too.

macOS builds a VidGrab.app (one folder, not one file: a one-file binary would
unpack itself at every launch and can't be signed) and does *not* embed ffmpeg:
the only static build with libass is not redistributable, so the app downloads
the pinned one on first run (vidgrab/ffmpeg_fetch.py).
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

for _name in () if sys.platform == "darwin" else _ffmpeg_names:
    for _sub in (_platform_subdir, ""):
        _src = str(ROOT / "ffmpeg" / _sub / _name) if _sub else str(ROOT / "ffmpeg" / _name)
        if os.path.isfile(_src):
            _datas.append((_src, "ffmpeg"))
            break

# --- auto captions: faster-whisper (CPU / NVIDIA) and OpenVINO (Intel GPU) ---
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

_datas += collect_data_files("faster_whisper")  # assets/silero_vad*.onnx
_binaries = collect_dynamic_libs("ctranslate2")
# OpenVINO reads the Whisper models as IR and runs them on its CPU / GPU plugins.
# Its libs/ folder is copied whole (frontends and plugins are found by file name
# next to libopenvino) minus what we never use: readers for ONNX, TensorFlow Lite,
# Paddle and GGUF models, the C API and the NPU (its compiler alone is ~100 MB).
from PyInstaller.utils.hooks import get_package_paths

_OV_SKIP = ("onnx", "paddle", "tensorflow_lite", "gguf", "npu", "openvino_c.")
for _pkg in ("openvino", "openvino_genai", "openvino_tokenizers"):
    _pkg_dir = Path(get_package_paths(_pkg)[1])
    # libs/: OpenVINO's plugins and frontends; lib/: the tokenizer extension the
    # Whisper models load by path (nothing imports it, so PyInstaller can't see it)
    for _sub in ("libs", "lib"):
        for _f in sorted((_pkg_dir / _sub).glob("*")):
            if _f.is_file() and not any(skip in _f.name.lower() for skip in _OV_SKIP):
                _binaries.append((str(_f), f"{_pkg}/{_sub}"))

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
        "openvino",
        "openvino_genai",
        "openvino_tokenizers",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # PyAV bundles a second ffmpeg (~130 MB); captions decode with ours
        "av",
        # OpenVINO's analytics client: never bundled (see vidgrab/captions.py)
        "openvino_telemetry",
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

if sys.platform == "darwin":
    # a folder app: the .app bundle holds the interpreter, libraries and assets
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="VidGrab",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        argv_emulation=False,
        target_arch=None,  # the runner's own architecture (arm64 or x86_64)
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="VidGrab")
    _icns = str(ROOT / "assets" / "icon.icns")  # made by the build (iconutil) from icon.png
    _version = {}
    exec((ROOT / "vidgrab" / "_version.py").read_text(encoding="utf-8"), _version)
    app = BUNDLE(
        coll,
        name="VidGrab.app",
        icon=_icns if os.path.isfile(_icns) else None,
        bundle_identifier="io.github.coherent17.vidgrab",
        version=_version["__version__"],
        info_plist={
            "CFBundleName": "VidGrab",
            "CFBundleDisplayName": "VidGrab",
            "CFBundleShortVersionString": _version["__version__"],
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )
else:
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
