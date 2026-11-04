"""Qt-free **install the new version** for the single-file Windows / Linux builds.

Only when the user asks (the Download page's "Update now"): `plan()` says whether this
copy of VidGrab can replace itself (a frozen single-file build in a folder it may
write to; the macOS app, pip installs and a source checkout just get the link),
`download()` fetches the release's file next to the running one and checks it against
the release's `SHA256SUMS.txt`, `install()` swaps it in. A running `.exe` can be
*renamed* on Windows (not overwritten), so the old file moves aside as `<name>.old`
and the new one takes its name; Linux simply renames over the binary. The old file is
removed by the next start (`cleanup()`); until then it is the way back if the new
file is broken. Nothing here raises for the caller except `UpdateError` with a
sentence that can be shown as is."""
from __future__ import annotations

import hashlib
import os
import stat
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ASSETS = {"win32": "VidGrab-windows-x64.exe", "linux": "VidGrab-linux-x64"}
MIN_BYTES = 10 * 1024 * 1024  # a real build is far bigger: anything smaller is an error page
SUFFIX_NEW = ".new"
SUFFIX_OLD = ".old"


class UpdateError(RuntimeError):
    """Message is meant for the user."""


@dataclass
class Plan:
    asset: str
    exe: Path


def plan(news: dict, *, frozen: bool | None = None, exe: str | None = None, platform: str | None = None) -> Plan | None:
    """What to do for this release, or None when this copy can't replace itself."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    platform = platform or sys.platform
    asset = ASSETS.get(platform)
    if not frozen or not asset or asset not in (news.get("assets") or {}):
        return None
    path = Path(exe or sys.executable)
    if path.suffix.lower() not in (".exe", "") or "VidGrab.app" in path.parts:
        return None
    if not os.access(path.parent, os.W_OK):  # e.g. Program Files: don't ask for admin, just show the page
        return None
    return Plan(asset, path)


def _fetch(url: str, dest: Path, on_progress: Callable[[int], None] | None, cancelled: Callable[[], bool] | None,
           proxy: str = "") -> None:
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={"User-Agent": "VidGrab-updater"})
    with opener.open(req, timeout=30) as resp, open(dest, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        while chunk := resp.read(1 << 18):
            if cancelled and cancelled():
                raise UpdateError("Cancelled")
            fh.write(chunk)
            got += len(chunk)
            if on_progress:
                on_progress(int(got * 100 / total) if total else -1)


def expected_hash(sums: str, name: str) -> str | None:
    """The SHA-256 of *name* from a `sha256sum` listing."""
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == name:
            return parts[0].lower()
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def download(news: dict, how: Plan, *, on_progress: Callable[[int], None] | None = None,
             cancelled: Callable[[], bool] | None = None, proxy: str = "",
             fetch: Callable[..., None] = _fetch) -> Path:
    """The new file, next to the running one (same disk, so the swap is a rename)."""
    assets = news.get("assets") or {}
    sums_url = assets.get("SHA256SUMS.txt")
    if not sums_url:
        raise UpdateError("This release has no checksum list, so it can't be installed safely.")
    dest = how.exe.with_name(how.exe.name + SUFFIX_NEW)
    sums_file = dest.with_name(dest.name + ".sums")
    try:
        try:
            fetch(sums_url, sums_file, None, cancelled, proxy)
            want = expected_hash(sums_file.read_text("utf-8", "replace"), how.asset)
            if not want:
                raise UpdateError("The release's checksum list doesn't include this file.")
            fetch(assets[how.asset], dest, on_progress, cancelled, proxy)
        except UpdateError:
            raise
        except OSError as exc:
            raise UpdateError(f"Could not download the update: {exc}") from exc
        if dest.stat().st_size < MIN_BYTES:
            raise UpdateError("The downloaded file is too small to be VidGrab.")
        if sha256(dest) != want:
            raise UpdateError("The downloaded file does not match its checksum, so it was not installed.")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    finally:
        sums_file.unlink(missing_ok=True)
    return dest


def install(new_file: Path, exe: Path) -> Path:
    """Swap *new_file* in as *exe*; the old one stays as `<exe>.old`. Returns *exe*."""
    old = exe.with_name(exe.name + SUFFIX_OLD)
    try:
        if sys.platform != "win32":
            new_file.chmod(new_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        old.unlink(missing_ok=True)
        os.replace(exe, old)
        try:
            os.replace(new_file, exe)
        except OSError:
            os.replace(old, exe)  # put the working copy back
            raise
    except OSError as exc:
        new_file.unlink(missing_ok=True)
        raise UpdateError(f"Could not install the update: {exc}") from exc
    return exe


def cleanup(exe: str | None = None) -> None:
    """At start: remove the leftovers of an update (the previous version, a half download)."""
    path = Path(exe or sys.executable)
    for suffix in (SUFFIX_OLD, SUFFIX_NEW, SUFFIX_NEW + ".sums"):
        try:
            path.with_name(path.name + suffix).unlink(missing_ok=True)
        except OSError:
            pass
