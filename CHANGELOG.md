# Changelog

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