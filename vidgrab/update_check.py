"""Qt-free **new version** check: one quiet request to GitHub's releases API.

It only *tells* the user (a note in the Download page, a link to the release);
nothing is downloaded or installed. It never raises: offline, rate-limited or
a strange answer all mean "no news"."""
from __future__ import annotations

import json
import re
import urllib.request

from vidgrab._version import __version__

REPO = "coherent17/VidGrab"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE = f"https://github.com/{REPO}/releases/latest"


def parse_version(text: str) -> tuple[int, ...]:
    """'v4.1.1' / '4.1.1-beta' -> (4, 1, 1); () when there are no numbers."""
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", text or "")
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


def is_newer(latest: str, current: str = __version__) -> bool:
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def latest_release(timeout: float = 4.0, proxy: str = "", current: str = __version__) -> dict | None:
    """{'version', 'url', 'notes'} when a newer release exists, else None."""
    try:
        handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []
        opener = urllib.request.build_opener(*handlers)
        req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": f"VidGrab/{current}"})
        with opener.open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        tag = str(data.get("tag_name") or "")
        if data.get("draft") or data.get("prerelease") or not is_newer(tag, current):
            return None
        return {"version": tag.lstrip("vV"), "url": str(data.get("html_url") or PAGE),
                "notes": str(data.get("body") or "")[:600]}
    except Exception:  # noqa: BLE001 - a nicety, never an error
        return None
