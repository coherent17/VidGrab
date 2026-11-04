"""Studio preview (the code lives in ui/studio/canvas.py and ui/studio/player.py; this module keeps the old names working)."""
from __future__ import annotations

from vidgrab.ui.studio.canvas import (  # noqa: F401
    BLENDED,
    VideoCanvas,
    _runs,
    fmt_time,
    frame_geometry,
    transport_icon,
)
from vidgrab.ui.studio.player import (  # noqa: F401  # noqa: F401
    QT_MULTIMEDIA_OK,
    MusicBed,
    QAudioOutput,
    QMediaPlayer,
    QVideoSink,
    Segment,
    StudioPreview,
    TransitionMark,
)
