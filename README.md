<div align="center">

<img src="docs/icon.png" alt="VidGrab" width="112">

# VidGrab

**Download from YouTube. Edit in the Studio. Caption it with AI. All on your own computer.**

Turn a link into a finished video: grab it, cut it, add subtitles (typed, or **written for you from the speech**),
music and pictures, and export it for YouTube, Shorts, Reels or TikTok. One portable app, nothing to install,
nothing uploaded.

[![CI](https://github.com/coherent17/VidGrab/actions/workflows/ci.yml/badge.svg)](https://github.com/coherent17/VidGrab/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/coherent17/VidGrab?label=release&color=7c5cff)](https://github.com/coherent17/VidGrab/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/coherent17/VidGrab/total?color=22d3ee)](https://github.com/coherent17/VidGrab/releases)
![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-4c4c4c)
[![License: MIT](https://img.shields.io/badge/license-MIT-10b981)](LICENSE)

[**Download**](https://github.com/coherent17/VidGrab/releases/latest) ·
[Demo video](docs/VidGrab-demo.mp4) ·
[User guide (繁體中文)](docs/VidGrab-user-guide-zh-TW.pdf) ·
[Changelog](CHANGELOG.md)

<img src="docs/screenshots/studio.png" alt="VidGrab Studio: preview, inspector and a multi-track timeline" width="900">

</div>

---

## Why VidGrab

| | |
|---|---|
| **One app, the whole job** | Download, trim, join, caption, add music and export, without bouncing between a downloader, an editor and a subtitle tool. |
| **AI captions that never leave your PC** | Whisper runs locally: no account, no upload, no per-minute fee. It uses your graphics card when it can. |
| **Fast on the hardware you have** | Intel, NVIDIA and AMD graphics speed up rendering; captions run on Intel and NVIDIA GPUs, and on a CPU that is tuned instead of brute-forced. |
| **Looks right the first time** | The preview is drawn exactly like the render: subtitles, animations, transitions, framing and pictures. |
| **Portable** | A single file for Windows or Linux, ffmpeg built in, English and 繁體中文, dark and light themes. |

### What you can make in a few minutes

- **A Shorts / Reels / TikTok clip from a long video.** Download it, trim the best 40 seconds, pick *Shorts / Reels / TikTok* (vertical 9:16, drag the picture to choose what stays in frame), click **Auto captions**, give the lines a *karaoke* or *typewriter* animation and render.
- **A subtitled version of any talk or interview.** Auto captions in the spoken language (about 100 are supported, including Traditional and Simplified Chinese), fix a word or two, burn them in or keep them as text.
- **A highlight montage or music video.** Join clips with crossfades and wipes, change a clip's speed, lay several songs under it, drop a logo on top.
- **A music medley** from songs or parts of songs, with crossfades, as MP3, M4A or WAV.
- **A GIF** of a moment, or the **audio only** of a video.

## Download

| Platform | File | How to run |
|----------|------|------------|
| Windows 10 / 11 (x64) | `VidGrab-windows-x64.exe` | Double-click |
| Linux x64 (glibc ≥ 2.35) | `VidGrab-linux-x64` (or `.tar.xz`) | `chmod +x VidGrab-linux-x64 && ./VidGrab-linux-x64` |

Grab them from the [latest release](https://github.com/coherent17/VidGrab/releases/latest), which also includes
the demo video, the user guide and `SHA256SUMS.txt` for verifying downloads.

**Quick start:** copy a YouTube link → **Paste** → **Download** → **Send to Studio** → trim, add **＋ Subtitle** or
**Auto captions…** → **Render**.

## Features

### ⬇ Download

- **MP4, MP3 or both** in one pass. Pick the quality from 4K down to 360p (MP3 at 128–320 kbps); at any resolution H.264 is preferred so files play everywhere
- **Several links at once** with a per-link preview (thumbnail, title, length, playlist size); remove any link before you start
- **Download queue** that runs one item at a time, with progress, speed, ETA, **Cancel** and **Retry**
- **Recent downloads** that stay between sessions; **Send to Studio** puts a file (and its subtitles) straight onto the timeline
- **Playlists and channels**: every video, numbered in order
- **YouTube subtitles** in 繁體中文, 简体中文, English or 日本語 (uploaded or auto-generated), saved as `.srt` or burned in. Timings follow any trim or speed change
- **Trim, flip and speed (0.25×–4×)** applied while downloading

### 🎬 Studio

- **Video montage**: join videos of any size or orientation into one MP4 (match the first clip, 1080p / 720p / 480p, vertical 9:16 or square). Clips without sound get silence
- **Music medley**: join songs or parts of songs into MP3 / M4A / WAV, with a crossfade between tracks
- **Multi-track timeline**: one row per clip, with thumbnails or waveforms. Drag the left and right handles to trim, drag a clip up or down to reorder, and click to seek. Zoom with Ctrl+wheel; handles and subtitles snap to the playhead and to each other
- **Edit like an editor**: undo / redo, split at the playhead, keyboard trimming (I / O) and playback (J / K / L, frame steps), multi-select (Ctrl+click or a box) with copy / paste, and **per-clip speed** (0.25×–4×, pitch kept)
- **Projects**: save the timeline as a `.vgproj` file and pick up where you left off (Open recent); an autosaved recovery copy brings back unsaved work after a crash
- **Two videos at once**: **Two videos…** plays two clips side by side, stacked, big + small or picture-in-picture in one frame (16:9, vertical or square), with a preview, a gap, and a choice of sound; the result joins the timeline as one clip
- **Transitions** between clips (crossfade, dip to black / white, wipe, slide, circle, zoom…) shown live in the preview, and **framing**: fill a vertical or square frame from a landscape clip, zoom in, and drag to choose what stays in view
- **Subtitles**: add a line at the playhead, drag it in the preview or snap it with the position grid, retime it by dragging its block, split or duplicate lines. Font, bold, colour, background box with opacity, fade in / out and reusable **style presets**. Overlapping lines stack into lanes
- **Subtitle effects**: any line can have **its own look** and an animation: *pop*, *slide up*, *typewriter* or *karaoke*. **Guides** show the centre and the safe area, and dragged text and pictures snap to them
- **Background music**: several songs, each cut with handles and set to come in when you want; separate music and original-audio volume, looping, fades. The preview plays it in sync with the video
- **Per-clip sound**: mute any clip from its row, or set its volume (0–200 %)
- **Images**: put logos, stickers or photos over the video for any time range; move, resize and rotate them right in the preview
- **Export presets**: YouTube 1080p, Shorts / Reels / TikTok, square, same as the clips, GIF or audio only. One-pass render with a live progress bar and Fast / Balanced / High quality

### 🤖 Auto captions

Click **Auto captions…** in the Studio and the speech in your clips becomes subtitle lines on the timeline, placed with
the clips' trims and speed, ready to edit, style and animate.

- **Private and offline.** Recognition runs on your computer with [Whisper](https://github.com/openai/whisper). Nothing is uploaded, and there is no account or limit
- **Your language.** Pick the spoken language or let it detect it (about 100 languages); Chinese comes out as Traditional or Simplified, as you choose
- **Three accuracy levels:** Fast, Balanced and Best (Whisper large-v3 turbo, far better with accents, names and mixed languages)
- **Readable lines.** Lines end at sentences, pauses and commas, never inside a word; Chinese lines use spaces instead of commas, as subtitles do. Singing over music is still captioned, and Whisper's invented "please subscribe…" lines are dropped
- **On demand, not bundled.** The app stays a single file; the speech model downloads once, the first time you use it, with a progress bar (sizes below), and **Settings → Storage** shows its size and deletes it

| Accuracy | Download on an Intel GPU | Download on an NVIDIA GPU or the CPU |
|---|---|---|
| Fast | 85 MB | 150 MB |
| Balanced | 260 MB | 490 MB |
| Best | 830 MB | 1.6 GB |

An NVIDIA card also needs NVIDIA's CUDA libraries (a 1.3 GB download, 2 GB on disk), which VidGrab fetches once from
NVIDIA's official packages if they aren't installed, so you never have to set up CUDA yourself.

### ⚡ Hardware acceleration

Two switches in **Settings → Hardware** (on by default, with an automatic fall back to the CPU whenever a card can't do
the job). Measured on a laptop with a Core Ultra 9 285H and its integrated Intel Arc 140T GPU:

**Auto captions**, one minute of Mandarin speech:

| Accuracy | Before | CPU, tuned | Intel GPU |
|---|---:|---:|---:|
| Fast | 18.1 s | 3.7 s | 2.6 s |
| Balanced | 35.4 s | 8.9 s | 4.9 s |
| **Best** | 27.1 s | 19.0 s | **5.1 s** |

The GPU runs the most accurate model faster than the middle one on the CPU, so a one-hour video takes about five minutes
at *Best*. Even without a graphics card, captions are 5–7× faster than before: on laptop chips with performance and
efficiency cores, VidGrab now uses only the fast cores (using all of them was several times slower).

**Rendering** a 215 s clip to 1080p with the video encoded on the graphics card (Intel Quick Sync, NVIDIA NVENC or AMD AMF):

| Quality | CPU | GPU | With the CPU limited to 4 threads |
|---|---:|---:|---:|
| Fast | 14.9 s | 14.1 s | |
| Balanced | 26.3 s | **18.0 s** | 56 s → **20 s** |
| High | 41.5 s | **22.9 s** | 97 s → **28 s** |

The picture is just as good (SSIM 0.9973 against 0.9975 for the CPU encode at the same file size). Scaling, subtitles and
transitions still run on the CPU, so the gain is biggest at *High* quality and on laptops with fewer cores.

> Tested on that Intel laptop. The NVIDIA and AMD paths are in the app but couldn't be tried on real NVIDIA / AMD
> hardware yet: they check the card first and fall back to the CPU if anything fails. Please
> [open an issue](https://github.com/coherent17/VidGrab/issues) if one misbehaves for you.

### ⚙ Settings

- **Download defaults**: save folder, format, quality, subtitles and a file-name pattern (title, title + ID, channel – title, date + title), plus a sound and message when the queue finishes
- **Studio defaults**: render quality, output resolution and subtitle style presets
- **Hardware**: use the graphics card for rendering and for auto captions, with what was found on your computer
- **Storage tools**: clear the thumbnail cache or download history, delete the downloaded speech models, export the log, reset all settings. The About section shows the yt-dlp, ffmpeg and Qt versions

### 🔒 Privacy

VidGrab talks to the network only to download what you ask for: YouTube (through yt-dlp), and, the first time you use
auto captions, the speech model from Hugging Face (plus NVIDIA's CUDA libraries from PyPI on an NVIDIA card). Captions,
projects and media never leave your computer, and the analytics built into the speech libraries are switched off.

## Screenshots

| Download page | Settings |
|:---:|:---:|
| <img src="docs/screenshots/download.png" alt="Download page with link previews and the download list" width="440"> | <img src="docs/screenshots/settings.png" alt="Settings page" width="440"> |
| **Studio, light theme** | |
| <img src="docs/screenshots/studio_light.png" alt="Studio in the light theme" width="440"> | |

## Using VidGrab

1. **Download**: copy one or more YouTube links and click **Paste**. Check the previews, choose the format and quality, then click **Download**.
2. **Send to Studio**: in the download list, click **Send to Studio** on a finished video (or use **＋ Media** in the Studio).
3. **Edit**: drag each clip's handles to trim it. Add **♪ Music** and **＋ Subtitle** lines, or let **Auto captions…** write them, then style and position them.
4. **Render**: choose the export preset and file name, then click **Render**.

The **[user guide](docs/VidGrab-user-guide-zh-TW.pdf)** (繁體中文) walks through every page with screenshots, and the
**[demo video](docs/VidGrab-demo.mp4)** shows the whole flow with narration.

Keyboard shortcuts: `Ctrl+V` pastes a link and `F1` shows About. In the Studio:

| Keys | Action |
|------|--------|
| `Space` / `K` | Play / pause |
| `J` / `L` · `←` / `→` | Back / forward 1 second · one frame |
| `I` / `O` | Trim the clip under the playhead to start / end there |
| `S` | Split the clip under the playhead |
| `M` | Mute / unmute the selected clip |
| `Delete` | Delete the selected clip or subtitle |
| `Ctrl+click` / drag a box | Select several items |
| `Ctrl+C` / `Ctrl+V` / `Ctrl+D` | Copy / paste at the playhead / duplicate |
| `Ctrl+A` | Select everything |
| `Ctrl+Z` / `Ctrl+Y` | Undo / redo |
| `Ctrl+wheel` · `Ctrl+0` | Zoom the timeline · fit the whole project |
| `Z` | Zoom to the selected clip |
| `Ctrl+S` / `Ctrl+O` / `Ctrl+N` | Save / open / new project |

Hold `Alt` while dragging to turn snapping off, or `Shift` for fine (1/10-speed) trimming; drag a handle past the edge of the timeline to keep extending the clip. The **?** button in the timeline lists every shortcut.

### Typing Chinese on Linux / WSL

The Windows build uses the Windows input method directly. Under WSL, Linux apps can't receive input from the Windows input
method, so either paste the text (Ctrl+V or the **Paste** button) or install ibus. VidGrab uses ibus automatically when
it's installed:

```bash
sudo apt install ibus ibus-chewing   # or ibus-libpinyin for pinyin
ibus-daemon -drx                     # add to ~/.profile to start it automatically
```

## Building from source

Requires Python 3.10+.

```bash
make setup    # create .venv and install dependencies (one-time)
make ffmpeg   # download the pinned ffmpeg 9.0.2 into ffmpeg/linux (one-time)
make run      # launch the app
make lint     # ruff
make test     # pytest, including a headless GUI smoke test
make build    # standalone binary for the current OS -> dist/
```

On Windows, use `python -m venv .venv`, `.venv\Scripts\activate`, `pip install -r requirements.txt` and
`python -m vidgrab`, or build with `scripts\build.ps1` (which fetches the pinned ffmpeg itself).

Every build, CI job and development setup uses the one ffmpeg version pinned in `ffmpeg/pin.json`
(SHA-256 checked); see `ffmpeg/README.txt` to upgrade it.

> Missing Qt libraries on Linux? `sudo apt install -y libegl1 libgl1 libxkbcommon0 libfontconfig1 libxcb-cursor0 libxcb-xinerama0 libdbus-1-3`

<details>
<summary><b>Project layout</b></summary>

```
vidgrab/
  app.py              main window, Download and Settings pages, download queue
  studio_page.py      Studio workspace and multi-track timeline
  preview.py          in-window preview player with draggable subtitles
  studio.py           ffmpeg engine: joining, subtitles (ASS), music, thumbnails and waveforms
  captions.py         auto captions: Whisper engines (NVIDIA, Intel GPU, CPU), model download, line breaking
  gpu.py              GPU video encoder detection and CPU thread tuning
  cuda_runtime.py     on-demand download of NVIDIA's CUDA libraries
  downloader.py       yt-dlp downloads, subtitles, trim / flip / speed
  jobs.py             one queued download (media + subtitles)
  downloads_panel.py  download list rows and history
  i18n.py             English / 繁體中文 strings
assets/               icon, flags, bundled Noto Sans CJK TC font
docs/                 demo video, user guide, screenshots
tests/                pytest suite (unit, GUI smoke, real-ffmpeg renders)
VidGrab.spec          PyInstaller spec (bundles ffmpeg, Qt, Whisper and OpenVINO)
```

</details>

<details>
<summary><b>CI and releases</b></summary>

Every push and pull request is linted and tested on Linux and Windows, and both standalone binaries are built. Each
build also renders real Studio projects with the exact ffmpeg it bundles, and checks that the speech engines load and
run inside the packaged binary.

To release, bump `vidgrab/_version.py`, add a `## <version>` section to `CHANGELOG.md`, and push a matching tag
(`git tag vX.Y.Z && git push origin vX.Y.Z`). The release workflow checks the tag against the version, builds both
platforms and publishes the executables, the demo video, the user guide and `SHA256SUMS.txt`, with notes taken from
the changelog.

</details>

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Video unavailable" / HTTP 403 | YouTube changes often; update to the latest VidGrab release |
| Video downloaded at only 360p | YouTube refused the high-quality stream, so VidGrab fell back to a reliable low-resolution one. Try again later |
| Antivirus warning | Common with PyInstaller apps; add an exception |
| Auto captions are slow | Turn on **Settings → Hardware → Make auto captions on the graphics card**, or pick **Fast** / **Balanced**. Intel graphics need an up-to-date graphics driver (on Linux also `intel-opencl-icd`) |
| Auto captions use the CPU although I have a graphics card | **Settings → Hardware** says what was found. AMD cards can't be used for captions (they can for rendering); NVIDIA needs a recent driver |
| Can't type Chinese | See [Typing Chinese on Linux / WSL](#typing-chinese-on-linux--wsl), or paste the text |
| Studio preview shows no picture | The packaged app includes QtMultimedia; from source, make sure PySide6 includes it |

## License

[MIT](LICENSE). Built with [yt-dlp](https://github.com/yt-dlp/yt-dlp), [FFmpeg](https://ffmpeg.org),
[PySide6 (Qt)](https://doc.qt.io/qtforpython/), [Whisper](https://github.com/openai/whisper) through
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) and [OpenVINO](https://github.com/openvinotoolkit/openvino),
and [Noto Sans CJK](https://github.com/notofonts/noto-cjk).

Only download content you have the right to use.
