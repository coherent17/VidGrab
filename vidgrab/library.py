"""Qt-free Library: the media files in the output folder, newest first."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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


def filter_entries(entries: list[Entry], kind: str = "all", query: str = "") -> list[Entry]:
    words = query.lower().split()
    return [e for e in entries
            if (kind == "all" or e.kind == kind) and all(w in e.name.lower() for w in words)]
