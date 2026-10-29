"""Download the pinned ffmpeg / ffprobe (see ffmpeg/pin.json) into ffmpeg/<platform>/.

Usage: python scripts/fetch_ffmpeg.py [linux|win]   (default: this OS)

The archive's SHA-256 must match the pin, so every build, CI job and developer
machine runs the exact same binaries. Does nothing when the pinned version is
already in place (ffmpeg/<platform>/VERSION).
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIN = json.loads((ROOT / "ffmpeg" / "pin.json").read_text(encoding="utf-8"))
URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/{release}/{name}"


def fetch(platform: str) -> Path:
    spec = PIN["files"][platform]
    dest = ROOT / "ffmpeg" / platform
    stamp = dest / "VERSION"
    exe = ".exe" if platform == "win" else ""
    if stamp.is_file() and stamp.read_text().strip() == spec["name"] \
            and (dest / f"ffmpeg{exe}").is_file() and (dest / f"ffprobe{exe}").is_file():
        print(f"ffmpeg {PIN['version']} already in {dest}")
        return dest

    url = URL.format(release=PIN["release"], name=spec["name"])
    print(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as resp:  # pinned https URL
        data = resp.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != spec["sha256"]:
        sys.exit(f"SHA-256 mismatch for {spec['name']}: got {digest}, pinned {spec['sha256']}")

    wanted = {f"ffmpeg{exe}", f"ffprobe{exe}"}
    found: dict[str, bytes] = {}
    if spec["name"].endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                base = info.filename.rsplit("/", 1)[-1]
                if base in wanted and "/bin/" in info.filename:
                    found[base] = zf.read(info)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as tf:
            for member in tf.getmembers():
                base = member.name.rsplit("/", 1)[-1]
                if base in wanted and "/bin/" in member.name and member.isfile():
                    found[base] = tf.extractfile(member).read()  # type: ignore[union-attr]
    missing = wanted - found.keys()
    if missing:
        sys.exit(f"{spec['name']} has no {', '.join(sorted(missing))}")

    dest.mkdir(parents=True, exist_ok=True)
    for base, blob in found.items():
        target = dest / base
        target.write_bytes(blob)
        target.chmod(0o755)
    stamp.write_text(spec["name"] + "\n")
    print(f"ffmpeg {PIN['version']} -> {dest}")
    return dest


def main() -> None:
    platform = sys.argv[1] if len(sys.argv) > 1 else ("win" if sys.platform == "win32" else "linux")
    if platform not in PIN["files"]:
        sys.exit(f"unknown platform {platform!r} (expected one of {', '.join(PIN['files'])})")
    fetch(platform)


if __name__ == "__main__":
    main()
