# VidGrab

![VidGrab icon](docs/icon.png)

[![CI](https://github.com/coherent17/VidGrab/actions/workflows/ci.yml/badge.svg)](https://github.com/coherent17/VidGrab/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/coherent17/VidGrab?label=release)](https://github.com/coherent17/VidGrab/releases)

A portable media downloader & editor for **Windows** and **Linux**. Grab a YouTube
video or an entire **playlist/channel** as **MP4**/**MP3**, then use the **Studio**, an
editor-style workspace, to join songs into a medley or videos into a montage with
**subtitles** and **background music**. It all ships as one self-contained
executable with a dark/light Qt GUI in **English** and **繁體中文**.

Built with Python, PySide6 (Qt), yt-dlp and ffmpeg, packaged with PyInstaller
(ffmpeg + ffprobe embedded, no install required).

## Demo & user guide

- 🎬 **[Demo video](docs/VidGrab-demo.mp4)** (繁體中文 narration, about 2 min): paste three links, queue MP4 + MP3 downloads, trim clips with the timeline handles, add background music and a styled subtitle, then render
- 📘 **[User guide (PDF, 繁體中文)](docs/VidGrab-user-guide-zh-TW.pdf)**: every page and option, a step-by-step example and a FAQ

## Features

- YouTube → **MP4** or **MP4+MP3** (single-pass), resolution picker up to 4K / MP3 bitrate picker
- **Playlist & channel downloads** — every video in the selected quality, numbered `01 - …`, with per-video progress
- **Video info card** — paste a link and instantly see title, uploader, duration, available resolutions and playlist size before downloading
- **Auto-detect on paste** — info card updates by itself ~700 ms after pasting or finishing typing
- **Download queue**: paste one link or many at once. Each gets a row with thumbnail, progress, speed and ETA, plus **Cancel / Retry**
- **Recent downloads** are kept between sessions, with **Send to Studio**, which puts the file straight onto the Studio timeline along with its subtitles
- **YouTube subtitles**: also grab the captions (繁體中文 / 简体中文 / English / 日本語; uploaded or auto-generated), saved as `.srt` or burned into the video. Their timing follows any trim / speed change
- **Flip**, **trim** and **speed (0.25×–4×)** applied while downloading
- **Studio**, an editor-style workspace with no scrolling:
  - A large **preview** on top that plays the finished result, an **Inspector** beside it, and a **timeline** below where **every clip has its own row**, plus Subtitles and Music rows
  - **Visual trimming**: drag a clip's **left handle** to choose where it starts and its **right handle** to choose where it ends. The preview shows the frame under the handle, and the faint area shows the rest of the source. Drag a clip up or down to reorder (`Space` plays)
  - **Music medley**: join different songs (or parts of songs) into one MP3/M4A/WAV, with optional crossfade
  - **Video montage**: join different videos into one MP4. Mixed sizes and orientations are fitted to one frame (landscape, vertical 9:16 or square)
  - **Subtitles**: add a line at the playhead, **drag the text in the viewer to place it**, and drag or resize its block on the timeline to retime it. Snap lines to a 3×3 position grid, split or duplicate lines, and pick the text colour, a background box (or none), font, bold and fade in / out. Import / export `.srt`. Chinese is supported, and the render matches the preview
  - **Background music**: mix a song under the montage with separate volume controls, looping and fade-out
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
- CI on every push lints, tests (Linux + Windows) and builds both platforms
- **Releasing**: bump `vidgrab/_version.py`, add a `CHANGELOG.md` section, then push a matching tag:

```bash
git tag v3.0.0
git push origin v3.0.0
```

The release workflow checks that the tag matches the version, builds both platforms, and publishes a GitHub
Release with `VidGrab-windows-x64.exe`, `VidGrab-linux-x64` (+ `.tar.xz`) and `SHA256SUMS.txt`. The notes come
from the changelog section. Both binaries are standalone, with ffmpeg/ffprobe embedded.

## Project layout

```
vidgrab/        the app (app.py UI, downloader.py download/edit logic, studio.py join/subtitle/music
                engine, i18n.py, network.py, icon.py, _version.py)
assets/         bundled resources (icon.ico/png, flags, NotoSans CJK TC font)
scripts/        build.bat / build.ps1 (Windows), generate_icon.py, write_version_info.py
docs/           icon.png preview (embedded above)
Makefile        dev task runner (setup / run / lint / test / build / clean)
VidGrab.spec    PyInstaller spec (bundles ffmpeg + Qt)
```

## Usage

**YouTube URL** → paste URL, pick MP4/MP3, optionally flip/trim/speed + preview → Download.
**Studio** → pick *Video montage* or *Music medley* → **＋ Add media** (or drop files) → each clip gets its own
timeline row.
- Drag the clip's left and right handles to trim it.
- Drag a clip up or down to reorder it.
- (video) **＋ Subtitle** adds a line at the playhead. Type it in the Inspector, then drag the text in the preview to position it.
- (video) Use **♪ Background music** to add a song.
- **Render**.

### Typing Chinese subtitles on Linux / WSL

The Windows build uses the Windows IME directly. Linux apps need an input-method framework, and **under WSL the Windows
IME cannot reach Linux apps at all**. You can always paste Chinese text (Ctrl+V or the **Paste** button next to the
subtitle text). To type it, install ibus, which VidGrab picks up automatically:

```bash
sudo apt install ibus ibus-chewing   # or ibus-libpinyin for pinyin
ibus-daemon -drx                     # start it (add to ~/.profile to keep it)
```

Switch input methods with Super+Space (configure via `ibus-setup`).

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Video unavailable" / 403 | Update yt-dlp (`pip install -U yt-dlp`), rebuild |
| Slow or stuck | Merging takes a moment; wait for "Processing…" |
| Antivirus flags the exe | Common with PyInstaller; allowlist or sign the exe |
| Can't type Chinese in the Studio | See *Typing Chinese subtitles on Linux / WSL* above, or paste the text |
| Studio preview shows no picture | The packaged app includes QtMultimedia; from source, install PySide6 with multimedia support |

Only download content you have the right to access. MIT licensed — use freely.