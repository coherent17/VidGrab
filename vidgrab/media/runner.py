"""Running ffmpeg with live progress."""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

from vidgrab.core.downloader import (
    LogCallback,
    ProgressCallback,
    TranslateFn,
    _noop_tr,
    find_ffmpeg,
)
from vidgrab.media.model import SAMPLE_RATE, _ResolvedClip
from vidgrab.media.probe import _no_window, _to_float

# ── ffmpeg runner with live progress ──────────────────────────────────────


def _run_with_progress(
    cmd: list[str],
    total: float,
    *,
    cwd: Path | None = None,
    label: str,
    on_progress: ProgressCallback | None,
    on_log: LogCallback | None,
    translate: TranslateFn | None,
    stall_s: float | None = None,
) -> None:
    """Run ffmpeg, mapping its ``-progress`` output onto a 0..100 percentage.
    With *stall_s*, ffmpeg is killed (and RuntimeError raised) if it prints no
    progress for that long, so a graphics driver that stops answering can't
    hang the render."""
    tr = translate or _noop_tr
    if on_log:
        on_log(" ".join(cmd))
    full = [cmd[0], "-hide_banner", "-nostats", "-progress", "pipe:1", *cmd[1:]]
    proc = subprocess.Popen(
        full,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_no_window(),
    )
    err_tail: list[str] = []
    err_first: list[str] = []  # the first error lines usually name the cause

    def drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            err_tail.append(line.rstrip())
            del err_tail[:-12]
            low = line.lower()
            if len(err_first) < 6 and any(k in low for k in (
                    "error", "invalid", "not match", "mismatch", "failed", "cannot",
                    "unable", "no such")):
                err_first.append(line.rstrip())

    t = threading.Thread(target=drain, daemon=True)
    t.start()
    last_seen = [time.monotonic()]
    stalled = threading.Event()

    def watch() -> None:
        while proc.poll() is None:
            time.sleep(1.0)
            if stall_s and time.monotonic() - last_seen[0] > stall_s:
                stalled.set()
                proc.kill()
                return

    if stall_s:
        threading.Thread(target=watch, daemon=True).start()
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            last_seen[0] = time.monotonic()
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and total > 0 and on_progress:
                secs = (_to_float(value) or 0) / 1_000_000
                on_progress(label, max(0.0, min(99.0, secs / total * 100)))
    except BaseException:
        # the callback raised (e.g. the user cancelled): don't leave ffmpeg running
        proc.kill()
        proc.wait()
        raise
    proc.wait()
    t.join(timeout=2)
    if stalled.is_set():
        raise RuntimeError(tr("ffmpeg stopped responding (no progress for {s} s).", s=round(stall_s or 0)))
    if proc.returncode != 0:
        if on_log:
            for line in err_tail[-6:]:
                on_log(line)
        # ffmpeg's own last words say *why* (shown in the error dialog too)
        lines = err_first + [x for x in err_tail[-6:] if x not in err_first]
        detail = "\n".join(line for line in lines if line.strip())
        raise RuntimeError(
            tr("ffmpeg failed to render the project (exit code {code}).", code=proc.returncode)
            + (f"\n\n{detail}" if detail else "")
        )


def unique_path(path: Path) -> Path:
    """*path*, or *path* with ' (2)', ' (3)', … appended if it already exists."""
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def _require_ffmpeg(translate: TranslateFn | None) -> str:
    tr = translate or _noop_tr
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            tr("ffmpeg is required for the Studio. Install ffmpeg or place it next to the app.")
        )
    return ffmpeg


def _input_args(clip: _ResolvedClip) -> list[str]:
    args: list[str] = []
    if clip.start:
        args += ["-ss", f"{clip.start:.3f}"]
    args += ["-t", f"{clip.duration:.3f}", "-i", str(clip.path)]
    return args


# every audio join restates the format, so the encoder never sees it change
# mid-stream (some ffmpeg builds' AAC encoder stops with EINVAL if it does)
_AUDIO_FMT = (f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo")


# a gentle hum / hiss remover: rumble below 70 Hz out, then a spectral denoiser that
# learns the steady noise floor (it leaves speech and music alone)
DENOISE = "highpass=f=70,afftdn=nr=14:nf=-35"
# the loudness YouTube, Shorts and most players aim for (integrated LUFS, true peak dB)
LOUDNESS = "loudnorm=I=-14:TP=-1.5:LRA=11"
# music ducking: how loud the voice must be to push the music down, how hard, how fast
DUCK = "sidechaincompress=threshold=0.01:ratio=20:attack=10:release=300:makeup=1"  # about -15 dB


def _audio_norm(label: str, gain: float = 1.0, denoise: bool = False) -> str:
    return (
        f"{label}aresample={SAMPLE_RATE},"
        f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo,"
        + (f"{DENOISE}," if denoise else "")
        + "asetpts=PTS-STARTPTS"
        + ("" if gain == 1.0 else f",volume={gain:.3f}")  # clip level / mute
    )
