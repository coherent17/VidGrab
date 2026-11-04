"""UI fonts."""
from __future__ import annotations

import os
import shutil
import sys

from vidgrab.core.downloader import (
    asset_roots,
)

# Fallback font chain used everywhere (QSS + app font). Noto Sans CJK TC
# (bundled) covers Traditional Chinese; it is pulled to the front for zh so
# glyphs render in their Traditional regional form.
# the fonts offered in Settings -> Appearance: key -> family (all bundled in assets/, four
# weights each). "system" (not in the table) leaves the computer's own UI font first.
UI_FONTS: dict[str, str] = {
    "jakarta": "Plus Jakarta Sans",
    "inter": "Inter",
    "poppins": "Poppins",
    "manrope": "Manrope",
    "dmsans": "DM Sans",
    "nunito": "Nunito Sans",
}


DEFAULT_UI_FONT = "jakarta"


_FONT_FILES = {"jakarta": "PlusJakartaSans", "inter": "Inter", "poppins": "Poppins",
               "manrope": "Manrope", "dmsans": "DMSans", "nunito": "NunitoSans"}


_FONT_FALLBACK = (
    "Segoe UI", "Noto Sans",
    "Noto Sans CJK TC", "Noto Sans TC", "Source Han Sans TC",
    "PingFang TC", "Microsoft JhengHei", "WenQuanYi Zen Hei",
    "Droid Sans Fallback", "Ubuntu", "Cantarell", "sans-serif",
)


# Latin letters and digits come from Inter in every language (a CJK font draws them
# plainly); Chinese characters fall through the chain to the CJK fonts below it.
_LANG_FONT_PREF: dict[str, str] = {}


def _font_families(lang: str = "en", font: str = DEFAULT_UI_FONT) -> list[str]:
    """The font chain: the chosen font first (Latin letters and digits; with *font*
    "system" the computer's own UI font leads), then the fallbacks, among them the
    CJK fonts that draw Chinese; *lang* may name a CJK font to lead with."""
    fams = list(_FONT_FALLBACK)
    if font in UI_FONTS:
        fams.insert(0, UI_FONTS[font])
    pref = _LANG_FONT_PREF.get(lang)
    if pref in fams:
        fams.remove(pref)
        fams.insert(0, pref)
    return fams


def _font_chain(lang: str, font: str = DEFAULT_UI_FONT) -> str:
    """Return the QSS `font-family` list."""
    return ", ".join(f'"{f}"' for f in _font_families(lang, font))


_APP_FONT_FAMILIES = list(_FONT_FALLBACK)


_BUNDLED_FONTS = (
    *(f"{stem}-{weight}.ttf" for stem in _FONT_FILES.values()
      for weight in ("Regular", "Medium", "SemiBold", "Bold")),
    "NotoSansTC-Regular.otf",
    "NotoSansCJKtc-Regular.otf",
    "SourceHanSansTC-Regular.otf",
)


def _register_bundled_fonts() -> None:
    """Load the bundled CJK font (if shipped next to the app) so zh renders.

    Safe no-op when no bundled font is present; Qt still falls back to any
    system CJK font like Noto Sans CJK TC or Microsoft JhengHei.
    """
    from PySide6.QtGui import QFontDatabase

    checked: set[str] = set()
    for root in reversed(asset_roots()):
        for fname in _BUNDLED_FONTS:
            p = root / "assets" / fname
            if str(p) in checked:
                continue
            checked.add(str(p))
            if p.is_file():
                try:
                    QFontDatabase.addApplicationFont(str(p))
                except Exception:  # noqa: BLE001, S110 - best effort
                    pass


def _enable_input_method() -> None:
    """Use ibus for CJK typing when it's installed and nothing else is set.

    PySide6 ships Qt's ibus plugin; Linux apps under WSL never see the Windows
    IME, so ibus (or fcitx) inside Linux is the only way to type Chinese."""
    if not sys.platform.startswith("linux"):
        return
    if os.environ.get("QT_IM_MODULE") or os.environ.get("QT_IM_MODULES"):
        return
    if shutil.which("ibus-daemon"):
        os.environ["QT_IM_MODULE"] = "ibus"
