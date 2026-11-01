"""Download the pinned ffmpeg / ffprobe (see ffmpeg/pin.json) and keep it in the
user's cache.

Used by the packaged builds that do not carry ffmpeg inside them (the macOS app,
and a pip install on any system) and by `scripts/fetch_ffmpeg.py`, which puts the
same files in ``ffmpeg/<platform>/`` for the builds that do. Every archive's
SHA-256 must match the pin, so everyone runs the same binaries.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import platform
import sys
import tarfile
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/{release}/{name}"
MAX_ARCHIVE = 400 * 1024 * 1024
Progress = Callable[[int, int], None]  # bytes done, bytes expected (0 = unknown)


def load_pin() -> dict:
    """The pin: inside an installed package, or ffmpeg/pin.json in a checkout."""
    here = Path(__file__).resolve().parent
    for path in (here / "ffmpeg_pin.json", here.parent / "ffmpeg" / "pin.json"):
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise RuntimeError("ffmpeg pin file not found")


def platform_key() -> str | None:
    """Which pinned build fits this computer (None: none does)."""
    machine = platform.machine().lower()
    if sys.platform == "win32":
        return "win" if machine in ("amd64", "x86_64") else None
    if sys.platform == "darwin":
        return "mac-arm64" if machine in ("arm64", "aarch64") else "mac-x64"
    return "linux" if machine in ("x86_64", "amd64") else None


def cache_dir() -> Path:
    """Where a downloaded ffmpeg lives (the local cache, next to the speech models)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA", str(Path.home())))
        return base / "VidGrab" / "ffmpeg"
    return Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "vidgrab" / "ffmpeg"


def cached_ffmpeg() -> str | None:
    exe = cache_dir() / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    return str(exe) if exe.is_file() else None


def _download(url: str, sha256: str, progress: Progress | None) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:  # a pinned https URL
            total = int(resp.headers.get("Content-Length") or 0)
            if total > MAX_ARCHIVE:
                raise RuntimeError("the ffmpeg download is larger than expected")
            chunks, done = [], 0
            while chunk := resp.read(1 << 20):
                chunks.append(chunk)
                done += len(chunk)
                if done > MAX_ARCHIVE:
                    raise RuntimeError("the ffmpeg download is larger than expected")
                if progress:
                    progress(done, total)
    except OSError as exc:
        raise RuntimeError(f"could not download ffmpeg: {exc}") from exc
    data = b"".join(chunks)
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        raise RuntimeError(f"the downloaded ffmpeg does not match its checksum ({url.rsplit('/', 1)[-1]})")
    return data


def _pick(data: bytes, name: str, wanted: set[str]) -> dict[str, bytes]:
    """The wanted executables out of a BtbN archive (zip or tar.xz, under bin/)."""
    found: dict[str, bytes] = {}
    if name.endswith(".zip"):
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
    return found


def fetch(key: str, dest: Path, *, pin: dict | None = None, progress: Progress | None = None,
          log: Callable[[str], None] = print) -> Path:
    """Put the pinned ffmpeg + ffprobe for platform *key* in *dest*. Does nothing
    when that version is already there."""
    pin = pin or load_pin()
    spec = pin["files"].get(key)
    if spec is None:
        raise RuntimeError(f"no ffmpeg is pinned for {key!r} (have {', '.join(pin['files'])})")
    exe = ".exe" if key == "win" else ""
    stamp = dest / "VERSION"
    label = spec.get("name") or spec["ffmpeg"]["name"]
    if stamp.is_file() and stamp.read_text().strip() == label \
            and (dest / f"ffmpeg{exe}").is_file() and (dest / f"ffprobe{exe}").is_file():
        log(f"ffmpeg {spec.get('version', pin['version'])} already in {dest}")
        return dest

    found: dict[str, bytes] = {}
    if "ffmpeg" in spec:  # one gzip per program (macOS)
        for prog in ("ffmpeg", "ffprobe"):
            item = spec[prog]
            log(f"downloading {item['name']}")
            found[prog] = gzip.decompress(_download(spec["url_base"] + item["name"], item["sha256"], progress))
    else:
        url = BTBN.format(release=pin["release"], name=spec["name"])
        log(f"downloading {url}")
        data = _download(url, spec["sha256"], progress)
        found = _pick(data, spec["name"], {f"ffmpeg{exe}", f"ffprobe{exe}"})
        missing = {f"ffmpeg{exe}", f"ffprobe{exe}"} - found.keys()
        if missing:
            raise RuntimeError(f"{spec['name']} has no {', '.join(sorted(missing))}")

    dest.mkdir(parents=True, exist_ok=True)
    for base, blob in found.items():
        target = dest / base
        tmp = target.with_name(target.name + ".part")
        tmp.write_bytes(blob)
        tmp.chmod(0o755)
        tmp.replace(target)
    stamp.write_text(label + "\n")
    log(f"ffmpeg {spec.get('version', pin['version'])} -> {dest}")
    return dest


def ensure(progress: Progress | None = None) -> str:
    """Make sure the user's cache has ffmpeg for this computer; returns its path."""
    key = platform_key()
    if key is None:
        raise RuntimeError("no ready-made ffmpeg for this system: install ffmpeg and put it on PATH")
    dest = fetch(key, cache_dir(), progress=progress, log=lambda _m: None)
    return str(dest / ("ffmpeg.exe" if key == "win" else "ffmpeg"))
