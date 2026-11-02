"""Qt-free Subscriptions: channels / playlists you follow, and their newest videos.

`<config>/subscriptions.json` is a list of `{url, title, seen}`; *seen* holds the
ids of videos already shown, so `new_ids()` can mark what appeared since."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yt_dlp

from vidgrab import downloader

FEED_SIZE = 15
SEEN_LIMIT = 400


@dataclass
class Subscription:
    url: str
    title: str = ""
    seen: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FeedItem:
    id: str
    title: str
    url: str
    duration: float | None = None


def load(path: Path) -> list[Subscription]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    subs = []
    for d in raw if isinstance(raw, list) else []:
        if isinstance(d, dict) and isinstance(d.get("url"), str) and d["url"]:
            seen = [s for s in d.get("seen", []) if isinstance(s, str)]
            subs.append(Subscription(d["url"], str(d.get("title", "")), seen[-SEEN_LIMIT:]))
    return subs


def save(path: Path, subs: list[Subscription]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([asdict(s) for s in subs], ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def add(subs: list[Subscription], url: str, title: str = "") -> Subscription | None:
    """Follow *url* (None when it is already followed)."""
    url = url.strip()
    if not url or any(s.url == url for s in subs):
        return None
    sub = Subscription(url, title)
    subs.append(sub)
    return sub


def is_single_video(url: str) -> bool:
    """A link to one video (not a channel or playlist), which has no feed."""
    u = url.lower()
    return ("watch?v=" in u and "list=" not in u) or "youtu.be/" in u or "/shorts/" in u


def feed_url(url: str) -> str:
    """A channel's home page lists tabs, not videos: point it at its Videos tab."""
    u = url.strip().rstrip("/")
    if "youtube.com" in u and any(p in u for p in ("/@", "/channel/", "/c/", "/user/")):
        tail = u.rsplit("/", 1)[-1]
        if tail not in ("videos", "shorts", "streams", "playlists", "featured"):
            return u + "/videos"
    return u


def parse_feed(info: dict) -> tuple[str, list[FeedItem]]:
    """(title, newest videos first) from a flat yt-dlp playlist result."""
    items = []
    for e in info.get("entries") or []:
        if not e or not e.get("id"):
            continue
        url = e.get("url") or e.get("webpage_url") or ""
        if not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={e['id']}"
        items.append(FeedItem(str(e["id"]), downloader.display_text(e.get("title") or str(e["id"])),
                              url, e.get("duration")))
    return downloader.display_text(info.get("title") or ""), items[:FEED_SIZE]


def fetch(url: str, limit: int = FEED_SIZE) -> tuple[str, list[FeedItem]]:
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "playlistend": limit,
            "ignoreerrors": True, **downloader._net_opts()}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(feed_url(url), download=False)
    return parse_feed(info or {})


def new_ids(sub: Subscription, items: list[FeedItem]) -> set[str]:
    """Ids not shown before; a brand-new subscription has no 'new' (everything
    would be)."""
    if not sub.seen:
        return set()
    return {i.id for i in items} - set(sub.seen)


def mark_seen(sub: Subscription, items: list[FeedItem]) -> None:
    for i in items:
        if i.id not in sub.seen:
            sub.seen.append(i.id)
    del sub.seen[:-SEEN_LIMIT]
