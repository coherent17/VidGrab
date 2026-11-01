"""Keep yt-dlp current without waiting for a new VidGrab release.

Sites change their pages every few weeks and yt-dlp follows; the copy inside
the app is frozen at build time. This module can fetch the newest yt-dlp
*wheel* from PyPI (pure Python), unpack it into the user's cache and put it
first on ``sys.path`` at the next start, so it is used instead of the
bundled one. Nothing here imports yt-dlp at load time: `activate()` runs
before anything else does.

Safety: the wheel's SHA-256 comes from PyPI's metadata (same HTTPS channel),
only files under ``yt_dlp/`` are unpacked, an update made under another
VidGrab version is ignored (a new release ships a newer yt-dlp anyway), and
an update that fails to import is switched off again.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from vidgrab._version import __version__ as APP_VERSION

PYPI_JSON = "https://pypi.org/pypi/yt-dlp/json"
MAX_WHEEL = 40 * 1024 * 1024
_POINTER = "current.json"


def update_root() -> Path:
    """Where updates live (VIDGRAB_YTDLP_DIR overrides it, for tests)."""
    env = os.environ.get("VIDGRAB_YTDLP_DIR")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA", str(Path.home())))
        return base / "VidGrab" / "yt-dlp"
    return Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "vidgrab" / "yt-dlp"


def _read_pointer(root: Path) -> dict | None:
    try:
        data = json.loads((root / _POINTER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def version_key(version: str) -> tuple[int, ...]:
    """'2026.07.04' / '2026.7.4.123' -> (2026, 7, 4[, 123]) for comparing."""
    parts = []
    for piece in str(version).split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def installed() -> dict | None:
    """The update that will be used at the next start: {version, app, path}."""
    root = update_root()
    ptr = _read_pointer(root)
    if not ptr or ptr.get("app") != APP_VERSION:
        return None
    path = root / str(ptr.get("version", ""))
    if not (path / "yt_dlp" / "__init__.py").is_file():
        return None
    return {"version": ptr["version"], "app": ptr["app"], "path": str(path)}


def activate() -> bool:
    """Put the downloaded yt-dlp first on sys.path (call before importing
    it). Returns True if it is in use. Never raises."""
    try:
        found = installed()
        if not found or "yt_dlp" in sys.modules:
            return False
        sys.path.insert(0, found["path"])
        try:
            import yt_dlp
            import yt_dlp.extractor
            from yt_dlp.version import __version__ as got
            if got != found["version"] or not str(
                    Path(yt_dlp.__file__).resolve()).startswith(str(Path(found["path"]).resolve())):
                raise ImportError("wrong yt-dlp loaded")
        except Exception:  # noqa: BLE001 - fall back to the bundled copy
            _forget()
            return False
        return True
    except Exception:  # noqa: BLE001
        return False


def _forget() -> None:
    """Undo an update that did not load: drop it from sys.path / sys.modules
    and delete it, so the bundled yt-dlp is used from now on."""
    found = installed()
    if found and found["path"] in sys.path:
        sys.path.remove(found["path"])
    for name in [n for n in sys.modules if n == "yt_dlp" or n.startswith("yt_dlp.")]:
        del sys.modules[name]
    reset()


def reset() -> None:
    """Go back to the yt-dlp inside the app (takes effect at the next start)."""
    shutil.rmtree(update_root(), ignore_errors=True)


def current_version() -> str:
    from yt_dlp.version import __version__
    return __version__


def in_use() -> bool:
    """Is the running yt-dlp the downloaded one (not the bundled copy)?"""
    import yt_dlp
    try:
        return Path(yt_dlp.__file__).resolve().is_relative_to(update_root().resolve())
    except (OSError, ValueError):
        return False


def _fetch(url: str, limit: int, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"VidGrab/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("download too large")
    return data


def latest() -> dict:
    """The newest release on PyPI: {version, url, sha256, size}."""
    meta = json.loads(_fetch(PYPI_JSON, 4 * 1024 * 1024))
    version = meta["info"]["version"]
    for f in meta["urls"]:
        if f.get("packagetype") == "bdist_wheel" and f["filename"].endswith("none-any.whl"):
            return {"version": version, "url": f["url"], "sha256": f["digests"]["sha256"],
                    "size": f.get("size") or 0}
    raise RuntimeError("no wheel found for the latest yt-dlp")


def check() -> dict:
    """{current, latest, newer, url, sha256}: is there a newer yt-dlp than the running one?"""
    cur = current_version()
    new = latest()
    pending = installed()
    newer = version_key(new["version"]) > version_key(cur) and not (
        pending and version_key(pending["version"]) >= version_key(new["version"]))
    return {"current": cur, "latest": new["version"], "newer": newer,
            "url": new["url"], "sha256": new["sha256"], "size": new["size"],
            "pending": pending["version"] if pending else None}


def install_wheel(data: bytes, version: str, sha256: str) -> Path:
    """Verify and unpack a yt-dlp wheel; it is used from the next start."""
    if hashlib.sha256(data).hexdigest() != sha256.lower():
        raise RuntimeError("the downloaded file does not match its checksum")
    root = update_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / version
    tmp = root / f"{version}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                name = info.filename
                if info.is_dir() or not name.startswith("yt_dlp/"):
                    continue
                parts = Path(name).parts
                if ".." in parts or Path(name).is_absolute():
                    raise RuntimeError("unsafe path in the update")
                dest = tmp / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(info))
        if not (tmp / "yt_dlp" / "__init__.py").is_file():
            raise RuntimeError("the update has no yt_dlp package")
        shutil.rmtree(target, ignore_errors=True)
        tmp.rename(target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    (root / _POINTER).write_text(json.dumps({"version": version, "app": APP_VERSION}),
                                 encoding="utf-8")
    for old in root.iterdir():  # keep only the new one
        if old.is_dir() and old.name != version:
            shutil.rmtree(old, ignore_errors=True)
    return target


def update(progress: Callable[[str], None] | None = None) -> str:
    """Download and install the newest yt-dlp; returns its version."""
    info = check()
    if progress:
        progress(info["latest"])
    data = _fetch(info["url"], MAX_WHEEL, timeout=120.0)
    install_wheel(data, info["latest"], info["sha256"])
    return info["latest"]
