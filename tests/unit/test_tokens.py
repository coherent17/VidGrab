"""The stylesheet's font sizes come from the type scale."""
from __future__ import annotations

import re
from pathlib import Path

from vidgrab.ui import tokens

THEME = Path(__file__).resolve().parents[2] / "vidgrab" / "ui" / "theme.py"


def test_every_font_size_in_the_stylesheet_is_on_the_type_scale() -> None:
    sizes = {int(n) for n in re.findall(r"font-size:\s*(\d+)px", THEME.read_text("utf-8"))}
    assert sizes <= set(tokens.TYPE_SCALE), sorted(sizes - set(tokens.TYPE_SCALE))


def test_the_pages_share_one_margin() -> None:
    ui = Path(__file__).resolve().parents[2] / "vidgrab" / "ui"
    assert tokens.PAGE_MARGINS == (24, 12, 24, 12)
    for name in ("library_page.py", "tools_page.py", "subscriptions_page.py", "help_page.py"):
        assert "setContentsMargins(*PAGE_MARGINS)" in (ui / name).read_text("utf-8"), name
