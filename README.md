# VidGrab

[![CI](https://github.com/coherent17/VidGrab/actions/workflows/ci.yml/badge.svg)](https://github.com/coherent17/VidGrab/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/coherent17/VidGrab?label=release)](https://github.com/coherent17/VidGrab/releases)

A portable media downloader & editor for Windows with a small dark-theme GUI. Grab a YouTube video as **MP4** or **MP3**, or open a local file, then **flip** and **trim** it — all in one single self-contained `.exe`.

Built with **Python**, **tkinter**, **yt-dlp**, **ffmpeg**, and packaged with **PyInstaller**.

## Features

- Download YouTube videos as **MP4** or simultaneous MP4 + MP3 (192 kbps)
- **Flip** horizontally and/or vertically
- **Trim** to a time window (seconds `90`, `M:SS` `1:30`, or `H:MM:SS`)
- **Local file mode** — attach an MP4/MP3/MKV/etc. and flip/trim it, output to any folder
- App icon, dark UI, progress bar, built-in log
- **Single self-contained exe** (~94 MB) — ffmpeg is embedded inside the binary, no extra install, no `ffmpeg` folder needed
- No Python required for end users

## Quick start (developers)

### Linux / WSL

The Windows commands (`python`, `.venv\Scripts\activate`) do **not** work in WSL. Use these instead.

**One-time setup** (needs your sudo password):

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip python3-tk ffmpeg
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
python app.py
```

> **WSL GUI:** On Windows 11, WSLg shows the window automatically once `python3-tk` is installed.

### Windows

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## Build the Windows exe

On a **Windows** machine (or WSL with Windows interop):

1. Install [Python 3.10+](https://www.python.org/downloads/) — check **"Add python.exe to PATH"**
2. Copy the project to a **Windows path** (recommended), e.g. `C:\Users\You\VidGrab`
   *(Building from `\\wsl.localhost\...` fails in CMD unless you use the scripts below.)*
3. Ensure `ffmpeg/ffmpeg.exe` and `ffmpeg/ffprobe.exe` are present — they get embedded into the exe
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

### Distributing to other users

Send users the single `VidGrab.exe` (or the `VidGrab.zip`). Unzip anywhere and run — **no install required**.

> **Note:** ffmpeg is embedded, so there is no separate `ffmpeg` folder to ship. If you later place an `ffmpeg/` folder next to the exe, it overrides the embedded copy (useful for testing).

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
pytest -v                          # 14 tests, no network needed
```

What CI does on every push to `main` / pull request:

- **test** (ubuntu): installs ffmpeg + tkinter, runs the full pytest suite, and fails if any `.exe` binary is ever tracked by git
- **build-windows** (windows-latest): downloads the gyan ffmpeg essentials build, embeds it via `VidGrab.spec`, and produces the single-file exe + zip as a downloadable artifact

**Releases:** push a tag to ship a ready-to-download GitHub Release with `VidGrab.exe` + `VidGrab.zip`:

```bash
git tag v1.0.0
git push origin v1.0.0
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

1. Click **Local File** at the top of the Source card
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