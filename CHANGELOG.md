# Changelog

## 3.4.0

Offline AI captions that use your graphics card, plus a much bigger Studio: per-clip speed, animated and individually styled subtitles, multi-select, export presets and crash recovery.

### Auto captions and graphics cards

- **Auto captions**: "Auto captions…" in the Studio turns the speech in the clips into subtitle lines with Whisper, on this computer — nothing is uploaded. Pick the spoken language (or detect it; Chinese can be Traditional or Simplified) and the accuracy: **Fast**, **Balanced** or **Best** (large-v3 turbo). Lines follow the clips' trims, speed and place in the montage; muted clips are skipped. Lines break at sentences, pauses and commas, never inside a word; Chinese lines use spaces instead of commas, as subtitles usually do. Singing over music is still captioned, and Whisper's stock invented lines ("please subscribe…") are dropped. The Render button stops it while it runs; the result is one undo step
- **Graphics cards for auto captions** — three engines, each falling back to the next if it can't load or fails: **NVIDIA** (CUDA; VidGrab downloads the CUDA 12 cuBLAS / cuDNN libraries once, about 1.3 GB, from NVIDIA's pinned official wheels, so nothing has to be installed), **Intel** graphics (integrated or Arc, through OpenVINO: the *Best* model runs there in 5 s per minute of speech against 19 s on a fast CPU), and the **CPU**. Verified end to end on an Intel Arc 140T; the NVIDIA path is tested with real library downloads and fakes but not on an NVIDIA card
- **Captions are 5–7× faster on the CPU too**: the old setting used every core, and on laptop chips with performance and efficiency cores that made recognition several times *slower* (one minute of speech: 35 s → 9 s at Balanced). It now uses only the fast cores (read from Windows / Linux), capped at 8 threads
- **Render on the graphics card**: the video is encoded with NVIDIA NVENC, Intel Quick Sync or AMD AMF when one works (checked by a test encode), the picture quality is the same (SSIM 0.9973 against 0.9975 on a test clip), and a render that fails on the card is redone on the CPU. About 1.5× faster at Balanced and 1.8× at High on a fast laptop CPU, 3× on one with few cores; no gain at Fast
- **Settings → Hardware**: two switches (render on the graphics card, auto captions on the graphics card; on by default) with a status line saying what was found. **Settings → Storage** shows the downloaded speech models and deletes them
- **Models are downloaded on demand, not bundled**, to the local cache (`%LOCALAPPDATA%\VidGrab\models` on Windows, `~/.cache/vidgrab/models` on Linux — not the roaming profile): 85 / 260 / 830 MB for Intel graphics, 150 / 490 MB / 1.6 GB for NVIDIA and the CPU
- **Nothing hangs or crashes when hardware misbehaves**: the graphics-card check is time-limited (a stuck driver counts as "no card"); a render whose graphics encoder stops answering for two minutes is abandoned and redone on the CPU; each captions engine that fails (bad driver, out of memory, corrupt or missing model, no network) hands over to the next, ending on the CPU; a half-downloaded model or CUDA package leaves no partial files and a retry resumes after the last finished package; and quitting while a caption job or hardware check is stuck in a driver no longer aborts the app, nor does it refuse to quit. Basic integrated Intel graphics (under 64 execution units, e.g. UHD 620) are still used when the switch is on, but Settings and the captions dialog say they may be slower than the CPU, so the user decides
- OpenVINO's analytics (it posts to Google Analytics as soon as it is imported) are switched off, and the package isn't bundled; a test fails if anything touches the network on import

### Studio

- **Never lose an edit: autosave and crash recovery.** The Studio keeps a recovery copy of the project while you work; if VidGrab closes without saving (a crash, a power cut), it offers to restore it at the next start
- **Per-clip speed (0.25×–4×)**: in the Clip panel's Trim tab (0.5× / 1× / 1.5× / 2× or any value). The sound keeps its pitch, the timeline block shrinks or grows to match, transitions and subtitles line up with the sped-up clip, and the preview plays at that speed
- **Subtitle effects and per-line looks**: a new **Effects** tab per line with entry animations (**Pop**, **Slide up**, **Typewriter**, **Karaoke**) and **Give this line its own look** (its own text colour, background, size and bold); the shared style moved to an **All lines** tab. The preview draws the animations as they will render
- **Multi-select, copy and paste**: Ctrl+click or drag a box on the timeline to select several clips, subtitles and pictures; move them together, delete them, or copy (Ctrl+C) and paste them at the playhead (Ctrl+V), keeping their spacing. Ctrl+D duplicates, Ctrl+A selects everything
- **Guides**: a **Guides** button over the preview shows the centre lines and the 5 % safe area; dragged subtitles and pictures snap to them (Alt = free)
- **Export presets**: the Project panel picks what to make — **YouTube (1080p)**, **Shorts / Reels / TikTok** (vertical, with a reminder when the video is over 60 s), **Square (1:1)**, **Same as the clips**, **GIF** or **Audio only (MP3)** — with the matching resolution and file type
- The Clip panel is split into **Trim**, **Transition** and **Picture and sound** tabs, so it fits without scrolling
- The Studio toolbar buttons are shorter ("＋ Media…", "♪ Music…") so the row fits in a small window

### Downloads and releases

- **Downloads retry over IPv4 when the network is unreachable**: on networks (and CI runners) with IPv6 but no route for it, YouTube downloads and link previews failed with "Network is unreachable"; they now retry the same way over IPv4
- **Releases run the tests first**: the release workflow runs the same lint and test suite as CI (Linux and Windows) before building, so a tag can't publish untested code. The checks live in one shared workflow (`checks.yml`) used by both
- Fixed the trim integration test, which asked for 50 s–110 s of an 8 s video (a four-part time) and so never trimmed; it was hidden because YouTube's bot-check made CI skip it

## 3.3.0

- **Images over the video**: "＋ Image…" (or drop a picture on the window, or double-click the new **Images** row) shows a picture from the playhead for 4 s, placed by what it is: a cut-out with transparency (a logo, a sticker) small in the top-right corner, a photo as large as fits in the middle (several pictures follow one another). Drag its block in the Images row to change when it shows; in the preview drag the picture to move it, its corner to resize it and the knob above it to **rotate** it (snaps to 0 / 90 / 180 / 270°, Alt = free). The Image panel has start / end, size, opacity, fade in / out, rotation (± 90° buttons), a 3 × 3 position grid and "Fill the frame". Any number of pictures render in the same single ffmpeg pass, under the subtitles; undo and projects include them
- **The preview shows transitions**: crossfade, dissolve, wipe, slide, circle and zoom are now drawn live in the preview (paused or playing), not just labelled, and the sound crossfades as in the render. A second, hidden player decodes the other clip of a transition for the same preview window
- **Cut the background music**: the music block now has start / end handles to choose the part of the song that plays, and dragging the block makes the music come in later. When looping, that part repeats (dashed lines mark each pass) and the rest of the song shows faintly behind it. The music panel has exact **Song start**, **Song end** and **Comes in at** fields; undo and projects include them
- **Several background songs**: "＋ Add song…" puts another song on the Music row (right after the previous one); each song has its own part, start time, volume and fade in / out, and overlapping two songs with fades crossfades them. Only the last song loops to the end of the video; the original-audio level and the end fade apply to all music. Projects from 3.2 (one song) still open
- **Hear the music in the preview**: the play button now plays the background music with the video, as it will be rendered: the chosen part of the song, from its start time, looping, at the music volume, with the original audio turned down and the end fade
- **Overlapping subtitles (and pictures) stack into lanes**: lines that overlap in time sit one under another in the Subtitles row (which grows to fit) instead of covering each other, so each can be seen, selected and dragged
- **One pinned ffmpeg everywhere: 9.0.2.** The Windows and Linux executables used to bundle different, unpinned builds (the newest development build on Windows, a 7.x static release on Linux), so behaviour could differ between platforms and change between builds without any code change. Both now ship the same ffmpeg 9.0.2, pinned in `ffmpeg/pin.json` with SHA-256 checks; every CI job tests that exact binary, and `make ffmpeg` gives developers the same one
- Removed the Studio's **Import .srt / Export .srt** buttons (YouTube subtitles downloaded with a video still come along with "Send to Studio")
- Headless runs (tests, scripts) never play sound: the download-finished chime is skipped and the preview starts muted

## 3.2.0

- **Undo / redo** in the Studio (Ctrl+Z / Ctrl+Y, plus toolbar buttons) for every edit: adding, trimming, splitting, reordering and deleting clips; subtitle text, timing, position and style; background music and its settings. Typing and slider drags count as one step
- **Projects**: save the Studio timeline as a `.vgproj` file and open it later (Project menu, Ctrl+S / Ctrl+O / Ctrl+N, Open recent). Media paths are stored both absolute and relative to the project file, so a moved folder still opens; missing files are reported and left out. VidGrab asks before discarding unsaved changes, including when you close the window. Dropping a `.vgproj` on the window opens it
- **Timeline zoom**: Ctrl+wheel (or − / + / Fit) zooms around the mouse; Shift+wheel or the scrollbar pans; the view follows the playhead during playback
- **Snapping**: trim handles and subtitle blocks snap to the playhead, clip boundaries and other subtitles, with a guide line; hold Alt to drag freely
- **Keyboard editing**: Space / K play-pause, J / L ±1 s, ← / → one frame, Home / End, I / O trim the clip under the playhead, S split it; a **?** button lists every shortcut
- **Split clips** at the playhead (✂ Split or S); both halves keep their source times
- **Transitions between clips**: select a clip to open its new **Clip** panel and pick how it comes in: Cut, Crossfade, Dip to black / white, Dissolve, Wipe, Slide, Circle or Zoom in, with a duration (0.2–3 s) and **Use for all cuts**. The clips overlap on the timeline (marked ✕), the sound crossfades too, and the render uses ffmpeg `xfade`. The preview switches at the middle of a transition, draws dips to black / white, and labels the others while they play
- **Framing (crop and reframe)**: per clip, **Whole picture** (black bars) or **Fill frame** (crop, no bars), a zoom of 100–300 %, and **drag the picture in the preview** to choose what stays in view. Made for vertical 9:16 and square videos from landscape clips; the preview matches the render
- **Mute or turn down a clip**: a speaker button on every clip row in the timeline mutes it in one click (red when muted; also `M`), and the Clip panel has Mute plus a 0–200 % volume slider. The preview plays at that level and the render applies it (also in music medleys); saved in projects and undoable
- **Filmstrip thumbnails**: every tile on a video's timeline block shows the frame at its own time, extracted on demand in the background (zooming in fetches finer frames). Before, one frame was repeated across the block, so a video that fades in from black showed an all-black track, and a short part of a long video showed the same image over and over
- **Easier trimming**:
  - drag a start / end handle **past the edge** of the timeline and the clip keeps growing (faster the further out you hold it) while the view rescales, so a long clip can be lengthened in one drag instead of many small ones
  - hold **Shift** while dragging for 1/10-speed fine adjustment
  - the Clip panel has **exact Start / End** fields (hundredths) with **−1 s / −1 frame / +1 frame / +1 s** buttons (frame length from the video's own frame rate)
  - **Zoom to clip** (button or Z) zooms the timeline onto the selected clip
- **Clearer subtitle panel**: Line and Style tabs instead of one long scrolling panel; text and background colours are one-click swatches (with a custom colour picker), and the default position is a Bottom / Top switch
- **The mouse wheel no longer changes dropdowns, number boxes or sliders** anywhere in the app; it scrolls the panel instead
- Trims can no longer go past the end of the source (a clip could end up 0 s long)
- **Preview play button sometimes did nothing**: after jumping into a different clip, the player could report the previous file as loaded, so the jump was lost and the new file played from 0:00 while the playhead and time stayed still. The preview now waits for the new file, re-applies a jump the player drops, and when you jump twice while a file is still loading the newest jump wins
- Demo video re-recorded and the user guide updated for the new Clip panel (trim, transitions, sound, framing), undo, projects and keyboard shortcuts
- The clip count / length label under the preview now subtracts transition overlaps, so it matches the preview's total

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