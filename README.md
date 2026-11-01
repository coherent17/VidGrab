<div align="center">

<img src="docs/icon.png" alt="VidGrab" width="112">

# VidGrab

**Download videos. Edit them. Caption them with AI. All on your own computer.**

Turn a link into a finished video: grab it, cut it, add subtitles (typed, or **written for you from the speech**),
music and pictures, then export it for YouTube, Shorts, Reels or TikTok. Nothing is uploaded.

[![CI](https://github.com/coherent17/VidGrab/actions/workflows/ci.yml/badge.svg)](https://github.com/coherent17/VidGrab/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/coherent17/VidGrab?label=release&color=7c5cff)](https://github.com/coherent17/VidGrab/releases/latest)
![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-4c4c4c)
[![License: MIT](https://img.shields.io/badge/license-MIT-10b981)](LICENSE)

[**Download**](https://github.com/coherent17/VidGrab/releases/latest) ·
[Demo video](docs/VidGrab-demo.mp4) ·
[User guide (繁體中文)](docs/VidGrab-user-guide-zh-TW.pdf) ·
[Changelog](CHANGELOG.md)

<img src="docs/screenshots/studio.png" alt="VidGrab Studio: preview, inspector and a multi-track timeline" width="900">

</div>

---

## What you can do

- **Make a Shorts / Reels / TikTok clip** from a long video: trim the best part, pick the vertical format, click **Auto captions**, render.
- **Subtitle any talk or interview** in about 100 spoken languages, fix a word or two, then burn the subtitles in or keep them as text.
- **Put two videos side by side** (or stacked, or picture-in-picture) in one frame.
- **Join clips into a montage or music video** with transitions, per-clip speed, background music and logos.
- **Download** videos, playlists and music from YouTube and many other sites, as MP4 or MP3 / M4A / Opus / FLAC / WAV.

English and 繁體中文, dark and light themes.

## Install

| Platform | Get it | Run it |
|----------|--------|--------|
| Windows 10 / 11 | `VidGrab-windows-x64.exe` | Double-click |
| macOS 12+ (Apple silicon or Intel) | `VidGrab-macos-arm64.zip` / `VidGrab-macos-x64.zip` | Unzip, then right-click `VidGrab.app` → **Open** the first time |
| Linux (x64) | `VidGrab-linux-x64` | `chmod +x VidGrab-linux-x64 && ./VidGrab-linux-x64` |

Download from the [latest release](https://github.com/coherent17/VidGrab/releases/latest). On a Mac the app is not signed, so macOS asks you to confirm the first launch, and VidGrab offers to download ffmpeg once.

**Or with pip** (Python 3.10+, any system):

```bash
pipx install vidgrab-studio                # for auto captions use "vidgrab-studio[captions]"
vidgrab                                    # start it; "vidgrab --info" shows what is installed
```

To start it from your own script:

```python
from vidgrab.app import main

main()
```

## Quick start

1. **Download:** copy a video link, click **Paste**, then **Download**. You can also type words to search YouTube.
2. **Send to Studio:** click **Send to Studio** next to the finished download.
3. **Edit:** drag a clip's edges to trim it, add **＋ Subtitle** lines or click **Auto captions…**, add **♪ Music**.
4. **Render:** choose an export preset and click **Render**.

The [user guide](docs/VidGrab-user-guide-zh-TW.pdf) (繁體中文) shows every page, and the [demo video](docs/VidGrab-demo.mp4) walks through the whole flow.

## Good to know

- **Auto captions** run on your computer with Whisper: no account, no upload. The speech model (85 MB to 1.6 GB) is downloaded once, the first time you use it. It uses an Intel or NVIDIA graphics card when there is one ([speed numbers](docs/performance.md)).
- **Rendering** can use your graphics card (Intel, NVIDIA, AMD, Apple) and falls back to the CPU on its own. See **Settings → Hardware**.
- **Settings** has three tabs: General, Downloads (defaults, speed limit, proxy, updating the download engine) and Studio.
- **Privacy:** VidGrab only connects to download what you ask for (the video site, and the speech model the first time you use captions). Your projects and captions never leave your computer.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Video unavailable" or a download error | Sites change often. Update the download engine in **Settings → Downloads**, or update VidGrab (pip: `pip install -U yt-dlp`) |
| Downloaded at only 360p | The site refused the high-quality stream. Try again later |
| Auto captions are slow | Pick **Fast** or **Balanced**, and keep **Settings → Hardware → auto captions on the graphics card** on |
| Can't type Chinese on Linux / WSL | Paste the text instead, or install ibus: `sudo apt install ibus ibus-chewing` |
| Antivirus warning | Common with this kind of app: add an exception |
| Won't start on Linux | Needs a desktop session and Qt's libraries: `sudo apt install libegl1 libxkbcommon0 libxcb-cursor0` |

Something else? [Open an issue](https://github.com/coherent17/VidGrab/issues).

## For developers

Building from source, tests and releases: [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). Built with [yt-dlp](https://github.com/yt-dlp/yt-dlp), [FFmpeg](https://ffmpeg.org), [PySide6 (Qt)](https://doc.qt.io/qtforpython/), [Whisper](https://github.com/openai/whisper) and [Noto Sans CJK](https://github.com/notofonts/noto-cjk). Only download content you have the right to use.
