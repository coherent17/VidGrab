from __future__ import annotations

import builtins
import struct
import zlib
from pathlib import Path

from vidgrab.icon import generate


def _png_pixels(path: Path) -> tuple[int, int, list[bytes]]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", data[16:24])
    size = struct.unpack(">I", data[33:37])[0]
    raw = zlib.decompress(data[41:41 + size])
    rows = [raw[y * (w * 4 + 1) + 1:(y + 1) * (w * 4 + 1)] for y in range(h)]
    return w, h, rows


def test_generate_writes_png_and_ico(tmp_path: Path) -> None:
    out = generate(tmp_path)
    assert out["png"].is_file()
    assert out["ico"].is_file()

    w, h, rows = _png_pixels(out["png"])
    assert (w, h) == (256, 256)

    def alpha(x: int, y: int) -> int:
        return rows[y][x * 4 + 3]

    assert alpha(2, 2) <= 2        # outside the rounded tile: transparent
    assert alpha(128, 128) >= 250  # tile interior: opaque


def test_ico_holds_all_sizes(tmp_path: Path) -> None:
    out = generate(tmp_path)
    ico = out["ico"].read_bytes()
    reserved, kind, count = struct.unpack("<HHH", ico[:6])
    assert (reserved, kind) == (0, 1)
    assert count == 6
    seen: set[int] = set()
    for i in range(count):
        rec = ico[6 + i * 16:6 + (i + 1) * 16]
        w = rec[0]
        plane, bpp = struct.unpack("<HH", rec[4:8])
        length = struct.unpack("<I", rec[8:12])[0]
        assert (plane, bpp) == (1, 32)
        assert length > 0
        seen.add(w if w else 256)
    assert seen == {16, 32, 48, 64, 128, 256}


def test_generation_without_qt(tmp_path: Path, monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.split(".")[0] == "PySide6":
            raise ImportError("simulated missing Qt")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = generate(tmp_path)  # must not raise: falls back to glyph-only
    assert out["png"].is_file()
    assert out["ico"].is_file()