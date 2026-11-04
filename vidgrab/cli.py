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

Without opening a window:
  vidgrab get URL [URL ...] [--mp3] [--quality 720] [--out DIR]
  vidgrab shrink FILE --mb 25          make a video fit a size limit
  vidgrab convert FILE --to mp3        mp4 mkv webm mp3 m4a opus wav flac
  vidgrab gif FILE --start 3 --length 4
  vidgrab best FILE --seconds 30       print the liveliest stretch (from the sound)
  vidgrab short FILE --seconds 30      make a vertical Short: best moment, face, captions
                                       (--no-face, --no-captions to skip those)
  from a Python script:    from vidgrab.app import main; main()

Installed with pip?
  update VidGrab:   pip install -U vidgrab-studio
  update yt-dlp:    pip install -U yt-dlp
  auto captions:    pip install "vidgrab-studio[captions]"
"""


def info() -> str:
    """What this installation has, for a bug report or a quick check."""
    from vidgrab.ai import captions
    from vidgrab.core import downloader, ffmpeg_fetch

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


COMMANDS = ("get", "shrink", "convert", "gif", "best", "short")


def _progress(label: str, pct: float | None) -> None:
    if pct is not None:
        print(f"\r{label} {pct:5.1f}%", end="", file=sys.stderr, flush=True)


def run_command(argv: list[str]) -> int:
    """`vidgrab get|shrink|convert|gif|best …`; the exit code (0 = fine)."""
    from pathlib import Path

    from vidgrab.ai import highlights
    from vidgrab.core import downloader, tools
    from vidgrab.media import studio

    parser = argparse.ArgumentParser(prog=f"vidgrab {argv[0]}")
    cmd = argv[0]
    if cmd == "get":
        parser.add_argument("urls", nargs="+")
        parser.add_argument("--mp3", action="store_true", help="audio only")
        parser.add_argument("--quality", help="highest video height, e.g. 720")
        parser.add_argument("--out", default=str(downloader.default_output_dir()), help="folder to save in")
    else:
        parser.add_argument("file")
        if cmd == "shrink":
            parser.add_argument("--mb", type=float, required=True, help="target size in MB")
        elif cmd == "convert":
            parser.add_argument("--to", choices=sorted(tools.CONVERT), required=True)
        elif cmd == "gif":
            parser.add_argument("--start", type=float, default=0.0)
            parser.add_argument("--length", type=float, default=4.0)
            parser.add_argument("--width", type=int, default=480)
        elif cmd == "short":
            parser.add_argument("--seconds", type=float, default=30.0)
            parser.add_argument("--no-face", action="store_true", help="centred crop, no face tracking")
            parser.add_argument("--no-captions", action="store_true")
        else:
            parser.add_argument("--seconds", type=float, default=30.0)
    args = parser.parse_args(argv[1:])
    try:
        if cmd == "get":
            for url in args.urls:
                out = downloader.download(url, args.out, "mp3" if args.mp3 else "mp4", quality=args.quality,
                                          on_progress=_progress)
                print(f"\n{out}")
            return 0
        src = args.file
        if not Path(src).is_file():
            print(f"vidgrab: no such file: {src}", file=sys.stderr)
            return 2
        dur = float(studio.probe_media(src).get("duration") or 0.0)
        if cmd == "short":
            from vidgrab.ai import captions, shorts

            out = tools.output_for(src, "short", ".mp4")
            shorts.make_short(src, out, seconds=args.seconds, follow=not args.no_face,
                              with_captions=not args.no_captions, models_dir=captions.default_models_dir(),
                              on_progress=_progress)
            print(f"\n{out}")
            return 0
        if cmd == "best":
            a, b = highlights.find_best(src, 0.0, dur, args.seconds)
            print(f"{a:.2f} {b:.2f}")
            return 0
        if cmd == "shrink":
            out = tools.output_for(src, f"{args.mb:g} MB", ".mp4")
            built, total = tools.compress_command(src, str(out), args.mb, dur, tools.suggested_height(args.mb, dur)), dur
        elif cmd == "convert":
            out = tools.output_for(src, "converted", tools.CONVERT[args.to][0])
            built, total = tools.convert_command(src, str(out), args.to), dur
        else:
            out = tools.output_for(src, "gif", ".gif")
            built, total = tools.gif_command(src, str(out), args.start, args.length, args.width), args.length
        tools.run_tool(built, total, label=cmd, on_progress=_progress)
        print(f"\n{out}")
        return 0
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"\nvidgrab: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in COMMANDS:
        sys.exit(run_command(argv))
    args, rest = parse(argv)
    if args.info:
        print(info())
        return
    sys.argv = [sys.argv[0], *(["--selftest"] if args.selftest else []), *rest]
    from vidgrab.ui.app import main as run_app

    run_app()


if __name__ == "__main__":
    main()
