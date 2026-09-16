"""Generate assets/icon.ico and assets/icon.png using only the Python standard library.

Uses 4x supersampling with box-filter down-sampling for anti-aliased edges.
Design: accent-blue rounded rectangle with a white play triangle and
a small download arrow (visible at 64 px and larger).
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)

_BG = (0x4F, 0x7C, 0xFF)   # accent blue #4f7cff
_FG = (255, 255, 255)       # white
SS = 4                      # super-sample factor


# ── shape helpers (high-res pixel coords) ────────────────────────────────

def _in_rounded_rect(cx, cy, rx, ry, cr, px, py):
    dx, dy = abs(px - cx), abs(py - cy)
    if dx > rx or dy > ry:
        return False
    if dx <= rx - cr or dy <= ry - cr:
        return True
    cdx, cdy = dx - (rx - cr), dy - (ry - cr)
    return cdx * cdx + cdy * cdy <= cr * cr


def _in_triangle(ax, ay, bx, by, cx, cy, px, py):
    v0x, v0y = bx - ax, by - ay
    v1x, v1y = cx - ax, cy - ay
    v2x, v2y = px - ax, py - ay
    d00 = v0x * v0x + v0y * v0y
    d01 = v0x * v1x + v0y * v1y
    d02 = v0x * v2x + v0y * v2y
    d11 = v1x * v1x + v1y * v1y
    d12 = v1x * v2x + v1y * v2y
    inv = 1.0 / (d00 * d11 - d01 * d01 + 1e-15)
    u = (d11 * d02 - d01 * d12) * inv
    v = (d00 * d12 - d01 * d02) * inv
    return u >= 0 and v >= 0 and u + v <= 1.0


def _in_arrow(cx, cy, s, px, py):
    bw, bh = s * 0.38, s * 1.0
    if abs(px - cx) <= bw and abs(py - cy) <= bh:
        return True
    hw, hh = s * 0.86, s * 0.32
    bar_cy = cy - bh * 0.38
    if abs(px - cx) <= hw and abs(py - bar_cy) <= hh:
        return True
    tip_top = bar_cy + hh
    tip_bot = cy + bh * 1.18
    if tip_top < py <= tip_bot:
        t = (py - tip_top) / (tip_bot - tip_top)
        if abs(px - cx) <= s * 0.55 * (1.0 - t):
            return True
    return False


# ── renderer ─────────────────────────────────────────────────────────────

def _draw(size: int) -> bytes:
    big = size * SS
    buf = bytearray(big * big * 4)
    m = big * 0.03
    rx = ry = big / 2 - m
    crx = big * 0.22
    cx = cy = big / 2

    ps = big * 0.26
    tri = [
        (cx - ps * 0.68, cy - ps * 1.05),
        (cx - ps * 0.68, cy + ps * 1.05),
        (cx + ps * 0.90, cy),
    ]

    show_arrow = size >= 64
    as_ = big * 0.058
    acx, acy = cx + rx * 0.52, cy + ry * 0.50

    for y in range(big):
        for x in range(big):
            i = (y * big + x) << 2
            px, py = x + 0.5, y + 0.5
            if not _in_rounded_rect(cx, cy, rx, ry, crx, px, py):
                continue
            r, g, b = _BG
            if _in_triangle(*tri[0], *tri[1], *tri[2], px, py) or show_arrow and _in_arrow(acx, acy, as_, px, py):
                r, g, b = _FG
            buf[i] = r
            buf[i + 1] = g
            buf[i + 2] = b
            buf[i + 3] = 255

    # box-filter down-sample
    out = bytearray(size * size * 4)
    for oy in range(size):
        for ox in range(size):
            oi = (oy * size + ox) << 2
            r = g = b = a = 0
            sy = oy * SS
            sx = ox * SS
            for dy in range(SS):
                for dx in range(SS):
                    ii = ((sy + dy) * big + (sx + dx)) << 2
                    r += buf[ii]
                    g += buf[ii + 1]
                    b += buf[ii + 2]
                    a += buf[ii + 3]
            n = SS * SS
            out[oi] = r // n
            out[oi + 1] = g // n
            out[oi + 2] = b // n
            out[oi + 3] = a // n
    return bytes(out)


# ── PNG helpers ──────────────────────────────────────────────────────────

def _png_chunk(tag: bytes, data: bytes) -> bytes:
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def _make_png(size: int, pixels: bytes) -> bytes:
    raw = b"".join(b"\x00" + pixels[y * size * 4:(y + 1) * size * 4] for y in range(size))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )


# ── ICO writer ───────────────────────────────────────────────────────────

def _write_ico(path: Path, sizes: list[int]) -> None:
    images = [(sz, _make_png(sz, _draw(sz))) for sz in sizes]
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries = b""
    blobs = b""
    for sz, png in images:
        es = 0 if sz >= 256 else sz
        entries += struct.pack("<BBBBHHII", es, es, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    path.write_bytes(header + entries + blobs)


# ── main ─────────────────────────────────────────────────────────────────

def main() -> None:
    ico_sizes = [16, 32, 48, 64, 128, 256]

    ico_path = ASSETS / "icon.ico"
    png_path = ASSETS / "icon.png"

    _write_ico(ico_path, ico_sizes)
    png_path.write_bytes(_make_png(256, _draw(256)))

    print(f"Wrote {ico_path}  ({len(ico_sizes)} sizes)")
    print(f"Wrote {png_path}  (256x256)")


if __name__ == "__main__":
    main()
