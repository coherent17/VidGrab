"""One queued download: the media itself plus (optionally) its subtitles.

Qt-free so it can be unit-tested; the Download page queues `DownloadJob`s
and runs them one at a time through `run_job` on a worker thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vidgrab.downloader import (
    DEFAULT_NAME,
    LogCallback,
    ProgressCallback,
    TranslateFn,
    _noop_tr,
    _parse_trim,
    download,
    download_both,
    download_playlist,
    fetch_subtitles,
)
from vidgrab.studio import Clip, compose_video, format_srt, parse_srt, retime_cues

MEDIA_SUFFIXES = {".mp4", ".mp3", ".m4a", ".webm", ".mkv"}


@dataclass
class DownloadJob:
    url: str
    output_dir: str
    fmt: str = "mp4"  # "mp4" | "mp3" | "both"
    quality: str | None = None
    video_filter: str | None = None
    speed: float | None = None
    section_start: str | None = None
    section_end: str | None = None
    playlist: bool = False
    subtitles: str | None = None  # language key from downloader.SUBTITLE_LANGS
    burn_subtitles: bool = False
    name_template: str = DEFAULT_NAME  # yt-dlp output template for the file name


def run_job(
    job: DownloadJob,
    *,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
) -> list[Path]:
    """Download *job*; returns the saved files (media first, then any .srt)."""
    tr = translate or _noop_tr
    common = {"on_progress": on_progress, "on_log": on_log, "translate": translate,
              "name_template": job.name_template or DEFAULT_NAME}
    if job.playlist:
        return download_playlist(
            job.url, job.output_dir, "mp3" if job.fmt == "mp3" else "mp4",
            quality=job.quality, **common,
        )
    edit = {
        "video_filter": job.video_filter, "speed": job.speed, "quality": job.quality,
        "section_start": job.section_start, "section_end": job.section_end,
    }
    if job.fmt == "both":
        files = list(download_both(job.url, job.output_dir, **edit, **common))
    else:
        files = [download(job.url, job.output_dir, job.fmt, **edit, **common)]
    if not job.subtitles:
        return files

    media = next((f for f in files if f.suffix.lower() == ".mp4"), files[0])
    if on_progress:
        on_progress(tr("Downloading subtitles…"), None)
    srt = fetch_subtitles(job.url, media.parent, job.subtitles, media.stem,
                          on_log=on_log, translate=translate)
    if srt is None:
        return files

    # line the captions up with the trimmed / sped-up result
    cues = parse_srt(srt.read_text(encoding="utf-8", errors="replace"))
    if job.section_start or job.section_end or job.speed:
        start, end = _parse_trim(job.section_start, job.section_end, translate=translate)
        cues = retime_cues(cues, start, None if end == float("inf") else end, job.speed)
        srt.write_text(format_srt(cues), encoding="utf-8")

    if job.burn_subtitles and media.suffix.lower() == ".mp4" and cues:
        burned = compose_video(
            [Clip(str(media))], media.with_name(f"{media.stem}.subtitled.mp4"),
            subtitles=cues, on_progress=on_progress, on_log=on_log, translate=translate,
        )
        media.unlink(missing_ok=True)
        burned.rename(media)
        srt.unlink(missing_ok=True)
        return files
    return [*files, srt]
