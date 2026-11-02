"""Qt-free one-shot media tools (Tools page, `vidgrab tool …`): compress to a
size, convert, make a GIF, extract audio. Each `*_command` is pure and unit-tested;
`run_tool()` runs one through `studio._run_with_progress`."""
from __future__ import annotations

from pathlib import Path

from vidgrab import studio
from vidgrab.downloader import find_ffmpeg

AUDIO_KBPS = 128
MIN_VIDEO_KBPS = 80
# convert targets: key -> (extension, ffmpeg output args)
CONVERT = {
    "mp4": (".mp4", ["-c:v", "libx264", "-preset", "medium", "-crf", "22", "-c:a", "aac", "-b:a", "160k",
                     "-movflags", "+faststart"]),
    "mkv": (".mkv", ["-c:v", "libx264", "-preset", "medium", "-crf", "22", "-c:a", "aac", "-b:a", "160k"]),
    "webm": (".webm", ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-c:a", "libopus", "-b:a", "128k"]),
    "mp3": (".mp3", ["-vn", "-c:a", "libmp3lame", "-b:a", "192k"]),
    "m4a": (".m4a", ["-vn", "-c:a", "aac", "-b:a", "192k"]),
    "opus": (".opus", ["-vn", "-c:a", "libopus", "-b:a", "128k"]),
    "wav": (".wav", ["-vn", "-c:a", "pcm_s16le"]),
    "flac": (".flac", ["-vn", "-c:a", "flac"]),
}
AUDIO_TARGETS = ("mp3", "m4a", "opus", "wav", "flac")
SIZE_PRESETS_MB = (8, 25, 50, 100)  # Discord-ish, e-mail, and so on
GIF_WIDTHS = (320, 480, 640)


def video_kbps(target_mb: float, duration: float, audio_kbps: int = AUDIO_KBPS) -> int:
    """Video bitrate that makes a *duration*-second file about *target_mb* MB
    (5 % kept back for the container)."""
    total = target_mb * 8192 * 0.95 / max(duration, 0.1)
    return max(int(total - audio_kbps), MIN_VIDEO_KBPS)


def compress_command(src: str, out: str, target_mb: float, duration: float, height: int = 0) -> list[str]:
    """Re-encode to about *target_mb* MB. *height* > 0 also shrinks the picture
    (a tiny bitrate on a big picture looks like mush)."""
    kbps = video_kbps(target_mb, duration)
    cmd = [find_ffmpeg() or "ffmpeg", "-y", "-i", src]
    if height:
        cmd += ["-vf", f"scale=-2:'min({height},ih)'"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.5)}k",
            "-bufsize", f"{kbps * 2}k", "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-movflags", "+faststart", out]
    return cmd


def suggested_height(target_mb: float, duration: float) -> int:
    """A picture height that suits that much data (0 = keep the size)."""
    k = video_kbps(target_mb, duration)
    return 0 if k >= 2500 else 720 if k >= 1200 else 480 if k >= 500 else 360


def convert_command(src: str, out: str, fmt: str) -> list[str]:
    ext, args = CONVERT[fmt]
    if not out.lower().endswith(ext):
        raise ValueError(f"{out} should end with {ext}")
    return [find_ffmpeg() or "ffmpeg", "-y", "-i", src, *args, out]


def gif_command(src: str, out: str, start: float, length: float, width: int = 480, fps: int = 12) -> list[str]:
    graph = (f"fps={fps},scale={width}:-2:flags=lanczos,split[a][b];"
             "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4")
    return [find_ffmpeg() or "ffmpeg", "-y", "-ss", f"{max(start, 0):.3f}", "-t", f"{length:.3f}", "-i", src,
            "-filter_complex", graph, "-loop", "0", out]


def output_for(src: str | Path, suffix: str, ext: str, folder: str | Path | None = None) -> Path:
    """A free output name next to the source (or in *folder*): `name (small).mp4`."""
    src = Path(src)
    return studio.unique_path(Path(folder or src.parent) / f"{src.stem} ({suffix}){ext}")


def run_tool(cmd: list[str], total: float, *, label: str, on_progress=None, on_log=None, translate=None) -> Path:
    """Run *cmd*; the last argument is the output file, deleted if it fails."""
    out = Path(cmd[-1])
    try:
        studio._run_with_progress(cmd, total, label=label, on_progress=on_progress, on_log=on_log,
                                  translate=translate)
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    if on_progress:
        on_progress(label, 100.0)
    return out
