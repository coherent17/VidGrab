"""Headless smoke test that constructs the real PySide6 UI.

Runs only when SMOKE_GUI=1 (e.g. QT_QPA_PLATFORM=offscreen).
Catches PySide6 API misuse and layout errors that a plain import misses.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SMOKE_GUI") != "1",
    reason="set SMOKE_GUI=1 to enable",
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_window_constructs_and_destroys(qapp, monkeypatch) -> None:
    monkeypatch.setattr(
        "vidgrab.app.check_internet",
        lambda timeout=2.5: type("S", (), {"online": True, "reason": "mock"})(),
    )
    from vidgrab.app import VidGrabWindow

    win = VidGrabWindow()
    try:
        assert win.windowTitle() == "VidGrab"
        assert win._stack.count() == 3
        assert win._stack.currentIndex() == 0
        # navigate to Edit page and back
        win._switch_page(1)
        assert win._stack.currentIndex() == 1
        assert win._action.text().startswith(
            "\u2702"
        ) or win._action.text().startswith("Process")
        win._switch_page(0)
        assert win._stack.currentIndex() == 0
    finally:
        win.close()


def test_theme_toggle(qapp, tmp_path, monkeypatch) -> None:
    from vidgrab import app as appmod

    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    appmod._save_config("dark")
    win = appmod.VidGrabWindow()
    try:
        assert win._theme == "dark"
        win._toggle_theme()
        assert win._theme == "light"
        assert appmod._load_config()["theme"] == "light"
        win._toggle_theme()
        assert win._theme == "dark"
    finally:
        win.close()


def test_lang_toggle(qapp, tmp_path, monkeypatch) -> None:
    from vidgrab import app as appmod

    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    appmod._save_config("dark", "en")
    win = appmod.VidGrabWindow()
    try:
        assert win._lang == "en"
        assert win._theme_btn.text() in ("\u2600 Light", "\u2600 \u6dfa\u8272")
        win._lang_combo.setCurrentIndex(win._lang_combo.findData("zh"))  # 繁體中文
        assert win._lang == "zh"
        assert "\u6dfa\u8272" in win._theme_btn.text()  # 淺色
        assert "\u5916\u89c0" in win._settings_title.text()  # 外觀
        assert "\u8a18\u9304" in win._log_title.text()  # 記錄
        cfg = appmod._load_config()
        assert cfg["lang"] == "zh"
        assert cfg["theme"] == "dark"
    finally:
        win.close()


def test_lang_toggle_ja_ko(qapp, tmp_path, monkeypatch) -> None:
    from vidgrab import app as appmod

    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    appmod._save_config("dark", "en")
    win = appmod.VidGrabWindow()
    try:
        win._lang_combo.setCurrentIndex(win._lang_combo.findData("ja"))
        assert win._lang == "ja"
        assert "\u30ed\u30b0" in win._log_title.text()  # 記錄 -> ログ
        win._lang_combo.setCurrentIndex(win._lang_combo.findData("ko"))
        assert win._lang == "ko"
        assert "\ub85c\uadf8" in win._log_title.text()  # 記錄 -> 로그
        cfg = appmod._load_config()
        assert cfg["lang"] == "ko"
    finally:
        win.close()


def test_edit_page_inline_preview(qapp, monkeypatch) -> None:
    """The Edit page shows an in-window player with a scrubber when multimedia is present."""
    from vidgrab import app as appmod

    monkeypatch.setattr(
        "vidgrab.app.check_internet",
        lambda timeout=2.5: type("S", (), {"online": True, "reason": "mock"})(),
    )
    win = appmod.VidGrabWindow()
    try:
        win._switch_page(1)
        if appmod._QT_MULTIMEDIA_OK:
            assert win._ed_preview_title is not None
            assert bool(win._ed_preview_title.text())
            assert win._ed_player is not None
            assert win._ed_video_lbl is not None
            assert win._ed_sink is not None
            assert win._ed_play_btn is not None and not win._ed_play_btn.isEnabled()
            assert win._ed_seek is not None and not win._ed_seek.isEnabled()
            assert win._ed_time_lbl is not None
        else:
            assert win._ed_player is None
    finally:
        win.close()


def test_bundled_fonts_register(qapp) -> None:
    from pathlib import Path

    from PySide6.QtGui import QFontDatabase

    from vidgrab import app as appmod

    appmod._register_bundled_fonts()
    families = set(QFontDatabase.families())
    for name in ("Noto Sans CJK TC", "Noto Sans CJK JP", "Noto Sans CJK KR"):
        assert name in families, f"bundled font not registered: {name}"

    assets = Path(appmod.__file__).resolve().parent.parent / "assets"
    for fname in ("NotoSansTC-Regular.otf", "NotoSansJP-Regular.otf", "NotoSansKR-Regular.otf"):
        assert (assets / fname).is_file(), f"font asset missing: {fname}"