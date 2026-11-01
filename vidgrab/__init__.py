"""VidGrab — download, flip & trim media from YouTube or local files."""

from ._version import __version__
from .ytdlp_update import activate as _use_downloaded_ytdlp

_use_downloaded_ytdlp()  # a newer yt-dlp the user downloaded goes first on sys.path

__all__ = ["__version__"]