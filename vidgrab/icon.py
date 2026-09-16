"""Brand icon generator for VidGrab - futuristic / cyber edition.

Pure standard library: signed-distance-field rendering with analytic
anti-aliasing (no supersampling), plus PNG and ICO (PNG-in-ICO) writers.

The "VidGrab" wordmark is rasterized with PySide6 when Qt is available
(the running app, the build env in CI, and `make build` all have it); the
remainder of the design is drawn even without Qt, so the generator can
never hard-fail.

Design (per 256 px tile): a chamfered "chip" tile filled with an electric
4-way gradient (blue -> cyan -> violet -> magenta), a cyan neon outline
with a soft outer glow, a white play triangle with a cyan neon rim + halo,
a glowing download chevron (>= 64 px), and a bold "VidGrab" wordmark
bathed in a cyan glow (sizes >= 48 px). Small sizes keep the triangle
only, centered.
"""

from __future__ import annotations

import math
import os
import struct
import zlib
from collections.abc import Callable
from pathlib import Path

# electric 4-corner gradient: TL blue, TR cyan, BL violet, BR magenta
_TL = (80, 130, 255)     # #5082ff
_TR = (56, 224, 230)     # #38e0e6
_BL = (124, 58, 237)     # #7c3aed
_BR = (240, 72, 168)     # #f048a8
_NEON = (185, 250, 255)  # bright cyan for outlines, glows and accents

_TEXT_THRESHOLD = 48      # sizes below this drop the wordmark
_TEXT_WIDTH = 0.86        # wordmark box width, fraction of tile
_TEXT_TOP = 0.495
_TEXT_BOT = 0.850

_TRI_BACK = 0.115         # triangle back-edge offset from tile center x
_TRI_HALFH = 0.091        # triangle back-edge half-height
_TRI_TIP = 0.130          # triangle tip forward offset
_TRI_CY = 0.335           # triangle vertical center

_TRI_CY_SMALL = 0.50      # centered triangle (no wordmark)
_TRI_BACK_SMALL = 0.155
_TRI_HALFH_SMALL = 0.145
_TRI_TIP_SMALL = 0.185

_CHEV_MIN = 64            # sizes below this drop the download chevron
_CHEV_Y = 0.478           # chevron vertical center


# ── signed distance fields ────────────────────────────────────────────────

def _sd_chamfer(px: float, py: float, cx: float, cy: float, h: float, cut: float) -> float:
    """Signed distance to a square whose four corners are chamfered (cut)."""
    dx, dy = math.fabs(px - cx), math.fabs(py - cy)
    sq = max(dx, dy) - h
    l1 = dx + dy - (h + cut)
    return max(sq, l1)


def _sd_seg(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    ddx, ddy = bx - ax, by - ay
    h2 = ddx * ddx + ddy * ddy
    if h2 == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * ddx + (py - ay) * ddy) / h2
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * ddx), py - (ay + t * ddy))


def _sd_capsule(px, py, ax, ay, bx, by, w) -> float:
    return _sd_seg(px, py, ax, ay, bx, by) - w


def _cross(ox: float, oy: float, ax: float, ay: float, bx: float, by: float) -> float:
    return (ax - ox) * (by - oy) - (ay - oy) * (bx - ox)


def _inside_tri(px: float, py: float, a: tuple, b: tuple, c: tuple) -> bool:
    d1 = _cross(px, py, a[0], a[1], b[0], b[1])
    d2 = _cross(px, py, b[0], b[1], c[0], c[1])
    d3 = _cross(px, py, c[0], c[1], a[0], a[1])
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def _sd_tri(px: float, py: float, a: tuple, b: tuple, c: tuple) -> float:
    d = min(
        _sd_seg(px, py, a[0], a[1], b[0], b[1]),
        _sd_seg(px, py, b[0], b[1], c[0], c[1]),
        _sd_seg(px, py, c[0], c[1], a[0], a[1]),
    )
    return -d if _inside_tri(px, py, a, b, c) else d


def _cov(sd: float) -> float:
    c = 0.5 - sd
    return 0.0 if c <= 0.0 else min(1.0, c)


def _ellipse_falloff(px, py, cx, cy, rx, ry) -> float:
    gx = (px - cx) / rx
    gy = (py - cy) / ry
    d = math.hypot(gx, gy)
    return max(0.0, 1.0 - d) ** 2


def _bilerp(u: float, v: float) -> tuple[float, float, float]:
    top = (x0 + (x1 - x0) * u for x0, x1 in zip(_TL, _TR))
    bot = (x0 + (x1 - x0) * u for x0, x1 in zip(_BL, _BR))
    return tuple(a + (b - a) * v for a, b in zip(top, bot))


# ── wordmark (Qt) ─────────────────────────────────────────────────────────

def _text_mask(target_w: int, target_h: int, text: str) -> Callable[[int, int], float] | None:
    """Render `text` and return an alpha sampler over target_w x target_h.

    Returns None when Qt is unavailable, so callers keep a glyph-only icon.
    """
    try:  # PySide6 is present in the app and in every build environment
        from PySide6.QtGui import (  # type: ignore
            QColor,
            QFont,
            QFontDatabase,
            QFontMetrics,
            QGuiApplication,
            QImage,
            QPainter,
        )
    except Exception:  # noqa: BLE001 - Qt optional; fall back to glyph-only
        return None

    app = QGuiApplication.instance()
    created = app is None
    if created:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QGuiApplication(["vidgrab-icon"])

    ss = 3  # text supersample, then box average
    iw, ih = target_w * ss, target_h * ss

    families = QFontDatabase.families()
    chosen = "sans-serif"
    for pref in ("Montserrat", "Poppins", "Segoe UI", "DejaVu Sans",
                 "Liberation Sans", "Noto Sans", "Arial"):
        if pref in families:
            chosen = pref
            break

    font = QFont(chosen)
    font.setWeight(QFont.Weight.ExtraBold)
    pt = round(iw * 96.0 / 400.0)  # aim big; fit-by-width shrinks if needed
    font.setPointSizeF(max(4.0, pt))

    img = QImage(iw, ih, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor(255, 255, 255, 255))

    fm = QFontMetrics(font)
    adv = fm.horizontalAdvance(text)
    if adv > iw - 14 and adv > 0:  # fit by width: shrink the em proportionally
        shrink = (iw - 14) / adv
        font.setPointSizeF(max(4.0, font.pointSizeF() * shrink))
        fm = QFontMetrics(font)
        adv = fm.horizontalAdvance(text)

    p.setFont(font)
    ascent, descent = fm.ascent(), fm.descent()
    tx = max(0, (iw - adv) // 2)
    ty = (ih - (ascent + descent)) // 2 + ascent
    p.drawText(tx, ty, text)
    p.end()
    if created:
        app.processEvents()

    blur = img.bits()
    if not blur or img.bytesPerLine() != iw * 4:
        return None

    alphas: list[bytes] = []
    for oy in range(target_h):
        row = b""
        for ox in range(target_w):
            acc = 0.0
            base = (oy * ss) * iw * 4 + (ox * ss) * 4
            for dy in range(ss):
                idx = base + dy * iw * 4
                for dx in range(ss):
                    acc += blur[idx + dx * 4 + 3]
            row += bytes((round(acc / (ss * ss)),))
        alphas.append(row)

    def sampler(x: int, y: int) -> float:
        if 0 <= y < target_h and 0 <= x < target_w:
            return alphas[y][x] / 255.0
        return 0.0

    return sampler


# ── renderer ──────────────────────────────────────────────────────────────

def _tri_sd(px: float, py: float, m: float, small: bool) -> float:
    """Signed distance to the (balloon-rounded) play triangle."""
    if small:
        cx = cy = m / 2
        a = (cx - _TRI_BACK_SMALL * m, cy - _TRI_HALFH_SMALL * m)
        b = (cx - _TRI_BACK_SMALL * m, cy + _TRI_HALFH_SMALL * m)
        c = (cx + _TRI_TIP_SMALL * m, cy)
    else:
        cx, cy = m / 2, _TRI_CY * m
        a = (cx - _TRI_BACK * m, cy - _TRI_HALFH * m)
        b = (cx - _TRI_BACK * m, cy + _TRI_HALFH * m)
        c = (cx + _TRI_TIP * m, cy)
    return _sd_tri(px, py, a, b, c) - m * 0.014  # sleek, slightly-rounded edge


def _chevron_sd(px: float, py: float, m: float) -> float:
    """Signed distance to a small downward chevron (download accent)."""
    cx = m / 2
    cy = _CHEV_Y * m
    w = m * 0.014
    stem = _sd_capsule(px, py, cx, cy - 0.030 * m, cx, cy + 0.008 * m, w)
    left = _sd_capsule(px, py, cx - 0.030 * m, cy, cx, cy + 0.038 * m, w)
    right = _sd_capsule(px, py, cx + 0.030 * m, cy, cx, cy + 0.038 * m, w)
    return min(stem, left, right)


def _render(size: int) -> tuple[bytes, Callable | None]:
    m = float(size)
    cx = cy = m / 2
    h = m / 2 - m * 0.012          # chamfer-square half-size (outer)
    cut = h * 0.32                 # shallow 45-degree corner chamfer
    halo = m * 0.030               # outer glow reach

    small = size < _TEXT_THRESHOLD
    text = None
    if not small:
        tw = max(1, round(_TEXT_WIDTH * m))
        th = max(1, round((_TEXT_BOT - _TEXT_TOP) * m))
        text = _text_mask(tw, th, "VidGrab")

    tx0 = (0.5 - _TEXT_WIDTH / 2) * m
    ty0 = _TEXT_TOP * m
    text_cy = ((_TEXT_TOP + _TEXT_BOT) / 2) * m

    out = bytearray(size * size * 4)
    for y in range(size):
        py = y + 0.5
        iy = y * size
        for x in range(size):
            px = x + 0.5
            i = iy + x
            o = i << 2

            sd = _sd_chamfer(px, py, cx, cy, h, cut)
            co = _cov(sd)

            oglow = 0.0
            if co <= 0.0:
                if sd < halo:
                    oglow = (1.0 - sd / halo) ** 2 * 0.55
                else:
                    continue

            if co > 0.0:
                # electric gradient + UV
                u = max(0.0, min(1.0, (px - (cx - h)) / (2.0 * h)))
                v = max(0.0, min(1.0, (py - (cy - h)) / (2.0 * h)))
                r, g, b = _bilerp(u, v)

                # glass sheen (upper-left radial)
                gl = _ellipse_falloff(px, py, 0.16 * m, 0.12 * m, 0.66 * m, 0.66 * m) * 0.18
                r += (255.0 - r) * gl
                g += (255.0 - g) * gl
                b += (255.0 - b) * gl

                # cyan neon outline along the tile edge
                ring = _cov(math.fabs(sd) - 2.0)
                if ring > 0.0:
                    r += (_NEON[0] - r) * ring * 0.62
                    g += (_NEON[1] - g) * ring * 0.62
                    b += (_NEON[2] - b) * ring * 0.62

                # play triangle: cyan halo + white fill + neon rim
                tsd = _tri_sd(px, py, m, small)
                gmax = m * 0.035
                if 0.0 < tsd < gmax:
                    halo_a = (1.0 - tsd / gmax) ** 2 * 0.28
                    r = min(255.0, r + _NEON[0] * halo_a)
                    g = min(255.0, g + _NEON[1] * halo_a)
                    b = min(255.0, b + _NEON[2] * halo_a)
                tco = _cov(tsd)
                if tco > 0.0:
                    r += (255.0 - r) * tco
                    g += (255.0 - g) * tco
                    b += (255.0 - b) * tco
                trim = _cov(math.fabs(tsd) - 2.0) * 0.42
                if trim > 0.0:
                    r = min(255.0, r + _NEON[0] * trim)
                    g = min(255.0, g + _NEON[1] * trim)
                    b = min(255.0, b + _NEON[2] * trim)

                # glowing download chevron
                if size >= _CHEV_MIN:
                    cc = _cov(_chevron_sd(px, py, m))
                    if cc > 0.0:
                        r = min(255.0, r + _NEON[0] * cc * 0.9)
                        g = min(255.0, g + _NEON[1] * cc * 0.9)
                        b = min(255.0, b + _NEON[2] * cc * 0.9)

                # wordmark: cyan backlight + white glyphs
                if text is not None:
                    tg = _ellipse_falloff(px, py, cx, text_cy, 0.44 * m, 0.165 * m) * 0.13
                    if tg > 0.0:
                        r = min(255.0, r + _NEON[0] * tg)
                        g = min(255.0, g + _NEON[1] * tg)
                        b = min(255.0, b + _NEON[2] * tg)
                    alpha = text(int(px - tx0), int(py - ty0))
                    if alpha > 0.0:
                        r += (255.0 - r) * alpha
                        g += (255.0 - g) * alpha
                        b += (255.0 - b) * alpha
            else:
                r = g = b = float(_NEON[0])  # pure outer glow region

            A = min(1.0, co + oglow)
            if A <= 0.0:
                continue
            share = co / A if A > 0.0 else 0.0
            cr = r * share + _NEON[0] * (1.0 - share)
            cg = g * share + _NEON[1] * (1.0 - share)
            cb = b * share + _NEON[2] * (1.0 - share)

            out[o] = max(0, min(255, round(cr)))
            out[o + 1] = max(0, min(255, round(cg)))
            out[o + 2] = max(0, min(255, round(cb)))
            out[o + 3] = round(A * 255.0)

    return bytes(out), text


# ── PNG / ICO writers ─────────────────────────────────────────────────────

def _png_chunk(tag: bytes, data: bytes) -> bytes:
    body = tag + data
    return (
        struct.pack(">I", len(data))
        + body
        + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    )


def _make_png(size: int, pixels: bytes) -> bytes:
    raw = b"".join(b"\x00" + pixels[y * size * 4:(y + 1) * size * 4] for y in range(size))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )


def _write_ico(path: Path, sizes: list[int]) -> None:
    images = [(sz, _make_png(sz, _render(sz)[0])) for sz in sizes]
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


# ── public API ────────────────────────────────────────────────────────────

def generate(output_dir: Path) -> dict[str, Path]:
    """Write icon.ico (16/32/48/64/128/256) and icon.png (256) into output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ico = output_dir / "icon.ico"
    png = output_dir / "icon.png"
    _write_ico(ico, [16, 32, 48, 64, 128, 256])
    png.write_bytes(_make_png(256, _render(256)[0]))
    return {"ico": ico, "png": png}