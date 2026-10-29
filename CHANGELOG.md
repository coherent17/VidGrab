# Changelog

## 3.1.0

- **Settings page** in two columns with five sections:
  - **Download defaults**: save folder, format, video / audio quality, subtitles (language, save or burn), a file-name pattern (title, title + video ID, channel – title, upload date + title), and a sound plus message when the download queue finishes
  - **Studio**: render quality (Fast / Balanced / High quality), default output resolution, and saved subtitle style presets
  - **Storage**: thumbnail cache size and clear, clear download history, export the log file, reset all settings
  - **About**: VidGrab, yt-dlp, ffmpeg, Qt and Python versions
- **Subtitle style presets**: save the current font, size, colours, background, fade and position from the Studio's subtitle panel and apply them in one click
- The theme choice is now translated, and the About text describes the current features
- User guide: fixed list bullets that showed as boxes and added the Settings page; demo video re-recorded with presets and Settings; README rewritten


## 3.0.0

- **Studio (new)** — an editor-style workspace that replaces the Edit page. It fits the window with no scrolling:
  - **Layout**: a large preview on top that plays the finished result (play / pause), an **Inspector** beside it (project, subtitle or music settings), and a **timeline** below in which **every clip has its own row**, plus Subtitles and Music rows. Thumbnails show for video and waveforms for audio
  - **Trimming with two handles**: drag a clip's left handle to choose where it starts and its right handle to choose where it ends. The preview shows the frame under the handle, and the faint area shows the rest of the source. Drag a clip up or down to reorder it
  - **Music medley**: join different songs, or sections of songs, into one MP3 / M4A / WAV with an optional crossfade
  - **Video montage**: join different videos into one MP4. Clips of any size or orientation are fitted to one frame (match the first clip, 1080p / 720p / 480p, vertical 9:16 or square), and clips without sound get silence
  - **Subtitles**: add a line at the playhead, then **drag it in the viewer to position it**. Drag or resize its block on the timeline to retime it. Import / export `.srt`, and set size and colour. Burned in as ASS so the render matches the preview; Chinese renders with the bundled Noto Sans CJK TC
  - **Subtitle colours**: pick the text colour and a background box (none / transparent, black, dark gray, white, yellow, or any custom colour) with adjustable opacity. The preview shows exactly what gets rendered
  - **Subtitle tools**: a 3×3 quick-position grid (alongside dragging), split a line at the playhead, duplicate a line, font choice (bundled CJK font or any installed font, which is handed to ffmpeg so the render matches), bold, and fade in / out
  - **Background music**: mix a song under the montage with separate music / original-audio volume, looping and an end fade-out
  - Drop files anywhere in the window to add them. Rendering shows real progress
- **Edit page removed**: trimming now lives in the Studio. Flip / speed remain on the Download page. The ffplay-based preview and the bundled `ffplay` binary are gone
- **Download queue + recent downloads (replaces the log)**: paste several links at once; each download gets a row with thumbnail, progress, speed and ETA, and **Cancel / Retry**. Finished downloads are remembered across restarts with **Send to Studio** (adds the file, and its subtitles, to the Studio timeline). Technical details now go to `vidgrab.log` in the config folder instead of the window
- **MP4 downloads prefer H.264**: at the chosen resolution VidGrab now picks H.264 over AV1. YouTube often serves AV1 in MP4, which many players (and the Studio preview) can't decode. 1440p / 4K, which exist only as VP9 / AV1, are still downloaded at full resolution
- **Connection status keeps updating**: the online check used to run once at startup, so starting offline left Download disabled until a restart. It now re-checks every 5 s while offline and every 30 s while online
- **Several links at once**: pasting a list of links (Ctrl+V or Paste) shows each one in the Video Info card with its thumbnail, title and length (or video count for playlists, with a per-playlist "Download whole playlist" box). Drop any link with ✕ before pressing Download
- **YouTube subtitles**: optionally download a video's captions (Traditional / Simplified Chinese, English, Japanese; uploaded or auto-generated) as `.srt`, or burn them into the video. Timings follow the trim / speed settings
- **Download page redesigned**: a link bar with Paste and a large Download button, the video card beside a compact options card, and progress + log below. Nothing scrolls
- **Navigation rail**: the 212 px sidebar became an 84 px icon rail
- **Chinese subtitle text**: a Paste button next to the subtitle text (WSL can't pass the Windows IME to Linux apps). ibus is enabled automatically when installed
- **Redesigned UI**: violet→cyan theme, page headers, rounded cards with accent bars, pill navigation, drawn chevrons and icons (no emoji-font dependency), all generated from one stylesheet template shared by dark and light
- **Languages**: the UI now ships in **English and 繁體中文** only (the other 10 languages, their flags and the JP/KR fonts were removed; a saved language that no longer exists falls back to English)
- **Release / CI**:
  - release assets are now `VidGrab-windows-x64.exe`, `VidGrab-linux-x64` (+ `.tar.xz`), the demo video, the zh-TW user guide PDF and `SHA256SUMS.txt`, with notes taken from this changelog
  - the release fails if the tag doesn't match `vidgrab/_version.py`
  - the Linux binary is built on Ubuntu 22.04, so it runs on older distros
  - CI also runs the tests on Windows
  - each build renders Studio projects with the exact ffmpeg it bundles

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