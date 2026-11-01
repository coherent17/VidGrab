"""The parallel one-file archive writer for the PyInstaller build."""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

import pytest

pytest.importorskip("PyInstaller")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pyi_parallel_pkg
from PyInstaller.archive.writers import CArchiveWriter


def _entries(tmp_path: Path) -> list[tuple]:
    rng = random.Random(7)
    out = []
    for i in range(24):
        path = tmp_path / f"lib{i}.so"
        # a mix of compressible and incompressible files, big and small
        chunk = (b"abcdefgh" * 512) if i % 3 else rng.randbytes(4096)
        path.write_bytes(chunk * rng.choice([1, 40, 300]))
        out.append((f"lib/lib{i}.so", str(path), i % 5 != 0, "b"))  # every fifth is stored
    out.append(("data.txt", str(tmp_path / "lib1.so"), True, "x"))  # the same file twice
    out.append(("pyi-option", "", False, "o"))
    return out


def test_the_parallel_archive_is_identical_to_the_normal_one(tmp_path):
    entries = _entries(tmp_path)
    normal, parallel = tmp_path / "normal.pkg", tmp_path / "parallel.pkg"
    CArchiveWriter(str(normal), entries, "libpython3.12.so")
    pyi_parallel_pkg.make_writer(CArchiveWriter)(str(parallel), entries, "libpython3.12.so")
    assert normal.stat().st_size == parallel.stat().st_size
    assert normal.read_bytes() == parallel.read_bytes()


def test_a_file_that_cannot_be_read_ahead_still_ends_up_in_the_archive(tmp_path, monkeypatch):
    entries = _entries(tmp_path)
    writer = pyi_parallel_pkg.make_writer(CArchiveWriter)
    monkeypatch.setattr(writer, "_deflate", classmethod(lambda cls, src: 1 / 0))  # every worker fails
    normal, fallback = tmp_path / "normal.pkg", tmp_path / "fallback.pkg"
    CArchiveWriter(str(normal), entries, "libpython3.12.so")
    writer(str(fallback), entries, "libpython3.12.so")
    assert normal.read_bytes() == fallback.read_bytes()


def test_one_cpu_means_no_threads(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 1)
    monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: {0}, raising=False)
    entries = _entries(tmp_path)
    normal, single = tmp_path / "normal.pkg", tmp_path / "single.pkg"
    CArchiveWriter(str(normal), entries, "libpython3.12.so")
    pyi_parallel_pkg.make_writer(CArchiveWriter)(str(single), entries, "libpython3.12.so")
    assert normal.read_bytes() == single.read_bytes()
