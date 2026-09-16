# VidGrab

![VidGrab icon](docs/icon.png)

[![CI](https://github.com/coherent17/VidGrab/actions/workflows/ci.yml/badge.svg)](https://github.com/coherent17/VidGrab/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/coherent17/VidGrab?label=release)](https://github.com/coherent17/VidGrab/releases)

A portable media downloader & editor for **Windows** and **Linux**. Grab a YouTube
video or an entire **playlist/channel** as **MP4**/**MP3**, or open a local file, then
**flip / trim / change speed** it — all in one self-contained binary with a dark/light
Qt GUI in 12 languages (🇺🇸 English, 🇹🇼 繁體中文, 🇯🇵 日本語, 🇰🇷 한국어, 🇪🇸 Español, 🇫🇷 Français, 🇩🇪 Deutsch, 🇵🇹 Português, 🇮🇹 Italiano, 🇷🇺 Русский, 🇻🇳 Tiếng Việt, 🇮🇩 Indonesia).

Built with Python, PySide6 (Qt), yt-dlp and ffmpeg, packaged with PyInstaller
(ffmpeg + ffplay embedded, no install required).

## Features

- YouTube → **MP4** or **MP4+MP3** (single-pass), resolution picker up to 4K / MP3 bitrate picker
- **Playlist & channel downloads** — every video in the selected quality, numbered `01 - …`, with per-video progress
- **Video info card** — paste a link and instantly see title, uploader, duration, available resolutions and playlist size before downloading
- **Auto-detect on paste** — info card updates by itself ~700 ms after pasting or finishing typing
- **Flip**, **trim**, and **speed (0.25×–4×)** for downloads and local files
- **Live preview** — hear/see your flip/trim/speed settings before committing
- **Local file mode** — edit MP4/MP3/MKV/WebM by drag & drop or Browse
- Offline indicator, dark/light theme, keyboard shortcuts (Ctrl+V paste, Ctrl+L clear log, F1 about)

## Quick start (developers)

### Linux / macOS

```bash
make setup     # create .venv + install deps (one-time)
make run       # launch the app
```

> Missing Qt system libraries? `sudo apt install -y python3-venv python3-pip ffmpeg libegl1 libgl1 libxkbcommon0 libfontconfig1 libxcb-cursor0 libxcb-xinerama0 libdbus-1-3`

### Windows

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m vidgrab
```

## Testing

```bash
make lint        # ruff check
make test        # pytest, incl. headless GUI smoke test (Qt offscreen)
```

## Building

- **Windows** — `scripts\build.ps1` (PowerShell) or `scripts\build.bat` (CMD), or `make build-windows` → `dist\VidGrab.exe`
- **Linux / macOS** — `make build` → `dist\VidGrab`
- CI on every push also builds both platforms; **releasing** = push a tag:

```bash
git tag v2.2.0
git push origin v2.2.0     # GitHub Release with VidGrab.exe + VidGrab-linux/.tar.xz
```

## Project layout

```
vidgrab/        the app (app.py UI, downloader.py logic, i18n.py, network.py, icon.py, _version.py)
assets/         bundled resources (icon.ico/png + NotoSans CJK TC/JP/KR fonts)
scripts/        build.bat / build.ps1 (Windows), generate_icon.py, write_version_info.py
docs/           project notes + icon.png preview (embedded above)
Makefile        dev task runner (setup / run / lint / test / build / clean)
VidGrab.spec    PyInstaller spec (bundles ffmpeg + Qt)
```

## Usage

**YouTube URL** → paste URL, pick MP4/MP3, optionally flip/trim/speed + preview → Download.
**Local file** → Edit page → Browse (or drag & drop) → set flip/trim/speed → Process.
Processed files are saved as `<name>_processed.<ext>` next to the original.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Video unavailable" / 403 | Update yt-dlp (`pip install -U yt-dlp`), rebuild |
| Slow or stuck | Merging takes a moment; wait for "Processing…" |
| Antivirus flags the exe | Common with PyInstaller; allowlist or sign the exe |
| Preview not working | ffplay is bundled; if missing, the app falls back to PATH |

Only download content you have the right to access. MIT licensed — use freely.