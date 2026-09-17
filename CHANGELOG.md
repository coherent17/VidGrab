# Changelog

## 2.3.2

- **Full-resolution downloads**: info card and downloads now probe with the `tv_embedded` player client, so video info shows up to 2160p instead of capping at 360p (and 1080p MP4 is a direct mp4 download)
- **Likes / dislikes / comments**: the info card now shows those counts (dislikes best-effort from the Return YouTube Dislike dataset, skipped gracefully when unavailable)
- **Reliable trims**: trimming now always downloads the full video and cuts locally with ffmpeg — YouTube's ranged (section) downloads either got HTTP 403 or silently returned the full file, which saved untrimmed videos
- **Download fallback**: if the high-quality client's media URLs are rejected (403), the download retries with the low-res-but-reliable fallback client instead of failing
- **Packaged Linux fix**: the Linux binary had `multimedia=0` on clean runners because QtMultimedia links PulseAudio/ALSA/xcb — release and CI builds now install those libraries, and a new CI `integration` job exercises real YouTube downloads on every push
- **Bigger window** and a redesigned **LOG section** — a proper card, side-by-side Clear button, aligned with the other sections
- **Interactive finish**: the progress bar animates to a green 100% when a download or processing job completes (upload button shows the saved path)
- **Flag icons bundled**: all 12 language flags ship as bundled PNGs (no color-emoji font needed)

## 2.3.1

- **Fix — inline preview missing from packaged builds**: the Edit-page preview player is back in `VidGrab.exe` / `VidGrab-linux` — the PyInstaller spec excluded `PySide6.QtMultimedia`, so the release binary only offered the ffplay pop-out preview (source builds were unaffected). QtMultimedia is now bundled again, and a hidden `--selftest` flag lets CI verify `multimedia` availability in the packaged binary

## 2.3.0

- **Playlist & channel downloads**: paste any playlist/channel URL and download every video in the selected quality (MP4/MP3) with `01 - …` numbering and per-video progress
- **Video info card**: a preview card on the download page shows the title, uploader, duration and available resolutions (or video count for playlists) before you download
- **Auto-detect on paste**: pasting a YouTube link instantly probes the video and fills the info card (debounced ~700 ms while typing)
- **In-window media preview**: the Edit page now includes a preview card — an inline video/sound player with a seek timeline showing the current second, so you can read off the exact trim start/end times; dragging the scrubber jumps straight to that frame
- **Localization × 12**: the picker now includes Español, Français, Deutsch, Português, Italiano, Русский, Tiếng Việt and Indonesia (each shown with its flag), on top of English, 繁體中文, 日本語 and 한국어

## 2.2.0

- **New brand icon**: futuristic cyber-chip design — chamfered tile, electric blue→cyan→violet→magenta gradient, neon outline + glow, play triangle with download chevron, and the "VidGrab" wordmark (shown in README) — committed as assets (no runtime generation)
- **日本語 (Japanese) and 한국어 (Korean)**: full UI localization bringing the total to 4 languages; Noto Sans CJK JP/KR fonts bundled so both render on every OS
- **Repo polish**: dedicated long-running session notes moved to `docs/`, build scripts consolidated under `scripts/`, `version_info.txt` now derived from `vidgrab/_version.py`, single `requirements.txt`, dropped the redundant zip artifact
- **Makefile**: `setup`/`run`/`lint`/`test`/`build`/`clean`/`icon` targets replace `run.sh`

## 2.1.0

- **Qt rewrite**: entire GUI rebuilt on PySide6 (Qt 6) replacing CustomTkinter — sidebar + content-panel layout, QSS-styled dark/light themes, proper QStatusBar, professional typography hierarchy
- **Sidebar navigation**: Download / Edit / Settings pages switch via a left-hand sidebar with icon+label buttons and active accent border
- **QStatusBar**: connection status, ffmpeg source, and version displayed persistently at the bottom
- **QSS theming**: hand-crafted dark (deep navy) and light themes with consistent card styling, accent borders, and scrollbar theming
- **Settings page**: in-app theme combo, about info, version display
- **Keyboard shortcuts**: Ctrl+V (paste URL), Ctrl+L (clear log), F1 (about)
- **PyInstaller improvements**: unused Qt modules excluded to reduce bundle size; customtkinter/darkdetect removed

## 2.0.0

- **Modern GUI**: rebuilt on CustomTkinter — rounded cards, segmented controls, built-in dark/light theme toggle, tooltip hints, styled modal dialogs, high-DPI support
- **Internet-aware**: a live ● Online / ○ Offline pill shows connectivity in real time; the download button is disabled and a clean Retry/Exit dialog appears when the machine is offline
- **Single-pass MP4 + MP3**: selecting both formats now downloads the video once, then derives the MP3 locally — saves ~50 % bandwidth when both are requested
- **Faster re-encode**: flip-only uses ultrafast x264 (CRF 23) and copies audio streams unchanged
- **Trim-during-download**: when trimming a YouTube URL, only the wanted section is downloaded when possible; falls back to a full download automatically
- **Linux binary**: a self-contained x86_64 ELF is now published alongside the Windows exe — same zero-install story for Linux desktops
- **Project restructured**: code lives in a proper `vidgrab/` Python package (`__version__`, `__main__`)
- **23 tests** covering output locating, MP3 derivation, local processing, network probe (all mocked), and a GUI smoke test under Xvfb
- **CI/CD**: GitHub Actions runs lint (ruff), the full test suite including the headless GUI smoke test, builds both Windows and Linux single-file binaries, and publishes all artifacts on tag push
- CustomTkinter data files bundled correctly by PyInstaller; platform-aware ffmpeg folder layout (`ffmpeg/win/`, `ffmpeg/linux/`)

## 1.0.0

- Initial release — single-file Windows exe with embedded ffmpeg