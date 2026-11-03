"""Qt-free **Make a Short**: a long video in, a vertical clip out — in one go.

It chains what the Studio does by hand: the liveliest stretch (`highlights`), a
9:16 crop that follows the main face (`reframe`), word-by-word captions
(`captions`) and one render (`studio.compose_video`, loudness evened out). Every
step after the first is optional and falls back quietly: no face found or no speech
add-on means a centred crop / no captions, never a failed Short.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from vidgrab import captions, highlights, reframe, studio
from vidgrab.downloader import DownloadCancelled

LENGTHS = (15, 30, 60)  # seconds; Shorts, Reels and TikTok stop at 60
CAPTION_Y = 0.74  # where the words sit on the tall frame (fraction of its height)

ProgressFn = Callable[[str, float | None], None]


def plan(duration: float, seconds: float) -> tuple[float, float]:
    """(start, end) of the part to keep: all of a short video, else the best *seconds*."""
    seconds = max(1.0, min(float(seconds), 60.0))
    return (0.0, duration) if duration <= seconds + 0.5 else (0.0, seconds)


def caption_style() -> studio.SubtitleStyle:
    return studio.SubtitleStyle(size=30, bold=True, outline=True)


def style_cues(cues: list[studio.SubtitleCue]) -> list[studio.SubtitleCue]:
    """Big centred words, the spoken one lit up (plain pop-in where there are no word times)."""
    for cue in cues:
        cue.animation = "highlight" if cue.words else "pop"
        cue.x, cue.y, cue.anchor = 0.5, CAPTION_Y, 5
    return cues


def make_short(src: str | Path, out: str | Path, *, seconds: float = 30, follow: bool = True,
               with_captions: bool = True, models_dir: str | Path, gpu: bool = True,
               on_progress: ProgressFn | None = None, on_log: Callable[[str], None] | None = None,
               cancelled: Callable[[], bool] | None = None,
               translate: studio.TranslateFn | None = None) -> Path:
    """Render *src* as a vertical Short at *out*. Returns the file."""
    tr = translate or (lambda text, **kw: text.format(**kw) if kw else text)
    src = str(src)

    def check() -> None:
        if cancelled and cancelled():
            raise DownloadCancelled(tr("Cancelled"))

    top = [0.0]  # the bar only ever moves forward

    def stage(lo: float, hi: float) -> ProgressFn:
        """Progress callback that maps a step's 0-100 onto lo..hi of the whole job."""
        def report(label: str, pct: float | None) -> None:
            check()
            if on_progress:
                value = None
                if pct is not None:
                    value = top[0] = max(top[0], lo + (hi - lo) * max(0.0, min(pct, 100.0)) / 100)
                on_progress(label, value)
        return report

    def log(text: str) -> None:
        if on_log:
            on_log(text)

    info = studio.probe_media(src, translate=translate)
    duration = float(info.get("duration") or 0.0)
    if duration <= 0 or not info.get("has_video"):
        raise RuntimeError(tr("This file has no video to make a Short from."))

    report = stage(0, 8)
    report(tr("Finding the best moment…"), 0)
    start, end = plan(duration, seconds)
    if duration > seconds + 0.5 and info.get("has_audio"):
        start, end = highlights.find_best(src, 0.0, duration, min(float(seconds), 60.0))
    elif duration > seconds + 0.5:
        start, end = 0.0, min(float(seconds), 60.0)
    check()
    report("", 100)

    clip = studio.Clip(src, start=f"{start:.3f}", end=f"{end:.3f}", fit="fill")
    if follow and reframe.available():
        try:
            keys = reframe.follow_face(src, start, end, models_dir, on_progress=stage(8, 38),
                                       cancelled=cancelled, translate=translate)
        except DownloadCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - a centred crop is still a good Short
            log(tr("Could not follow the face ({exc}); using a centred crop.", exc=exc))
            keys = []
        if keys:
            from vidgrab import effects

            clip.fx = effects.sanitize({"follow": keys})
    check()

    cues: list[studio.SubtitleCue] = []
    if with_captions and info.get("has_audio"):
        try:
            cues = style_cues(captions.transcribe(
                [captions.CaptionSource(src, start=start, end=end)], models_dir, gpu=gpu,
                on_progress=stage(38, 70), on_log=log, translate=translate))
        except DownloadCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - captions are a bonus
            log(tr("Could not make captions ({exc}); rendering without them.", exc=exc))
    check()

    result = studio.compose_video(
        [clip], out, resolution="vertical", subtitles=cues or None,
        subtitle_style=caption_style() if cues else None, quality="balanced",
        normalize_loudness=True, on_progress=stage(70, 100), on_log=on_log, translate=translate)
    return Path(result)
