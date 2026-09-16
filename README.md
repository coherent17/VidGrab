# VidGrab

[![CI](https://github.com/coherent17/VidGrab/actions/workflows/ci.yml/badge.svg)](https://github.com/coherent17/VidGrab/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/coherent17/VidGrab?label=release)](https://github.com/coherent17/VidGrab/releases)

A portable media downloader & editor for **Windows** and **Linux** with a modern dark/light Qt GUI. Grab a YouTube video as **MP4** or **MP3**, or open a local file, then **flip** and **trim** it — all in one single self-contained binary.

Built with **Python**, **PySide6 (Qt)**, **yt-dlp**, **ffmpeg**, and packaged with **PyInstaller**.

## Features

- Download YouTube videos as **MP4** or simultaneous MP4 + MP3 (single-pass, ~50 % faster)
- **Flip** horizontally and/or vertically (ultrafast re-encode, audio copied)
- **Trim** to a time window (`90`, `1:30`, `1:02:03` or `start-end`) — YouTube downloads fetch only the wanted section when possible
- **Local file mode** — browse a local MP4/MP3/MKV/etc. from the **Edit** page and flip/trim it
- **Internet status bar** — live ● Online / ○ Offline indicator with ffmpeg + version in the `QStatusBar`; buttons disabled cleanly when offline
- **Sidebar navigation** — Download / Edit / Settings pages with a left-hand icon nav panel
- **Dark / Light theme toggle** — QSS-styled, persisted in `~/.config/vidgrab/config.json`
- **Single self-contained binary** (~100 MB) — ffmpeg embedded, no install, no `ffmpeg` folder needed
- **Linux release** — a self-contained x86_64 ELF is published alongside the Windows exe
- Keyboard shortcuts: Ctrl+V (paste), Ctrl+L (clear log), Enter (start), F1 (about)
- No Python required for end users

## Quick start (developers)

### Linux / WSL

The Windows commands (`python`, `.venv\Scripts\activate`) do **not** work in WSL. Use these instead.

**One-time setup** (needs your sudo password):

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip ffmpeg \
  libegl1 libgl1 libxkbcommon0 libfontconfig1 \
  libxcb-cursor0 libxcb-xinerama0 libdbus-1-3
```

**Run the app:**

```bash
chmod +x run.sh
./run.sh
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate      # NOT .venv\Scripts\activate
pip install -r requirements.txt
python -m vidgrab              # or the back-compat shim: python app.py
```

> **WSL GUI:** On Windows 11, WSLg shows the window automatically once the Qt system libraries are installed.

### Windows

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m vidgrab              # or the back-compat shim: python app.py
```

## Project structure

```
vidgrab/            the app
  __main__.py       python -m vidgrab entry point
  app.py            PySide6 (Qt) UI — sidebar + content panel (VidGrabWindow)
  downloader.py     yt-dlp download / ffmpeg flip & trim logic
  network.py        offline/captive-portal detection
  _version.py       single __version__ source
assets/             icon.ico + icon.png (regenerate via scripts/generate_icon.py)
ffmpeg/win|linux/   build-time ffmpeg binaries (embedded, not committed)
tests/              pytest suite incl. headless GUI smoke test
VidGrab.spec        PyInstaller spec (platform-aware, bundles ffmpeg + Qt)
```

## Build the Windows exe

On a **Windows** machine (or WSL with Windows interop):

1. Install [Python 3.10+](https://www.python.org/downloads/) — check **"Add python.exe to PATH"**
2. Copy the project to a **Windows path** (recommended), e.g. `C:\Users\You\VidGrab`
   *(Building from `\\wsl.localhost\...` fails in CMD unless you use the scripts below.)*
3. Ensure `ffmpeg/win/ffmpeg.exe` and `ffmpeg/win/ffprobe.exe` are present — they get embedded into the exe
4. Generate the icon (once): `python scripts/generate_icon.py`
5. Build:

**PowerShell** (recommended, works from WSL UNC paths):

```powershell
cd \\wsl.localhost\<Distro>\home\<you>\VidGrab
Set-ExecutionPolicy -Scope Process Bypass
.\build.ps1
```

**Command Prompt** (uses `pushd` to handle WSL UNC paths):

```bat
build.bat
```

Or copy to a native path first:

```bat
xcopy \\wsl.localhost\<Distro>\home\<you>\VidGrab C:\VidGrab /E /I
cd C:\VidGrab
build.bat
```

Output: `dist\VidGrab.exe` (single self-contained file) and `dist\VidGrab.zip`.

The **Linux binary** (`VidGrab-linux`) is produced by CI on `ubuntu-latest`:
it embeds a static ffmpeg build and needs only standard X11/Wayland libraries
on the target machine.

### Distributing to other users

Send users the single `VidGrab.exe` (or `VidGrab.zip`), or `VidGrab-linux` on
Linux. No install required — ffmpeg is embedded, so there is no separate
`ffmpeg` folder to ship. An `ffmpeg/win/` folder placed next to the exe still
overrides the embedded copy (useful for testing).

## Manual PyInstaller command

```bat
pip install -r requirements.txt
python scripts/generate_icon.py
pyinstaller VidGrab.spec --noconfirm
```

## Testing & CI

```bash
source .venv/bin/activate          # or .venv\Scripts\activate on Windows
pip install -r requirements-dev.txt
ruff check .                       # lint
pytest -v                          # 26 tests, no network needed
```

To also run the headless GUI smoke test (constructs the real window), use the
Qt offscreen platform (no display needed):

```bash
SMOKE_GUI=1 QT_QPA_PLATFORM=offscreen pytest -v
```

What CI does on every push to `main` / pull request:

- **test** (ubuntu): ruff lint, the full pytest suite (incl. the GUI smoke test
  on the Qt offscreen platform), and fails if any ffmpeg binary is ever tracked
  by git
- **build-windows** (windows-latest): downloads the gyan ffmpeg essentials build
  into `ffmpeg/win/`, embeds it via `VidGrab.spec`, produces the single-file
  exe + zip as a downloadable artifact
- **build-linux** (ubuntu-latest): embeds a static ffmpeg build into
  `ffmpeg/linux/`, produces the single-file ELF + `.tar.xz`

**Releases:** push a tag to ship a ready-to-download GitHub Release with
`VidGrab.exe`, `VidGrab.zip`, `VidGrab-linux` and `VidGrab-linux.tar.xz`:

```bash
git tag v2.1.0
git push origin v2.1.0
```

## Usage

### YouTube URL mode

1. Launch `VidGrab`
2. Paste a YouTube URL (or use **Paste**)
3. Tick **MP4** (video) and/or **MP3** (audio)
4. Optionally set **Flip** (Horizontal / Vertical) and **Trim** (Start / End)
5. Choose the output folder (default: `Downloads/VidGrab`)
6. Click **Download**

### Local file mode

1. Click **Edit** in the sidebar
2. Press **Browse…** and pick an MP4 / MP3 / MKV / WebM / etc.
3. Optionally set **Flip** and **Trim**
4. Choose the output folder
5. Click **Process**

Processed files are saved as `<name>_processed.<ext>` in the chosen folder. Downloaded files keep the video title.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Video unavailable" / 403 | Update yt-dlp: `pip install -U yt-dlp` then rebuild |
| Slow or stuck | Some videos need merging; wait for "Processing…" |
| Antivirus blocks exe | Common with PyInstaller; sign the exe or allowlist it |
| Local file fails | The output folder must be accessible and `ffmpeg` must be embedded or on PATH |

## Legal

Only download content you have the right to access. Respect YouTube's Terms of Service and copyright laws in your region.

## License

MIT — use and modify freely.