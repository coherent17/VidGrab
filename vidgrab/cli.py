"""The `vidgrab` command: answers --help / --version / --info in the terminal
without opening a window, and starts the app otherwise.

Qt is only imported when the window really starts, so the text commands are
instant and work on a computer without a display."""

from __future__ import annotations

import argparse
import platform
import sys

from vidgrab._version import __version__

EPILOG = """\
Start the app:
  vidgrab                  (or: python -m vidgrab)
  from a Python script:    from vidgrab.app import main; main()

Installed with pip?
  update VidGrab:   pip install -U vidgrab-studio
  update yt-dlp:    pip install -U yt-dlp
  auto captions:    pip install "vidgrab-studio[captions]"
"""


def info() -> str:
    """What this installation has, for a bug report or a quick check."""
    from vidgrab import captions, downloader, ffmpeg_fetch

    ffmpeg = downloader.find_ffmpeg()
    try:
        import yt_dlp.version
        ytdlp = yt_dlp.version.__version__
    except Exception:  # noqa: BLE001
        ytdlp = "not installed"
    rows = [
        ("VidGrab", __version__),
        ("Python", f"{platform.python_version()} on {platform.system()} {platform.machine()}"),
        ("yt-dlp", ytdlp),
        ("ffmpeg", ffmpeg or "not found - VidGrab offers to download it the first time it needs it"),
        ("captions", "installed" if captions.installed()
         else 'not installed - pip install "vidgrab-studio[captions]"'),
        ("ffmpeg cache", str(ffmpeg_fetch.cache_dir())),
    ]
    return "\n".join(f"{name:<13}{value}" for name, value in rows)


def parse(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog="vidgrab", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="VidGrab: download videos, then edit them with subtitles, music and AI captions.",
        epilog=EPILOG)
    parser.add_argument("--version", "-V", action="version", version=f"VidGrab {__version__}")
    parser.add_argument("--info", action="store_true",
                        help="show what this installation has (ffmpeg, captions, yt-dlp) and exit")
    parser.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_known_args(argv)  # anything else (Qt's own options) goes on to Qt


def main(argv: list[str] | None = None) -> None:
    args, rest = parse(sys.argv[1:] if argv is None else argv)
    if args.info:
        print(info())
        return
    sys.argv = [sys.argv[0], *(["--selftest"] if args.selftest else []), *rest]
    from vidgrab.app import main as run_app

    run_app()


if __name__ == "__main__":
    main()
