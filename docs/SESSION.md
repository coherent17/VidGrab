# Session Notes — VidGrab

## Environment
- WSL2 Linux + Windows Python 3.14.6; Windows venv `.venv/Scripts/` has pyinstaller.exe + yt-dlp.exe; Linux venv `.venv/bin/` has yt_dlp 2026.07.04.
- Build: copy `.py` + spec + assets to a Windows temp dir, then run PowerShell with the UNC pyinstaller path (see build command below).

## Build command (confirmed working)
```
# Replace <Distro> and <you> with your WSL distro name and Linux username
powershell.exe -NoProfile -Command "
Set-Location '<WindowsTempDir>';
$pyinstaller = [System.IO.Path]::Combine('\\\\wsl.localhost','<Distro>','home','<you>','VidGrab','.venv','Scripts','pyinstaller.exe');
& $pyinstaller 'VidGrab.spec' --noconfirm"
```

## Key facts
- yt-dlp 2026.07.04 needs `player_client=android` via extractor_args to avoid YouTube 403. `format_sort: ["proto:https"]`.
- ffmpeg lives at `ffmpeg/` in the repo root (ffmpeg.exe + ffprobe.exe, gyan build). Embedded into the exe by the spec at build time.
- Flip (h/v) works — always done via local ffmpeg `_trim()` with `.proctmp` suffix. MP3 always uses `.mp3tmp` suffix so audio extraction never overwrites an existing `.mp4` with the same title.

## New in build 2026-09-16 22:36 (app icon)
- **Window icon fixed**: `app.py::_set_window_icon()` now calls `iconbitmap()` (Windows) / `iconphoto()` (Linux) with the bundled icon instead of showing tkinter's default feather. Spec bundles `assets/icon.ico` + `assets/icon.png` as datas so they're available from `sys._MEIPASS/assets/`.
- **New icon design**: `scripts/generate_icon.py` rewritten — accent-blue rounded square (#4f7cff), white play triangle, plus a small white download arrow at sizes ≥ 64 px. Uses 4× supersampling box-filter for anti-aliasing. Emits `icon.ico` (16/32/48/64/128/256) and `icon.png` (256).
- Exe resource icon unchanged mechanism (spec `icon=`), now points at the new design.
- NOTE: don't leave VidGrab.exe running during a rebuild — the onefile bootloader child process locks dist\VidGrab.exe (caused I/O error on rm). Kill via `Get-Process VidGrab | Stop-Process -Force`.

## New in build 2026-09-16 22:21 (self-contained single exe)
- **ffmpeg embedded**: `VidGrab.spec` now bundles `ffmpeg/ffmpeg.exe` + `ffmpeg/ffprobe.exe` as datas (dest `ffmpeg`) into the onefile exe. PyInstaller extracts them to `sys._MEIPASS/ffmpeg/` at launch. The gyan **essentials** build is static (only system DLLs), so no extra DLLs are needed.
- `find_ffmpeg()` already checks `_MEIPASS/ffmpeg/ffmpeg.exe` last; an `ffmpeg/` folder placed next to the exe still overrides it (good for swaps/testing).
- Footers now show `ffmpeg: embedded (bundled in this app)` instead of the temp `_MEI...` path.
- **Deliverable is now a single exe** (~94 MB) or `VidGrab.zip` (~93 MB). NO separate `ffmpeg/` folder needed. Build scripts (`build.ps1`/`build.bat`) no longer assemble a portable folder.
- Spec embeds ffmpeg only if `ffmpeg/ffmpeg.exe` exists next to the SPEC at build time. Place ffmpeg.exe + ffprobe.exe in `ffmpeg/` in the repo root (or next to the spec in the build dir) before running PyInstaller.

## New in build 2026-09-16 21:59
- **Local file mode**: Source card now has a "YouTube URL" / "Local File" toggle. In Local File mode the user picks an mp4/mp3/mkv/etc., the Format card is hidden, and the Download button becomes "Process". `downloader.process_local_file()` applies trim + flip via local ffmpeg (or copies when neither is set) to `{name}_processed.{ext}` in the Save-to folder.
- **Checkbox colors**: MP4 checkbox is now green (SUCCESS `#3ecf8e`), MP3 checkbox is now orange (new ORANGE `#f0a050`) so the two formats are visually distinct.

## FIXED in latest build (2026-09-15 01:18)
1. **`_locate_output` double-dot glob bug**: old no-suffix branch built patterns like `f"*.{ext}"` with `ext=".mp3"` → `*..mp3` (two dots), never matched. Now `[f"*{ext}"]`.
2. **MP3 clobbering MP4**: when both MP4+MP3 selected, `bestaudio/best` could fall back to a combined `.mp4`; `FFmpegExtractAudio` then deleted that `.mp4` (a previously saved file) while producing `.mp3`. Now MP3 downloads to `%.tmp3tmp` and is renamed after. Non-ffmpeg path strips tmp suffixes; guard added for out_file == final_file (no-rename case).

## Verified
- single mp4 -> `OK`, single mp3 -> `OK`, mp3 -> after-mp4 both files coexist; trim keeps working. Test URL: `https://www.youtube.com/watch?v=LCyB5Zm3LWU` (fully downloads both formats to /tmp/flip-test/out*).

## Deliverables
- `dist/VidGrab.exe` (single self-contained exe), `dist/VidGrab.zip` (~93 MB).

## TO TEST on Windows (manual)
- Both checkboxes MP4+MP3 on the same video -> expect 2 files, mp4 intact.
- Plain MP3 (no trim/flip) -> file found, no "output file was not found" error.
- Trim + flip still correct.