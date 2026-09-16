"""Generate the VidGrab brand icon.

Reads the drawing logic from `vidgrab/icon.py` (single source of truth) and
writes:

  assets/icon.ico   16/32/48/64/128/256 PNG-in-ICO (Windows exe resource)
  assets/icon.png   256x256 RGBA
  docs/icon.png     same image, committed for the README preview

Runs Qt offscreen when available so the "VidGrab" wordmark is rendered with
real typography; falls back to the glyph-only design without Qt.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from vidgrab.icon import generate

    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    out = generate(assets)

    preview = ROOT / "docs" / "icon.png"
    preview.write_bytes(out["png"].read_bytes())

    print(f"Wrote {out['ico']}  (16/32/48/64/128/256)")
    print(f"Wrote {out['png']}  (256x256)")
    print(f"Wrote {preview}  (README preview)")


if __name__ == "__main__":
    main()