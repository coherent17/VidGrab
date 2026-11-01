"""Download the pinned ffmpeg / ffprobe (see ffmpeg/pin.json) into ffmpeg/<platform>/.

Usage: python scripts/fetch_ffmpeg.py [linux|win|mac-arm64|mac-x64]   (default: this computer)

The archive's SHA-256 must match the pin, so every build, CI job and developer
machine runs the exact same binaries. Does nothing when the pinned version is
already in place (ffmpeg/<platform>/VERSION). The work is in vidgrab/ffmpeg_fetch.py,
which the app also uses to fetch ffmpeg on first run.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vidgrab import ffmpeg_fetch


def main() -> None:
    key = sys.argv[1] if len(sys.argv) > 1 else ffmpeg_fetch.platform_key()
    pin = ffmpeg_fetch.load_pin()
    if key not in pin["files"]:
        sys.exit(f"unknown platform {key!r} (expected one of {', '.join(pin['files'])})")
    # macOS builds of both CPUs are kept in ffmpeg/mac/ (the spec / find_ffmpeg look there)
    folder = "mac" if key.startswith("mac") else key
    try:
        ffmpeg_fetch.fetch(key, ROOT / "ffmpeg" / folder)
    except RuntimeError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
