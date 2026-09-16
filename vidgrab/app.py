"""VidGrab — professional desktop media tool (PySide6 / Qt)."""

from __future__ import annotations

import json
import math
import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from vidgrab import __version__
from vidgrab.downloader import (
    default_output_dir,
    download,
    download_both,
    find_ffmpeg,
    get_app_dir,
    process_local_file,
)
from vidgrab.i18n import LANGUAGES, make_translator
from vidgrab.network import ConnectionStatus, check_internet

# ── palette ────────────────────────────────────────────────────────────────
#
# Brand: electric blue  #4f7cff
# Semantic: emerald success, amber warning, red error, violet/teal accents

DARK_QSS = """
* {
    font-family: "Segoe UI", "Noto Sans", "Ubuntu", "Cantarell", sans-serif;
}
QMainWindow {
    background-color: #0b0f14;
}

/* ── header ── */
QWidget#header {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0e1420, stop:1 #151c2c);
    border-bottom: 1px solid #1f2839;
}
QLabel#app_version {
    font-size: 12px;
    color: #7d8ba1;
    background: transparent;
}
QLabel#app_version b {
    color: #4f7cff;
}

/* ── sidebar ── */
QWidget#sidebar {
    background-color: #0d1219;
    border-right: 1px solid #1f2839;
}
QFrame#brand {
    background: transparent;
}
QLabel#brand_title {
    font-size: 20px;
    font-weight: bold;
    color: #e8edf6;
    background: transparent;
}
QLabel#brand_title span {
    color: #4f7cff;
}
QLabel#brand_sub {
    font-size: 11px;
    color: #5c6b84;
    background: transparent;
}
QFrame#brand_divider {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4f7cff, stop:1 transparent);
    border: none;
    max-height: 2px;
    min-height: 2px;
}
QPushButton#nav {
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0px;
    padding: 11px 18px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
    color: #6b7a94;
}
QPushButton#nav:hover {
    background-color: #141b28;
    color: #b6c2d6;
}
QPushButton#nav:hover:checked {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #141d30, stop:1 #1a2640);
    color: #e8edf6;
}
QPushButton#nav:checked {
    background-color: #111827;
    border-left: 3px solid #4f7cff;
    color: #e8edf6;
}

/* ── cards ── */
QGroupBox {
    background-color: #111827;
    border: 1px solid #1f2839;
    border-radius: 12px;
    margin-top: 16px;
    padding: 16px 14px 14px 14px;
    font-size: 12px;
    font-weight: 600;
    color: #8b93ab;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    top: -7px;
    background-color: #0b0f14;
    border-radius: 4px;
    padding: 1px 8px;
    letter-spacing: 1px;
}
QGroupBox#source_card::title   { color: #f43f5e; }
QGroupBox#format_card::title  { color: #10b981; }
QGroupBox#flip_card::title    { color: #06b6d4; }
QGroupBox#trim_card::title    { color: #8b5cf6; }
QGroupBox#save_card::title    { color: #4f7cff; }
QGroupBox#settings_card::title { color: #8b5cf6; }

/* ── inputs ── */
QLineEdit {
    background-color: #0d1219;
    border: 1px solid #1f2839;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #e8edf6;
    selection-background-color: #4f7cff;
}
QLineEdit:focus {
    border-color: #4f7cff;
}
QLineEdit#placeholder {
    color: #4b5672;
}

QComboBox {
    background-color: #0d1219;
    border: 1px solid #1f2839;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #e8edf6;
    min-width: 120px;
}
QComboBox:hover {
    border-color: #4f7cff;
}
QComboBox::drop-down {
    border: none;
    width: 28px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #7d8ba1;
    margin-right: 8px;
}
QComboBox QAbstractItemView {
    background-color: #111827;
    border: 1px solid #1f2839;
    color: #e8edf6;
    selection-background-color: #1a2744;
    border-radius: 6px;
    padding: 4px;
}

QCheckBox {
    color: #c9d1e0;
    font-size: 13px;
    spacing: 10px;
    padding: 2px 0;
    background: transparent;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #3a4560;
    border-radius: 5px;
    background: #0d1219;
}
QCheckBox::indicator:hover {
    border-color: #4f7cff;
}
QCheckBox::indicator:checked {
    image: url(@CHECK@);
    background-color: #4f7cff;
    border-color: #4f7cff;
}
QCheckBox:hover {
    color: #e8edf6;
}

/* ── buttons ── */
QPushButton#secondary {
    background-color: #161d2e;
    border: 1px solid #253050;
    border-radius: 8px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 500;
    color: #c9d1e0;
}
QPushButton#secondary:hover {
    background-color: #1c2540;
    border-color: #4f7cff;
    color: #ffffff;
}
QPushButton#secondary:pressed {
    background-color: #141c30;
}

QPushButton#primary {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4f7cff, stop:1 #6c5ce7);
    border: none;
    border-radius: 10px;
    padding: 14px 28px;
    font-size: 15px;
    font-weight: bold;
    color: #ffffff;
    letter-spacing: 0.5px;
}
QPushButton#primary:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #6389ff, stop:1 #7f70f0);
}
QPushButton#primary:pressed {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #3a60d0, stop:1 #5845c0);
}
QPushButton#primary:disabled {
    background-color: #1e2640;
    color: #4b5672;
}

QPushButton#theme_btn {
    background-color: #161d2e;
    border: 1px solid #253050;
    border-radius: 6px;
    padding: 5px 14px;
    font-size: 12px;
    font-weight: 500;
    color: #c9d1e0;
    min-width: 80px;
}
QPushButton#theme_btn:hover {
    background-color: #1c2540;
    border-color: #4f7cff;
    color: #ffffff;
}

/* ── status pills ── */
QLabel#section {
    font-size: 12px;
    font-weight: 600;
    color: #5c6b84;
    letter-spacing: 1px;
    background: transparent;
}
QLabel#status {
    font-size: 12px;
    font-weight: 500;
    color: #8b93ab;
    background: transparent;
}

/* ── log ── */
QTextEdit#log {
    background-color: #0d1219;
    border: 1px solid #1f2839;
    border-radius: 10px;
    padding: 10px;
    font-family: "Cascadia Code", "JetBrains Mono", "Fira Code", "Consolas", monospace;
    font-size: 11px;
    color: #7d8ba1;
    selection-background-color: #4f7cff;
}
QProgressBar {
    background-color: #111827;
    border: 1px solid #1f2839;
    border-radius: 6px;
    max-height: 12px;
    min-height: 12px;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4f7cff, stop:1 #7a5cf0);
    border-radius: 5px;
}
QTextEdit#log {
    background-color: #0d1219;
    border: 1px solid #1f2839;
    border-radius: 10px;
    padding: 10px;
    font-family: "Cascadia Code", "JetBrains Mono", "Fira Code", "Consolas", monospace;
    font-size: 11px;
    color: #7d8ba1;
    selection-background-color: #4f7cff;
}
QStatusBar {
    background-color: #0d1219;
    border-top: 1px solid #1f2839;
    font-size: 11px;
    color: #5c6b84;
    padding: 5px 12px;
}
QScrollBar:vertical {
    background: transparent;
    width: 9px;
}
QScrollBar::handle:vertical {
    background-color: #253050;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background-color: #3a4560;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0px;
}
QToolTip {
    background-color: #1c2540;
    border: 1px solid #253050;
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 11px;
    color: #c9d1e0;
}
"""

LIGHT_QSS = """
* {
    font-family: "Segoe UI", "Noto Sans", "Ubuntu", "Cantarell", sans-serif;
}
QMainWindow {
    background-color: #eef1f6;
}

/* ── header ── */
QWidget#header {
    background-color: #f8fafc;
    border-bottom: 1px solid #d9dfec;
}
QLabel#app_version {
    font-size: 12px;
    color: #64748b;
    background: transparent;
}
QLabel#app_version b {
    color: #4f7cff;
}

/* ── sidebar ── */
QWidget#sidebar {
    background-color: #e7ebf2;
    border-right: 1px solid #d3daea;
}
QFrame#brand {
    background: transparent;
}
QLabel#brand_title {
    font-size: 20px;
    font-weight: bold;
    color: #1e293b;
    background: transparent;
}
QLabel#brand_title span {
    color: #4f7cff;
}
QLabel#brand_sub {
    font-size: 11px;
    color: #94a3b8;
    background: transparent;
}
QFrame#brand_divider {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4f7cff, stop:1 transparent);
    border: none;
    max-height: 2px;
    min-height: 2px;
}
QPushButton#nav {
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0px;
    padding: 11px 18px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
    color: #64748b;
}
QPushButton#nav:hover {
    background-color: #dde3ee;
    color: #334155;
}
QPushButton#nav:hover:checked {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #dce3f2, stop:1 #d0daf0);
    color: #1e293b;
}
QPushButton#nav:checked {
    background-color: #dde4f2;
    border-left: 3px solid #4f7cff;
    color: #1e293b;
}

/* ── cards ── */
QGroupBox {
    background-color: #f8fafc;
    border: 1px solid #d3daea;
    border-radius: 12px;
    margin-top: 16px;
    padding: 16px 14px 14px 14px;
    font-size: 12px;
    font-weight: 600;
    color: #64748b;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    top: -7px;
    background-color: #eef1f6;
    border-radius: 4px;
    padding: 1px 8px;
    letter-spacing: 1px;
}
QGroupBox#source_card::title   { color: #e11d48; }
QGroupBox#format_card::title  { color: #059669; }
QGroupBox#flip_card::title    { color: #0891b2; }
QGroupBox#trim_card::title    { color: #7c3aed; }
QGroupBox#save_card::title    { color: #4f7cff; }
QGroupBox#settings_card::title { color: #7c3aed; }

/* ── inputs ── */
QLineEdit {
    background-color: #ffffff;
    border: 1px solid #d3daea;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #1e293b;
    selection-background-color: #4f7cff;
}
QLineEdit:focus {
    border-color: #4f7cff;
}

QComboBox {
    background-color: #ffffff;
    border: 1px solid #d3daea;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #1e293b;
    min-width: 120px;
}
QComboBox:hover {
    border-color: #4f7cff;
}
QComboBox::drop-down {
    border: none;
    width: 28px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #94a3b8;
    margin-right: 8px;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #d3daea;
    color: #1e293b;
    selection-background-color: #eef1f6;
    border-radius: 6px;
    padding: 4px;
}

QCheckBox {
    color: #334155;
    font-size: 13px;
    spacing: 10px;
    padding: 2px 0;
    background: transparent;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #b6c2d6;
    border-radius: 5px;
    background: #ffffff;
}
QCheckBox::indicator:hover {
    border-color: #4f7cff;
}
QCheckBox::indicator:checked {
    image: url(@CHECK@);
    background-color: #4f7cff;
    border-color: #4f7cff;
}
QCheckBox:hover {
    color: #1e293b;
}

/* ── buttons ── */
QPushButton#secondary {
    background-color: #f1f5f9;
    border: 1px solid #d3daea;
    border-radius: 8px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 500;
    color: #475569;
}
QPushButton#secondary:hover {
    background-color: #e2e8f0;
    border-color: #4f7cff;
    color: #1e293b;
}
QPushButton#secondary:pressed {
    background-color: #dbe3ef;
}

QPushButton#primary {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4f7cff, stop:1 #6c5ce7);
    border: none;
    border-radius: 10px;
    padding: 14px 28px;
    font-size: 15px;
    font-weight: bold;
    color: #ffffff;
    letter-spacing: 0.5px;
}
QPushButton#primary:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #6389ff, stop:1 #7f70f0);
}
QPushButton#primary:pressed {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #3a60d0, stop:1 #5845c0);
}
QPushButton#primary:disabled {
    background-color: #e2e8f0;
    color: #94a3b8;
}

QPushButton#theme_btn {
    background-color: #f1f5f9;
    border: 1px solid #d3daea;
    border-radius: 6px;
    padding: 5px 14px;
    font-size: 12px;
    font-weight: 500;
    color: #475569;
    min-width: 80px;
}
QPushButton#theme_btn:hover {
    background-color: #e2e8f0;
    border-color: #4f7cff;
    color: #1e293b;
}

/* ── status pills ── */
QLabel#section {
    font-size: 12px;
    font-weight: 600;
    color: #94a3b8;
    letter-spacing: 1px;
    background: transparent;
}
QLabel#status {
    font-size: 12px;
    font-weight: 500;
    color: #64748b;
    background: transparent;
}

/* ── log ── */
QTextEdit#log {
    background-color: #f8fafc;
    border: 1px solid #d9dfec;
    border-radius: 10px;
    padding: 10px;
    font-family: "Cascadia Code", "JetBrains Mono", "Fira Code", "Consolas", monospace;
    font-size: 11px;
    color: #64748b;
    selection-background-color: #4f7cff;
}
QProgressBar {
    background-color: #e2e8f0;
    border: 1px solid #d3daea;
    border-radius: 6px;
    max-height: 12px;
    min-height: 12px;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4f7cff, stop:1 #7a5cf0);
    border-radius: 5px;
}
QTextEdit#log {
    background-color: #f8fafc;
    border: 1px solid #d9dfec;
    border-radius: 10px;
    padding: 10px;
    font-family: "Cascadia Code", "JetBrains Mono", "Fira Code", "Consolas", monospace;
    font-size: 11px;
    color: #64748b;
    selection-background-color: #4f7cff;
}
QStatusBar {
    background-color: #e7ebf2;
    border-top: 1px solid #d3daea;
    font-size: 11px;
    color: #64748b;
    padding: 5px 12px;
}
QScrollBar:vertical {
    background: transparent;
    width: 9px;
}
QScrollBar::handle:vertical {
    background-color: #cbd5e1;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background-color: #94a3b8;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0px;
}
QToolTip {
    background-color: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 11px;
    color: #1e293b;
}
"""

_THEMES: dict[str, str] = {"dark": DARK_QSS, "light": LIGHT_QSS}

# ── config ─────────────────────────────────────────────────────────────────


def _config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
        return base / "VidGrab"
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "vidgrab"


def _load_config() -> dict[str, str]:
    try:
        data = json.loads((_config_dir() / "config.json").read_text())
        theme = data.get("theme", "dark")
        lang = data.get("lang", "en")
    except (OSError, json.JSONDecodeError):
        theme = "dark"
        lang = "en"
    if theme not in _THEMES:
        theme = "dark"
    if lang not in LANGUAGES:
        lang = "en"
    return {"theme": theme, "lang": lang}


def _save_config(theme: str, lang: str = "en") -> None:
    try:
        d = _config_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.json").write_text(json.dumps({"theme": theme, "lang": lang}))
    except OSError:
        pass


# ── vector icons ────────────────────────────────────────────────────────────

_HAND = Qt.PointingHandCursor


def _icon(kind: str, color: str = "#8b93ab", size: int = 18) -> QIcon:
    """Draw a simple vector icon for buttons."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)

    m = size  # alias
    if kind == "download":
        cx = m / 2
        p.drawLine(int(cx), 2, int(cx), m - 7)
        p.drawLine(int(cx) - 4, m - 11, int(cx), m - 7)
        p.drawLine(int(cx) + 4, m - 11, int(cx), m - 7)
        p.drawLine(4, m - 3, m - 4, m - 3)
    elif kind == "scissors":
        cx, cy = m / 2, m / 2
        r = m // 3
        p.drawEllipse(int(cx - r - 1), int(cy - r), 6, 6)
        p.drawEllipse(int(cx + r - 5), int(cy - r), 6, 6)
        p.drawLine(int(cx), int(cy - r + 6), int(cx), int(cy + r))
    elif kind == "gear":
        cx, cy = m / 2, m / 2
        r = m // 3
        p.drawEllipse(int(cx - r), int(cy - r), r * 2, r * 2)
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            x1 = cx + (r - 1) * math.cos(rad)
            y1 = cy + (r - 1) * math.sin(rad)
            x2 = cx + (r + 2) * math.cos(rad)
            y2 = cy + (r + 2) * math.sin(rad)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
    elif kind == "clipboard":
        p.drawLine(6, 4, m - 6, 4)
        p.drawLine(6, m - 3, m - 6, m - 3)
        p.drawLine(6, 4, 6, m - 3)
        p.drawLine(m - 6, 4, m - 6, m - 3)
        p.drawLine(8, 7, m - 8, 7)
        p.drawLine(8, 10, m - 8, 10)
        p.drawLine(8, 13, m - 11, 13)
    elif kind == "folder":
        p.drawLine(3, 6, 3, m - 3)
        p.drawLine(m - 3, 6, m - 3, m - 3)
        p.drawLine(3, m - 3, m - 3, m - 3)
        p.drawLine(3, 6, 8, 6)
        p.drawLine(8, 3, 8, 6)
        p.drawLine(8, 6, m - 3, 6)
    elif kind == "trash":
        p.drawLine(5, 4, m - 5, 4)
        p.drawLine(5, 4, 5, m - 3)
        p.drawLine(m - 5, 4, m - 5, m - 3)
        p.drawLine(3, 4, m - 3, 4)
        p.drawLine(8, 7, 8, m - 5)
        p.drawLine(m // 2, 7, m // 2, m - 5)
        p.drawLine(m - 8, 7, m - 8, m - 5)
        p.drawLine(4, 7, m - 4, 7)
    elif kind == "sun":
        cx, cy = m / 2, m / 2
        r = m // 4
        p.drawEllipse(int(cx - r), int(cy - r), r * 2, r * 2)
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            x1 = cx + (r + 2) * math.cos(rad)
            y1 = cy + (r + 2) * math.sin(rad)
            x2 = cx + (r + 5) * math.cos(rad)
            y2 = cy + (r + 5) * math.sin(rad)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
    elif kind == "moon":
        cx, cy = m / 2, m / 2
        r = m // 3
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(int(cx - r), int(cy - r), r * 2, r * 2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.setCompositionMode(QPainter.CompositionMode_Source)
        cover = r + 1
        p.drawEllipse(int(cx - r + 3), int(cy - r - 2), cover * 2, cover * 2)

    p.end()
    return QIcon(pm)


# ── checkmark asset ────────────────────────────────────────────────────────


def _checkmark_path() -> str:
    """Return (generating if needed) a white checkmark PNG for checkbox tips."""
    d = _config_dir()
    p = d / "check.png"
    if not p.is_file():
        try:
            d.mkdir(parents=True, exist_ok=True)
            pix = QPixmap(20, 20)
            pix.fill(Qt.transparent)
            qp = QPainter(pix)
            qp.setRenderHint(QPainter.Antialiasing)
            qp.setPen(
                QPen(
                    QColor("#ffffff"), 2.4, Qt.SolidLine,
                    Qt.RoundCap, Qt.RoundJoin,
                )
            )
            qp.drawLine(4, 11, 8, 15)
            qp.drawLine(8, 15, 16, 5)
            qp.end()
            pix.save(str(p), "PNG")
        except Exception:  # noqa: BLE001 - fall back to no image
            return ""
    return p.as_posix()


# ── brand icon ─────────────────────────────────────────────────────────────


def _icon_path() -> Path:
    return get_app_dir() / "assets" / "icon.png"


def _app_icon() -> QIcon:
    p = _icon_path()
    if p.is_file():
        return QIcon(str(p))
    return QIcon()


def _brand_pixmap() -> QPixmap | None:
    """Sidebar logo at a fixed render size (None if the asset is missing)."""
    pm = QPixmap(str(_icon_path()))
    if pm.isNull():
        return None
    return pm.scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation)


# ── worker thread ──────────────────────────────────────────────────────────


class _Worker(QThread):
    """Run a download / processing task off the main thread."""

    finished = Signal(object)
    error = Signal(str)
    progress = Signal(str, object)
    log = Signal(str)

    def __init__(self, task: str, **kwargs) -> None:
        super().__init__()
        self._task = task
        self._kw = kwargs

    def _cb_progress(self, msg: str, pct: float | None) -> None:
        self.progress.emit(msg, pct)

    def _cb_log(self, msg: str) -> None:
        self.log.emit(msg)

    def run(self) -> None:
        try:
            common = {
                "video_filter": self._kw.get("video_filter"),
                "section_start": self._kw.get("section_start"),
                "section_end": self._kw.get("section_end"),
                "on_progress": self._cb_progress,
                "on_log": self._cb_log,
                "translate": self._kw.get("translate"),
            }
            if self._task == "download":
                result = download(
                    self._kw["url"], self._kw["output_dir"], self._kw["fmt"],
                    **common,
                )
            elif self._task == "download_both":
                result = download_both(
                    self._kw["url"], self._kw["output_dir"], **common,
                )
            elif self._task == "local_file":
                result = process_local_file(
                    self._kw["input_path"], self._kw["output_dir"], **common,
                )
            else:
                raise RuntimeError(f"Unknown task: {self._task}")
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


# ── sidebar ────────────────────────────────────────────────────────────────

_NAV_ITEMS: list[tuple[str, str]] = [
    ("download", "Download"),
    ("scissors", "Edit"),
    ("gear", "Settings"),
]


class _Sidebar(QWidget):
    """Left-hand navigation panel with brand block + icon nav buttons."""

    page_changed = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(200)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        brand = QWidget()
        brand.setObjectName("brand")
        bl = QVBoxLayout(brand)
        bl.setContentsMargins(18, 20, 18, 16)
        bl.setSpacing(2)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        icon = QLabel()
        icon.setObjectName("brand_icon")
        icon.setFixedSize(30, 30)
        icon.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        pm = _brand_pixmap()
        if pm:
            icon.setPixmap(pm)
        brand_row.addWidget(icon)
        title = QLabel('Vid<span>Grab</span>')
        title.setObjectName("brand_title")
        brand_row.addWidget(title)
        brand_row.addStretch()
        bl.addLayout(brand_row)
        sub = QLabel(f"v{__version__}")
        sub.setObjectName("brand_sub")
        bl.addWidget(sub)
        divider = QFrame()
        divider.setObjectName("brand_divider")
        divider.setFrameShape(QFrame.NoFrame)
        bl.addWidget(divider, alignment=Qt.AlignTop)
        lay.addWidget(brand)

        self._buttons: list[QPushButton] = []
        for idx, (kind, _key) in enumerate(_NAV_ITEMS):
            btn = QPushButton()
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setFixedHeight(42)
            btn.setCursor(QCursor(_HAND))
            if idx == 0:
                btn.setChecked(True)
            btn.toggled.connect(
                lambda checked, i=idx: self.page_changed.emit(i) if checked else None
            )
            lay.addWidget(btn)
            self._buttons.append(btn)

        lay.addStretch()

    def retranslate(self, t, theme: str = "dark") -> None:
        for btn, (kind, key) in zip(self._buttons, _NAV_ITEMS):
            color = "#ffffff" if (theme == "dark") else "#1e293b"
            if theme == "dark":
                color = "#b6c2d6" if btn.isChecked() else "#6b7a94"
            else:
                color = "#1e293b" if btn.isChecked() else "#64748b"
            btn.setIcon(_icon(kind, color, 18))
            btn.setIconSize(QSize(18, 18))
            btn.setText(f"  {t(key)}")

    def select(self, idx: int) -> None:
        self._buttons[idx].setChecked(True)


# ── page fade animation ────────────────────────────────────────────────────


class _FadeStack(QStackedWidget):
    """QStackedWidget with a fade animation on index change."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity")
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._prev = 0

    def setCurrentIndex(self, idx: int) -> None:
        if idx == self._prev:
            return super().setCurrentIndex(idx)
        self._anim.stop()
        self._effect.setOpacity(0.0)
        super().setCurrentIndex(idx)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._prev = idx


# ── main window ────────────────────────────────────────────────────────────


class VidGrabWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        cfg = _load_config()
        self._theme = cfg["theme"]
        self._lang = cfg["lang"]
        self._t = make_translator(self._lang)
        self._busy = False
        self._internet_online: bool | None = None
        self._worker: _Worker | None = None

        self.setWindowTitle("VidGrab")
        self.setMinimumSize(920, 680)
        self.resize(1040, 760)

        self._apply_theme()
        self._build_ui()
        self._apply_language()
        self._update_ffmpeg_status()
        self._start_internet_check()
        self._setup_shortcuts()

    # ── ui construction ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar = _Sidebar()
        self._sidebar.page_changed.connect(self._switch_page)
        body.addWidget(self._sidebar)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)

        self._stack = _FadeStack()
        self._stack.addWidget(self._build_download_form())
        self._stack.addWidget(self._build_edit_form())
        self._stack.addWidget(self._build_settings_form())
        content.addWidget(self._stack, stretch=4)
        content.addWidget(self._build_bottom())
        body.addLayout(content, stretch=1)
        root.addLayout(body, stretch=1)

        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._net_lbl = QLabel(f"\u25cf {self._t('checking\u2026')}")
        self._net_lbl.setFixedHeight(22)
        self._net_lbl.setAlignment(Qt.AlignCenter)
        self._label_pill(self._net_lbl, "#f59e0b")
        self._ffmpeg_lbl = QLabel()
        self._version_lbl = QLabel(f"v{__version__}")
        self._statusbar.addWidget(self._net_lbl)
        self._statusbar.addWidget(self._mk_sep())
        self._statusbar.addWidget(self._ffmpeg_lbl)
        self._statusbar.addPermanentWidget(self._version_lbl)

    @staticmethod
    def _label_pill(label: QLabel, color: str, dark_text: bool = False) -> None:
        label.setStyleSheet(
            f"background-color:{color}; color:{'#0b0f14' if dark_text else '#ffffff'};"
            "border-radius:10px; padding:2px 10px; font-weight:bold; font-size:11px;"
        )

    @staticmethod
    def _mk_sep() -> QLabel:
        s = QLabel("\u2502")
        s.setStyleSheet(
            "color:#2c3a4f; font-size:11px; padding:0 4px; background:transparent;"
        )
        return s

    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setObjectName("header")
        w.setFixedHeight(54)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(20, 0, 20, 0)

        lbl = QLabel(f'<b>VidGrab</b>  v{__version__}')
        lbl.setObjectName("app_version")
        lay.addWidget(lbl)
        lay.addStretch()

        self._theme_btn = QPushButton()
        self._theme_btn.setObjectName("theme_btn")
        self._theme_btn.setFixedHeight(28)
        self._theme_btn.setCursor(QCursor(_HAND))
        self._theme_btn.clicked.connect(self._toggle_theme)
        lay.addWidget(self._theme_btn)
        return w

    # ── download form ──────────────────────────────────────────────────

    def _build_download_form(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 14, 20, 6)
        lay.setSpacing(14)

        src = QGroupBox("SOURCE")
        src.setObjectName("source_card")
        self._dl_source = src
        sl = QVBoxLayout(src)
        row = QHBoxLayout()
        self._url = QLineEdit()
        self._url.setPlaceholderText("Paste a YouTube link\u2026")
        self._url.setClearButtonEnabled(True)
        self._url.returnPressed.connect(self._start_action)
        row.addWidget(self._url, stretch=1)
        pb = QPushButton("Paste")
        pb.setObjectName("secondary")
        pb.setMinimumWidth(76)
        pb.setCursor(QCursor(_HAND))
        pb.clicked.connect(self._paste_url)
        row.addWidget(pb)
        self._dl_paste = pb
        sl.addLayout(row)
        lay.addWidget(src)
        lay.addStretch(1)

        fmt = QGroupBox("FORMAT")
        fmt.setObjectName("format_card")
        self._dl_format = fmt
        fl = QHBoxLayout(fmt)
        self._mp4 = _colored_check("MP4 (video)", "#10b981")
        self._mp4.setChecked(True)
        self._mp3 = _colored_check("MP3 (audio)", "#f59e0b")
        fl.addWidget(self._mp4)
        fl.addWidget(self._mp3)
        fl.addStretch()
        lay.addWidget(fmt)

        row2 = QHBoxLayout()
        flip = QGroupBox("FLIP")
        flip.setObjectName("flip_card")
        self._dl_flip = flip
        vl = QVBoxLayout(flip)
        self._hflip = QCheckBox("Horizontal")
        self._vflip = QCheckBox("Vertical")
        vl.addWidget(self._hflip)
        vl.addWidget(self._vflip)
        row2.addWidget(flip)

        trim = QGroupBox("TRIM")
        trim.setObjectName("trim_card")
        self._dl_trim = trim
        tl = QFormLayout(trim)
        self._ts = QLineEdit()
        self._ts.setPlaceholderText("0:00")
        self._ts.setMaximumWidth(110)
        self._te = QLineEdit()
        self._te.setPlaceholderText("\u221e")
        self._te.setMaximumWidth(110)
        self._ts_lbl = QLabel("Start:")
        self._te_lbl = QLabel("End:")
        tl.addRow(self._ts_lbl, self._ts)
        tl.addRow(self._te_lbl, self._te)
        row2.addWidget(trim)
        lay.addLayout(row2)
        lay.addStretch(1)

        save = QGroupBox("SAVE TO")
        save.setObjectName("save_card")
        self._dl_save = save
        svl = QHBoxLayout(save)
        self._out = QLineEdit(str(default_output_dir()))
        self._out.setClearButtonEnabled(True)
        svl.addWidget(self._out, stretch=1)
        bb = QPushButton("Browse\u2026")
        bb.setObjectName("secondary")
        bb.setMinimumWidth(76)
        bb.setCursor(QCursor(_HAND))
        bb.clicked.connect(lambda: self._browse_folder(self._out))
        svl.addWidget(bb)
        self._dl_browse = bb
        lay.addWidget(save)
        return page

    # ── edit form ──────────────────────────────────────────────────────

    def _build_edit_form(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 14, 20, 6)
        lay.setSpacing(14)

        src = QGroupBox("SOURCE")
        src.setObjectName("source_card")
        self._ed_source = src
        sl = QVBoxLayout(src)
        row = QHBoxLayout()
        self._file = QLineEdit()
        self._file.setPlaceholderText("Choose a local video or audio file\u2026")
        self._file.setClearButtonEnabled(True)
        row.addWidget(self._file, stretch=1)
        bb = QPushButton("Browse\u2026")
        bb.setObjectName("secondary")
        bb.setMinimumWidth(76)
        bb.setCursor(QCursor(_HAND))
        bb.clicked.connect(self._browse_file)
        row.addWidget(bb)
        self._ed_browse = bb
        sl.addLayout(row)
        lay.addWidget(src)
        lay.addStretch(1)

        row2 = QHBoxLayout()
        flip = QGroupBox("FLIP")
        flip.setObjectName("flip_card")
        self._ed_flip = flip
        vl = QVBoxLayout(flip)
        self._ehflip = QCheckBox("Horizontal")
        self._evflip = QCheckBox("Vertical")
        vl.addWidget(self._ehflip)
        vl.addWidget(self._evflip)
        row2.addWidget(flip)

        trim = QGroupBox("TRIM")
        trim.setObjectName("trim_card")
        self._ed_trim = trim
        tl = QFormLayout(trim)
        self._ets = QLineEdit()
        self._ets.setPlaceholderText("0:00")
        self._ets.setMaximumWidth(110)
        self._ete = QLineEdit()
        self._ete.setPlaceholderText("\u221e")
        self._ete.setMaximumWidth(110)
        self._ets_lbl = QLabel("Start:")
        self._ete_lbl = QLabel("End:")
        tl.addRow(self._ets_lbl, self._ets)
        tl.addRow(self._ete_lbl, self._ete)
        row2.addWidget(trim)
        lay.addLayout(row2)
        lay.addStretch(1)

        save = QGroupBox("SAVE TO")
        save.setObjectName("save_card")
        self._ed_save = save
        svl = QHBoxLayout(save)
        self._eout = QLineEdit(str(default_output_dir()))
        self._eout.setClearButtonEnabled(True)
        svl.addWidget(self._eout, stretch=1)
        bb2 = QPushButton("Browse\u2026")
        bb2.setObjectName("secondary")
        bb2.setMinimumWidth(76)
        bb2.setCursor(QCursor(_HAND))
        bb2.clicked.connect(lambda: self._browse_folder(self._eout))
        svl.addWidget(bb2)
        self._ed_browse2 = bb2
        lay.addWidget(save)
        return page

    # ── settings form ──────────────────────────────────────────────────

    def _build_settings_form(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 14, 20, 6)
        lay.setSpacing(12)

        g1 = QGroupBox("APPEARANCE")
        g1.setObjectName("settings_card")
        self._settings_card = g1
        fl = QFormLayout(g1)
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["Dark", "Light"])
        self._theme_combo.setCurrentText(self._theme.capitalize())
        self._theme_combo.setCursor(QCursor(_HAND))
        self._theme_combo.currentTextChanged.connect(
            lambda t: self._set_theme(t.lower())
        )
        self._lang_combo = QComboBox()
        self._lang_combo.setCursor(QCursor(_HAND))
        for code, name in LANGUAGES.items():
            self._lang_combo.addItem(name, code)
        idx = self._lang_combo.findData(self._lang)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.currentIndexChanged.connect(self._on_lang_change)
        self._theme_lbl = QLabel("Theme:")
        self._lang_lbl = QLabel("Language:")
        fl.addRow(self._theme_lbl, self._theme_combo)
        fl.addRow(self._lang_lbl, self._lang_combo)
        lay.addWidget(g1)

        g2 = QGroupBox("ABOUT")
        g2.setObjectName("settings_card")
        self._about_card = g2
        al = QVBoxLayout(g2)
        self._about_lbl = QLabel()
        self._about_lbl.setWordWrap(True)
        self._about_lbl.setTextFormat(Qt.RichText)
        al.addWidget(self._about_lbl)
        lay.addWidget(g2)

        lay.addStretch()
        return page

    # ── shared bottom (log + progress + button) ────────────────────────

    def _build_bottom(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 4, 20, 12)
        lay.setSpacing(8)

        hdr = QHBoxLayout()
        hdr.setSpacing(8)
        self._log_lbl = QLabel("LOG")
        self._log_lbl.setObjectName("section")
        self._log_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        hdr.addWidget(self._log_lbl)
        hdr.addStretch()
        cb = QPushButton("Clear")
        cb.setObjectName("secondary")
        cb.setMinimumWidth(56)
        cb.setCursor(QCursor(_HAND))
        cb.clicked.connect(self._clear_log)
        self._clear_btn = cb
        hdr.addWidget(cb)
        lay.addLayout(hdr)

        self._log = QTextEdit()
        self._log.setObjectName("log")
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(60)
        lay.addWidget(self._log, stretch=1)

        prow = QHBoxLayout()
        prow.setSpacing(10)
        self._progress = QProgressBar()
        self._progress.setFixedHeight(12)
        self._progress.setTextVisible(False)
        self._progress.setValue(0)
        prow.addWidget(self._progress, stretch=1)
        self._status_lbl = QLabel("Ready")
        self._status_lbl.setObjectName("status")
        self._status_lbl.setMinimumWidth(110)
        self._status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        prow.addWidget(self._status_lbl)
        lay.addLayout(prow)

        self._action = QPushButton("\u2b07  Download")
        self._action.setObjectName("primary")
        self._action.setFixedHeight(50)
        self._action.setCursor(QCursor(_HAND))
        self._action.setEnabled(False)
        self._action.clicked.connect(self._start_action)
        lay.addWidget(self._action)

        return w

    # ── page switching ─────────────────────────────────────────────────

    def _switch_page(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)
        if idx < 2:
            self._action.setVisible(True)
            self._action.setText(self._action_label(idx))
        else:
            self._action.setVisible(False)
        self._refresh_btn()
        self._sidebar.retranslate(self._t, self._theme)

    def _action_label(self, idx: int) -> str:
        if idx == 0:
            return self._t("\u2b07  Download")
        return self._t("\u2702  Process")

    # ── theme ──────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        check = _checkmark_path()
        qss = _THEMES[self._theme]
        self.setStyleSheet(qss.replace("@CHECK@", check))

    def _toggle_theme(self) -> None:
        self._set_theme("light" if self._theme == "dark" else "dark")

    def _set_theme(self, name: str) -> None:
        if name not in _THEMES:
            return
        self._theme = name
        self._apply_theme()
        self._theme_combo.blockSignals(True)
        self._theme_combo.setCurrentText(self._theme.capitalize())
        self._theme_combo.blockSignals(False)
        self._apply_language()
        _save_config(self._theme, self._lang)

    # ── language ───────────────────────────────────────────────────────

    def _on_lang_change(self) -> None:
        code = self._lang_combo.currentData()
        if code and code != self._lang:
            self._lang = code
            self._t = make_translator(code)
            self._apply_language()
            _save_config(self._theme, self._lang)

    def _apply_language(self) -> None:
        t = self._t
        self._sidebar.retranslate(t, self._theme)
        self._theme_btn.setText(
            t("\u263e Dark") if self._theme == "light" else t("\u2600 Light")
        )
        # download page
        self._dl_source.setTitle(t("SOURCE"))
        self._dl_format.setTitle(t("FORMAT"))
        self._dl_flip.setTitle(t("FLIP"))
        self._dl_trim.setTitle(t("TRIM"))
        self._dl_save.setTitle(t("SAVE TO"))
        self._url.setPlaceholderText(t("Paste a YouTube link\u2026"))
        self._hflip.setText(t("Horizontal"))
        self._vflip.setText(t("Vertical"))
        self._mp4.setText(t("MP4 (video)"))
        self._mp3.setText(t("MP3 (audio)"))
        self._ts_lbl.setText(t("Start:"))
        self._te_lbl.setText(t("End:"))
        self._dl_paste.setText(t("Paste"))
        self._dl_browse.setText(t("Browse\u2026"))
        # edit page
        self._ed_source.setTitle(t("SOURCE"))
        self._ed_flip.setTitle(t("FLIP"))
        self._ed_trim.setTitle(t("TRIM"))
        self._ed_save.setTitle(t("SAVE TO"))
        self._file.setPlaceholderText(t("Choose a local video or audio file\u2026"))
        self._ehflip.setText(t("Horizontal"))
        self._evflip.setText(t("Vertical"))
        self._ets_lbl.setText(t("Start:"))
        self._ete_lbl.setText(t("End:"))
        self._ed_browse.setText(t("Browse\u2026"))
        self._ed_browse2.setText(t("Browse\u2026"))
        # settings page
        self._settings_card.setTitle(t("APPEARANCE"))
        self._theme_lbl.setText(t("Theme:"))
        self._lang_lbl.setText(t("Language:"))
        self._about_card.setTitle(t("ABOUT"))
        self._about_lbl.setText(
            t("about_text", ver=__version__)
        )
        # bottom
        self._log_lbl.setText(t("LOG"))
        self._clear_btn.setText(t("Clear"))
        if not self._busy:
            self._status_lbl.setText(t("Ready"))
            self._action.setText(self._action_label(self._stack.currentIndex()))
        # status bar
        self._update_ffmpeg_status()
        if self._internet_online is True:
            self._net_lbl.setText(f"\u25cf {t('Online')}")
            self._label_pill(self._net_lbl, "#10b981")
        elif self._internet_online is False:
            self._net_lbl.setText(f"\u25cb {t('Offline')}")
            self._label_pill(self._net_lbl, "#ef4444")
        else:
            self._net_lbl.setText(f"\u25cf {t('checking\u2026')}")
            self._label_pill(self._net_lbl, "#f59e0b")
        self._refresh_btn()

    # ── about ──────────────────────────────────────────────────────────

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            self._t("about_title"),
            self._t("about_dialog", ver=__version__),
        )

    # ── clipboard / file dialogs ───────────────────────────────────────

    def _paste_url(self) -> None:
        text = QApplication.clipboard().text()
        if text:
            self._url.setText(text.strip())

    def _browse_folder(self, target: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", target.text()
        )
        if folder:
            target.setText(folder)

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Media File",
            "",
            "Media (*.mp4 *.mp3 *.mkv *.webm *.avi *.mov *.m4a *.wav *.flac);;"
            "All files (*)",
        )
        if path:
            self._file.setText(path)

    # ── log ────────────────────────────────────────────────────────────

    def _clear_log(self) -> None:
        self._log.clear()

    def _append_log(self, msg: str) -> None:
        self._log.append(msg)

    # ── ffmpeg status ──────────────────────────────────────────────────

    def _update_ffmpeg_status(self) -> None:
        ff = find_ffmpeg()
        if ff:
            if Path(ff).is_relative_to(get_app_dir()):
                self._ffmpeg_lbl.setText(self._t("ffmpeg: embedded"))
            else:
                self._ffmpeg_lbl.setText(self._t("ffmpeg: {name}", name=Path(ff).name))
        else:
            self._ffmpeg_lbl.setText(self._t("ffmpeg: not found"))

    # ── internet ───────────────────────────────────────────────────────

    def _start_internet_check(self) -> None:
        self._pending_status: ConnectionStatus | None = None
        self._probe_thread: threading.Thread | None = None
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_internet)
        self._poll.start(200)
        self._do_probe()

    def _do_probe(self) -> None:
        if self._probe_thread is None or not self._probe_thread.is_alive():
            self._probe_thread = threading.Thread(
                target=self._probe_worker, daemon=True
            )
            self._probe_thread.start()

    def _probe_worker(self) -> None:
        self._pending_status = check_internet(timeout=2.5)

    def _poll_internet(self) -> None:
        status = self._pending_status
        if status is not None:
            self._pending_status = None
            self._apply_internet(status)

    def _apply_internet(self, status: ConnectionStatus) -> None:
        self._internet_online = status.online
        if status.online:
            self._net_lbl.setText(f"\u25cf {self._t('Online')}")
            self._label_pill(self._net_lbl, "#10b981")
        else:
            self._net_lbl.setText(f"\u25cb {self._t('Offline')}")
            self._label_pill(self._net_lbl, "#ef4444")
        self._refresh_btn()

    # ── busy / button state ────────────────────────────────────────────

    def _refresh_btn(self) -> None:
        if self._busy:
            self._action.setEnabled(False)
            return
        idx = self._stack.currentIndex()
        if idx == 0:
            self._action.setEnabled(self._internet_online is True)
        elif idx == 1:
            self._action.setEnabled(True)
        else:
            self._action.setVisible(False)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self._progress.setMaximum(0)
            self._progress.setValue(0)
            idx = self._stack.currentIndex()
            self._action.setText(
                self._t("\u2b07  Downloading\u2026")
                if idx == 0
                else self._t("\u2702  Processing\u2026")
            )
        else:
            self._progress.setMaximum(100)
            self._progress.setValue(0)
            self._switch_page(self._stack.currentIndex())

    # ── start action ───────────────────────────────────────────────────

    def _start_action(self) -> None:
        if self._busy:
            return
        idx = self._stack.currentIndex()
        if idx == 0:
            self._start_download()
        elif idx == 1:
            self._start_local_file()

    def _start_download(self) -> None:
        url = self._url.text().strip()
        if not url:
            QMessageBox.warning(self, self._t("Missing URL"), self._t("Please paste a YouTube link."))
            return
        if not self._internet_online:
            QMessageBox.warning(
                self,
                self._t("No internet"),
                self._t("You appear to be offline.\nVidGrab needs a live connection."),
            )
            return
        if not find_ffmpeg():
            QMessageBox.critical(
                self,
                self._t("ffmpeg required"),
                self._t(
                    "Downloads need ffmpeg for MP3 and most MP4 merges. "
                    "Install ffmpeg or rebuild with an embedded copy."
                ),
            )
            return

        self._set_busy(True)
        filt = _build_filter(self._hflip, self._vflip)
        start = self._ts.text().strip() or None
        end = self._te.text().strip() or None
        out = self._out.text()

        if self._mp4.isChecked() and self._mp3.isChecked():
            self._run("download_both", url=url, output_dir=out,
                      video_filter=filt, section_start=start, section_end=end)
        else:
            fmt = "mp3" if self._mp3.isChecked() else "mp4"
            self._run("download", url=url, output_dir=out, fmt=fmt,
                      video_filter=filt, section_start=start, section_end=end)

    def _start_local_file(self) -> None:
        path = self._file.text().strip()
        if not path:
            QMessageBox.warning(self, self._t("No file"), self._t("Please select a local media file."))
            return
        if not Path(path).is_file():
            QMessageBox.warning(
                self, self._t("File not found"),
                self._t("The file does not exist:\n{path}", path=path),
            )
            return
        if not find_ffmpeg():
            QMessageBox.critical(
                self,
                self._t("ffmpeg required"),
                self._t(
                    "Processing local files requires ffmpeg. "
                    "Install ffmpeg or rebuild with an embedded copy."
                ),
            )
            return

        self._set_busy(True)
        filt = _build_filter(self._ehflip, self._evflip)
        start = self._ets.text().strip() or None
        end = self._ete.text().strip() or None
        out = self._eout.text()
        self._run("local_file", input_path=path, output_dir=out,
                  video_filter=filt, section_start=start, section_end=end)

    def _run(self, task: str, **kwargs) -> None:
        self._worker = _Worker(task, translate=self._t, **kwargs)
        self._worker.finished.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self._append_log)
        self._worker.start()

    # ── callbacks ──────────────────────────────────────────────────────

    def _on_progress(self, msg: str, pct: object) -> None:
        self._status_lbl.setText(msg)
        if isinstance(pct, (int, float)):
            if self._progress.maximum() == 0:
                self._progress.setMaximum(100)
            val = int(min(100, max(0, pct)))
            self._progress.setValue(val)
            self._status_lbl.setText(f"{msg}  ({val}%)")
        elif self._busy:
            self._progress.setMaximum(0)

    def _on_result(self, result: object) -> None:
        self._set_busy(False)
        self._progress.setMaximum(100)
        self._progress.setValue(100)
        self._status_lbl.setText(self._t("Done"))
        if isinstance(result, tuple):
            paths = "\n".join(str(p) for p in result)
        else:
            paths = str(result)
        QMessageBox.information(
            self, self._t("Success"),
            self._t("Saved to:\n{paths}", paths=paths),
        )

    def _on_error(self, msg: str) -> None:
        self._set_busy(False)
        self._progress.setMaximum(100)
        self._progress.setValue(0)
        self._status_lbl.setText(self._t("Failed"))
        self._append_log(f"Error: {msg}")
        QMessageBox.critical(self, self._t("Something went wrong"), msg)

    # ── shortcuts ──────────────────────────────────────────────────────

    def _setup_shortcuts(self) -> None:
        from PySide6.QtGui import QKeySequence, QShortcut

        QShortcut(QKeySequence("Ctrl+V"), self, self._paste_url)
        QShortcut(QKeySequence("Ctrl+L"), self, self._clear_log)
        QShortcut(QKeySequence("F1"), self, self._show_about)

    # ── close ──────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        _save_config(self._theme, self._lang)
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self,
                self._t("Task in progress"),
                self._t(
                    "A download or processing task is still running.\n"
                    "Please wait for it to complete before closing."
                ),
            )
            event.ignore()
            return
        event.accept()


# ── helpers ────────────────────────────────────────────────────────────────


def _colored_check(text: str, color: str) -> QCheckBox:
    """QCheckBox with a custom accent color + white checkmark on check."""
    check = _checkmark_path()
    cb = QCheckBox(text)
    cb.setStyleSheet(
        f"QCheckBox::indicator:checked {{ background-color: {color}; "
        f"border-color: {color}; image: url({check}); }}"
    )
    return cb


def _build_filter(hflip: QCheckBox, vflip: QCheckBox) -> str | None:
    parts = []
    if hflip.isChecked():
        parts.append("hflip")
    if vflip.isChecked():
        parts.append("vflip")
    return ",".join(parts) or None


# ── entry point ────────────────────────────────────────────────────────────


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("VidGrab")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(_app_icon())
    app.setStyle("Fusion")

    font = QFont()
    font.setFamilies(
        ["Segoe UI", "Noto Sans", "Ubuntu", "Cantarell", "sans-serif"]
    )
    app.setFont(font)

    window = VidGrabWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
