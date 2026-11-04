"""The Studio's clip / song records."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from PySide6.QtGui import (
    QImage,
)

from vidgrab.media import effects
from vidgrab.media.studio import (
    transition_overlaps,
)


@dataclass
class _MediaClip:
    path: str
    info: dict
    start: float | None = None
    end: float | None = None
    thumb: QImage | None = None
    wave: list[float] = field(default_factory=list)
    # (source time, frame) samples drawn along the block — a filmstrip
    thumbs: list[tuple[float, QImage]] = field(default_factory=list)
    transition: str = "none"  # into this clip from the previous one
    transition_d: float = 1.0
    fit: str = "fit"
    zoom: float = 1.0
    pan_x: float = 0.5
    pan_y: float = 0.5
    volume: float = 1.0  # the clip's own sound, 0..2
    muted: bool = False
    speed: float = 1.0  # 0.25 .. 4
    denoise: bool = False  # reduce steady background noise when rendering
    fx: dict = field(default_factory=dict)  # picture effects (vidgrab.effects)

    @property
    def has_audio(self) -> bool:
        return bool(self.info.get("has_audio"))

    def gain(self) -> float:
        return 0.0 if self.muted else self.volume

    def edit(self) -> tuple:
        """The user-editable part, as plain comparable data (undo / projects)."""
        return (self.start, self.end, self.transition, self.transition_d, self.fit,
                self.zoom, self.pan_x, self.pan_y, self.volume, self.muted, self.speed,
                self.denoise, effects.edit_tuple(self.fx))

    def with_edit(self, edit: tuple) -> _MediaClip:
        (start, end, transition, transition_d, fit, zoom, pan_x, pan_y, volume,
         muted, *rest) = edit
        return replace(self, start=start, end=end, transition=transition,
                       transition_d=transition_d, fit=fit, zoom=zoom, pan_x=pan_x, pan_y=pan_y,
                       volume=volume, muted=muted, speed=rest[0] if rest else 1.0,
                       denoise=bool(rest[1]) if len(rest) > 1 else False,
                       fx=dict(rest[2]) if len(rest) > 2 else {})

    def frame_at(self, t: float) -> QImage | None:
        if not self.thumbs:
            return self.thumb
        return min(self.thumbs, key=lambda item: abs(item[0] - t))[1]

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def length(self) -> float:
        return float(self.info.get("duration") or 0.0)

    @property
    def has_video(self) -> bool:
        return bool(self.info.get("has_video"))

    def span(self) -> tuple[float, float]:
        s = self.start or 0.0
        e = self.end if self.end is not None else self.length
        return s, min(e, self.length) if self.length else e

    def part(self) -> float:
        """Length of the part of the source that is used (source seconds)."""
        s, e = self.span()
        return max(0.0, e - s)

    def kept(self) -> float:
        """How long the clip lasts in the montage (its part / speed)."""
        return self.part() / self.speed


def _fmt_precise(seconds: float) -> str:
    """M:SS.ss — hundredths, so one-frame nudges show."""
    m, sec = divmod(max(0.0, seconds), 60)
    return f"{int(m)}:{sec:05.2f}"


def _brightness(img: QImage) -> float:
    """Mean brightness (0-255) of a downscaled copy of *img*."""
    small = img.scaled(16, 9).convertToFormat(QImage.Format_Grayscale8)
    values = [small.pixelColor(x, y).value() for y in range(small.height())
              for x in range(small.width())]
    return sum(values) / max(1, len(values))


@dataclass
class _Song:
    """One background song: the part that plays, when it comes in, its level."""

    path: str
    info: dict
    wave: list[float] = field(default_factory=list)
    start: float = 0.0
    end: float | None = None  # None = to the end of the song
    offset: float = 0.0  # where it comes in on the montage timeline
    volume: int = 35  # percent
    fade: float = 0.0  # fade in / out at its own edges (s)

    @property
    def length(self) -> float:
        return float(self.info.get("duration") or 0.0)

    def span(self) -> tuple[float, float]:
        return self.start, (self.end if self.end is not None else self.length)

    def edit(self) -> tuple:
        return (self.path, self.start, self.end, self.offset, self.volume, self.fade)


def clip_overlaps(clips: list[_MediaClip]) -> list[float]:
    return transition_overlaps([c.kept() for c in clips],
                               [(c.transition, c.transition_d) for c in clips])


# ── multi-track timeline ──────────────────────────────────────────────────
