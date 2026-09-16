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
        win._lang_combo.setCurrentIndex(1)  # 繁體中文
        assert win._lang == "zh"
        assert "\u6dfa\u8272" in win._theme_btn.text()  # 淺色
        assert "\u5916\u89c0" in win._settings_title.text()  # 外觀
        assert "\u8a18\u9304" in win._log_lbl.text()  # 記錄
        cfg = appmod._load_config()
        assert cfg["lang"] == "zh"
        assert cfg["theme"] == "dark"
    finally:
        win.close()