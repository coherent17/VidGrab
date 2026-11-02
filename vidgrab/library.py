"""Qt-free Library: the media files in the output folder, newest first."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from vidgrab.fuzzy import FuzzyIndex

VIDEO = {".mp4", ".mkv", ".webm", ".mov", ".avi"}
AUDIO = {".mp3", ".m4a", ".opus", ".wav", ".flac", ".ogg", ".aac"}
IMAGE = {".gif", ".png", ".jpg", ".jpeg"}
KINDS = ("all", "video", "audio", "image")
MAX_DEPTH = 2  # the folder and one level of sub-folders (playlists)
MAX_FILES = 2000


@dataclass(frozen=True)
class Entry:
    path: str
    name: str
    kind: str  # video | audio | image
    size: int
    mtime: float


def kind_of(path: str | Path) -> str | None:
    ext = Path(path).suffix.lower()
    return "video" if ext in VIDEO else "audio" if ext in AUDIO else "image" if ext in IMAGE else None


def scan(folder: str | Path) -> list[Entry]:
    """Media files in *folder* (and one level of sub-folders), newest first. Half-written
    files (`.part`, `.ytdl`, the temp suffixes) are left out by their extension."""
    root = Path(folder)
    out: list[Entry] = []
    if not root.is_dir():
        return out
    base = len(root.parts)
    for dirpath, dirs, files in os.walk(root):
        if len(Path(dirpath).parts) - base >= MAX_DEPTH - 1:
            dirs[:] = []
        for f in files:
            kind = kind_of(f)
            if not kind:
                continue
            p = Path(dirpath) / f
            try:
                st = p.stat()
            except OSError:
                continue
            out.append(Entry(str(p), p.stem, kind, st.st_size, st.st_mtime))
            if len(out) >= MAX_FILES:
                break
    out.sort(key=lambda e: e.mtime, reverse=True)
    return out


class Finder:
    """Fuzzy search over a scan: typos, half-typed words and Chinese file names
    find files; with a query the best match comes first, without one the order
    stays newest first."""

    def __init__(self, entries: list[Entry]) -> None:
        self.entries = entries
        self._by_path = {e.path: e for e in entries}
        self.index = FuzzyIndex()
        for e in entries:
            self.index.add(e.path, e.name, (e.name, 1.0))

    def filter(self, kind: str = "all", query: str = "") -> list[Entry]:
        if query.strip():
            found = [self._by_path[str(k)] for k, _s in self.index.search(query, limit=len(self.entries))]
        else:
            found = self.entries
        return [e for e in found if kind == "all" or e.kind == kind]

    def suggest(self, query: str, limit: int = 8) -> list[str]:
        return self.index.suggest(query, limit)

    def did_you_mean(self, query: str) -> str | None:
        return self.index.did_you_mean(query)


def filter_entries(entries: list[Entry], kind: str = "all", query: str = "") -> list[Entry]:
    return Finder(entries).filter(kind, query)
