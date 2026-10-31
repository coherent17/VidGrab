"""VidGrab — professional desktop media tool (PySide6 / Qt)."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QObject,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QIcon,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from vidgrab import __version__
from vidgrab.captions import transcribe
from vidgrab.downloader import (
    NAME_TEMPLATES,
    DownloadCancelled,
    default_output_dir,
    download,
    download_both,
    download_playlist,
    fetch_dislikes,
    find_ffmpeg,
    get_app_dir,
    get_bundle_dir,
    probe,
)
from vidgrab.downloads_panel import (
    CANCELLED,
    DONE,
    FAILED,
    QUEUED,
    RUNNING,
    DownloadItem,
    DownloadsPanel,
    LinkRow,
    human_size,
    load_history,
    save_history,
)
from vidgrab.i18n import FLAGS, LANGUAGES, make_translator
from vidgrab.jobs import DownloadJob, run_job
from vidgrab.network import ConnectionStatus, check_internet
from vidgrab.preview import QT_MULTIMEDIA_OK as _QT_MULTIMEDIA_OK
from vidgrab.studio import compose_audio, compose_video
from vidgrab.studio_page import StudioPage

# ── palette ────────────────────────────────────────────────────────────────
#
# One stylesheet template, two palettes. Brand: violet #7c5cff -> cyan #22d3ee.

_PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "BG": "#0a0b16", "BG2": "#120f27", "SIDEBAR": "#0c0c1b",
        "SURFACE": "#14152b", "SURFACE_HI": "#1c1e3c", "FIELD": "#0e0f22",
        "BORDER": "#262a4d", "BORDER_HI": "#3a3f70",
        "TEXT": "#eceeff", "TEXT_DIM": "#b4b8dc", "TEXT_MUTED": "#7b80aa",
        "ACCENT": "#7c5cff", "ACCENT_HI": "#937aff", "ACCENT_LO": "#5a3fd6",
        "ACCENT2": "#22d3ee", "ACCENT2_HI": "#5ee3f5", "ACCENT2_LO": "#139bb3",
        "NAV_ACTIVE": "#2a2160", "SEL": "#2b2563",
        "SCROLL": "#2c3060", "SCROLL_HI": "#3e4380", "PREVIEW_BG": "#05060f",
        "AMBER": "#f59e0b", "AMBER_HI": "#fbbf24",
        "DISABLED_BG": "#1d1f3a", "DISABLED_TEXT": "#545a85",
    },
    "light": {
        "BG": "#f5f6fc", "BG2": "#ecebff", "SIDEBAR": "#ffffff",
        "SURFACE": "#ffffff", "SURFACE_HI": "#f1f2fb", "FIELD": "#f8f9fe",
        "BORDER": "#e2e4f3", "BORDER_HI": "#c9cdea",
        "TEXT": "#1b1d3a", "TEXT_DIM": "#454a75", "TEXT_MUTED": "#80859f",
        "ACCENT": "#6a4cff", "ACCENT_HI": "#7f66ff", "ACCENT_LO": "#5236e0",
        "ACCENT2": "#0ea5e9", "ACCENT2_HI": "#38bdf8", "ACCENT2_LO": "#0284c7",
        "NAV_ACTIVE": "#e9e4ff", "SEL": "#e6e1ff",
        "SCROLL": "#d3d6ea", "SCROLL_HI": "#b8bcdc", "PREVIEW_BG": "#0b0c18",
        "AMBER": "#d97706", "AMBER_HI": "#f59e0b",
        "DISABLED_BG": "#e4e6f3", "DISABLED_TEXT": "#a2a6c2",
    },
}

_QSS_TEMPLATE = """
* {
    font-family: @FONT_CHAIN@;
}
QLabel {
    color: @TEXT_DIM@;
    background: transparent;
}
QWidget#central {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 @BG@, stop:1 @BG2@);
}

/* ── page header ── */
QWidget#header {
    background: transparent;
    border-bottom: 1px solid @BORDER@;
}
QLabel#page_title {
    font-size: 22px;
    font-weight: 800;
    color: @TEXT@;
}
QLabel#page_sub {
    font-size: 12px;
    color: @TEXT_MUTED@;
}

/* ── sidebar ── */
QWidget#sidebar {
    background-color: @SIDEBAR@;
    border-right: 1px solid @BORDER@;
}
QLabel#brand_title {
    font-size: 21px;
    font-weight: 800;
    color: @TEXT@;
}
QLabel#brand_sub, QLabel#sidebar_foot {
    font-size: 11px;
    color: @TEXT_MUTED@;
}
QFrame#brand_divider {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 @ACCENT@, stop:0.5 @ACCENT2@, stop:1 transparent);
    border: none;
    max-height: 2px;
    min-height: 2px;
}
QToolButton#nav {
    background: transparent;
    border: none;
    border-radius: 12px;
    padding: 6px 2px 4px 2px;
    font-size: 11px;
    font-weight: 700;
    color: @TEXT_MUTED@;
}
QToolButton#nav:hover {
    background-color: @SURFACE_HI@;
    color: @TEXT@;
}
QToolButton#nav:checked {
    background-color: @NAV_ACTIVE@;
    color: @TEXT@;
}
QWidget#url_bar {
    background-color: @SURFACE@;
    border: 1px solid @BORDER@;
    border-radius: 16px;
}
QLineEdit#url_input {
    font-size: 15px;
    padding: 11px 14px;
    border-radius: 11px;
}
QLabel#field_cap {
    color: @TEXT_MUTED@;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1px;
    min-width: 72px;
}
QPushButton#nav {
    background: transparent;
    border: none;
    border-radius: 10px;
    margin: 1px 12px;
    padding: 10px 14px;
    text-align: left;
    font-size: 13px;
    font-weight: 600;
    color: @TEXT_MUTED@;
}
QPushButton#nav:hover {
    background-color: @SURFACE_HI@;
    color: @TEXT@;
}
QPushButton#nav:checked {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 @NAV_ACTIVE@, stop:1 @SIDEBAR@);
    border-left: 3px solid @ACCENT@;
    color: @TEXT@;
}

/* ── cards ── */
QGroupBox {
    background-color: @SURFACE@;
    border: 1px solid @BORDER@;
    border-radius: 14px;
    padding: 0px;
}
QGroupBox:hover {
    border-color: @BORDER_HI@;
}
QFrame#card_bar {
    border: none;
    border-radius: 2px;
    min-width: 4px;
    max-width: 4px;
    min-height: 14px;
    max-height: 14px;
}

/* ── studio panels ── */
QWidget#panel, QWidget#toolbar {
    background-color: @SURFACE@;
    border: 1px solid @BORDER@;
    border-radius: 12px;
}
QLabel#panel_title {
    color: @TEXT@;
    font-size: 13px;
    font-weight: 800;
}
QTabWidget::pane {
    background-color: @SURFACE@;
    border: 1px solid @BORDER@;
    border-radius: 12px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: @TEXT_MUTED@;
    padding: 8px 6px;
    margin-right: 2px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 13px;
    font-weight: 700;
}
QTabBar::tab:selected {
    color: @TEXT@;
    border-bottom: 2px solid @ACCENT@;
}
QTabBar::tab:hover {
    color: @TEXT@;
}
QPlainTextEdit {
    background-color: @FIELD@;
    border: 1px solid @BORDER@;
    border-radius: 9px;
    padding: 6px 8px;
    font-size: 14px;
    color: @TEXT@;
    selection-background-color: @ACCENT@;
}
QPlainTextEdit:focus {
    border-color: @ACCENT@;
}
QSplitter::handle:horizontal {
    background: transparent;
}

/* ── segmented mode switch ── */
QWidget#segmented {
    background-color: @FIELD@;
    border: 1px solid @BORDER@;
    border-radius: 13px;
}
QPushButton#segment {
    background: transparent;
    border: none;
    border-radius: 10px;
    padding: 9px 22px;
    font-size: 13px;
    font-weight: 700;
    color: @TEXT_MUTED@;
}
QPushButton#segment:hover {
    color: @TEXT@;
}
QPushButton#segment:checked {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 @ACCENT@, stop:1 @ACCENT2@);
    color: #ffffff;
}
QPushButton#segment[compact="true"] {
    padding: 6px 4px;
}

/* ── inputs ── */
QLineEdit, QAbstractSpinBox {
    background-color: @FIELD@;
    border: 1px solid @BORDER@;
    border-radius: 9px;
    padding: 7px 11px;
    font-size: 13px;
    color: @TEXT@;
    selection-background-color: @ACCENT@;
}
QLineEdit:hover, QAbstractSpinBox:hover {
    border-color: @BORDER_HI@;
}
QLineEdit:focus, QAbstractSpinBox:focus {
    border-color: @ACCENT@;
}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
    border: none;
    background: transparent;
    width: 18px;
}
QAbstractSpinBox::up-arrow {
    image: url(@ARROW_UP@);
    width: 10px;
    height: 7px;
}
QAbstractSpinBox::down-arrow {
    image: url(@ARROW_DOWN@);
    width: 10px;
    height: 7px;
}

QComboBox {
    background-color: @FIELD@;
    border: 1px solid @BORDER@;
    border-radius: 9px;
    padding: 7px 12px;
    font-size: 13px;
    color: @TEXT@;
    min-width: 120px;
}
QComboBox:hover {
    border-color: @ACCENT@;
}
QComboBox::drop-down {
    border: none;
    width: 28px;
}
QComboBox::down-arrow {
    image: url(@ARROW_DOWN@);
    width: 12px;
    height: 8px;
    margin-right: 10px;
}
QComboBox QAbstractItemView {
    background-color: @SURFACE@;
    border: 1px solid @BORDER@;
    color: @TEXT@;
    selection-background-color: @SEL@;
    selection-color: @TEXT@;
    /* border-radius on the popup view keeps the combo from closing on item
       click in some Qt versions — keep it square to stay reliable. */
    border-radius: 0px;
    padding: 4px;
}

/* ── tables (clip timeline, subtitle cues) ── */
QTableWidget {
    background-color: @FIELD@;
    alternate-background-color: @SURFACE@;
    border: 1px solid @BORDER@;
    border-radius: 10px;
    gridline-color: transparent;
    color: @TEXT@;
    font-size: 13px;
    selection-background-color: @SEL@;
    selection-color: @TEXT@;
}
QTableWidget::item {
    padding: 4px 8px;
}
QTableWidget QLineEdit {
    padding: 2px 6px;
    border-radius: 4px;
}
QHeaderView {
    background-color: @FIELD@;
    border: none;
}
QHeaderView::section:vertical {
    background-color: @FIELD@;
    color: @TEXT_MUTED@;
    border: none;
    padding: 0 6px;
}
QHeaderView::section {
    background-color: @SURFACE@;
    color: @TEXT_MUTED@;
    border: none;
    border-bottom: 1px solid @BORDER@;
    padding: 6px 8px;
    font-size: 11px;
    font-weight: 700;
}
QTableCornerButton::section {
    background-color: @SURFACE@;
    border: none;
}

/* ── sliders ── */
QSlider::groove:horizontal {
    height: 6px;
    border-radius: 3px;
    background: @BORDER@;
}
QSlider::sub-page:horizontal {
    height: 6px;
    border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 @ACCENT@, stop:1 @ACCENT2@);
}
QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
    background: #ffffff;
    border: 3px solid @ACCENT@;
}
QSlider::handle:horizontal:hover {
    border-color: @ACCENT2@;
}
QSlider#speed_slider::sub-page:horizontal {
    background: @AMBER@;
}
QSlider#speed_slider::handle:horizontal {
    border-color: @AMBER@;
}
QSlider#speed_slider::handle:horizontal:hover {
    border-color: @AMBER_HI@;
}
QLabel#speed_value {
    color: @AMBER_HI@;
    font-weight: 800;
    font-size: 15px;
}
QLabel#speed_marker, QLabel#time_lbl, QLabel#hint {
    color: @TEXT_MUTED@;
    font-size: 11px;
}
QLabel#time_lbl {
    font-size: 12px;
}
QLabel#level_value {
    color: @TEXT@;
    font-weight: 700;
    min-width: 40px;
}
QLabel#total_lbl {
    color: @TEXT@;
    font-weight: 700;
    font-size: 12px;
}

/* ── inline preview player ── */
QLabel#preview_video {
    background-color: @PREVIEW_BG@;
    border: 1px solid @BORDER@;
    border-radius: 12px;
    color: @TEXT_MUTED@;
    font-size: 13px;
}

QCheckBox {
    color: @TEXT_DIM@;
    font-size: 13px;
    spacing: 10px;
    padding: 2px 0;
    background: transparent;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid @BORDER_HI@;
    border-radius: 6px;
    background: @FIELD@;
}
QCheckBox::indicator:hover {
    border-color: @ACCENT@;
}
QCheckBox::indicator:checked {
    image: url(@CHECK@);
    background-color: @ACCENT@;
    border-color: @ACCENT@;
}
QCheckBox:hover {
    color: @TEXT@;
}

/* ── info card ── */
QLabel#info_name {
    color: @TEXT@;
    font-size: 15px;
    font-weight: 700;
}
QLabel#info_meta {
    color: @TEXT_MUTED@;
    font-size: 12px;
}
QLabel#info_thumb {
    background-color: @FIELD@;
    border: 1px solid @BORDER@;
    border-radius: 10px;
    color: @TEXT_MUTED@;
    font-size: 11px;
}

/* ── buttons ── */
QPushButton#secondary {
    background-color: @SURFACE_HI@;
    border: 1px solid @BORDER@;
    border-radius: 9px;
    padding: 7px 12px;
    font-size: 13px;
    font-weight: 600;
    color: @TEXT@;
}
QPushButton#secondary:hover {
    border-color: @ACCENT@;
    color: @ACCENT_HI@;
}
QPushButton#secondary:pressed {
    background-color: @FIELD@;
}
QPushButton#secondary:disabled {
    color: @DISABLED_TEXT@;
    border-color: @BORDER@;
}

QPushButton#primary {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 @ACCENT@, stop:1 @ACCENT2@);
    border: none;
    border-radius: 12px;
    padding: 14px 28px;
    font-size: 15px;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: 0.5px;
}
QPushButton#primary[compact="true"] {
    /* fixed-height toolbar buttons: the default 14px padding squashes the text */
    padding: 4px 22px;
}
QPushButton#primary:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 @ACCENT_HI@, stop:1 @ACCENT2_HI@);
}
QPushButton#primary:pressed {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 @ACCENT_LO@, stop:1 @ACCENT2_LO@);
}
QPushButton#primary:disabled {
    background-color: @DISABLED_BG@;
    color: @DISABLED_TEXT@;
}

QPushButton#play_btn {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 @ACCENT@, stop:1 @ACCENT2@);
    border: none;
    border-radius: 18px;
}
QPushButton#play_btn:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 @ACCENT_HI@, stop:1 @ACCENT2_HI@);
}
QPushButton#play_btn:disabled {
    background-color: @DISABLED_BG@;
}
/* ── downloads list ── */
QListWidget#dl_list {
    background: transparent;
    border: none;
}
QListWidget#dl_list::item, QListWidget#dl_list::item:hover {
    background: transparent;
    border: none;
    padding: 0px;
}
QWidget#dl_row {
    background-color: @FIELD@;
    border: 1px solid @BORDER@;
    border-radius: 12px;
}
QWidget#dl_row:hover {
    border-color: @BORDER_HI@;
}
QLabel#dl_thumb {
    background-color: @SURFACE_HI@;
    border-radius: 8px;
}
QLabel#dl_title {
    color: @TEXT@;
    font-size: 13px;
    font-weight: 700;
}
QLabel#dl_status {
    color: @TEXT_MUTED@;
    font-size: 12px;
}
QLabel#dl_status[state="done"] {
    color: #10b981;
}
QLabel#dl_status[state="failed"] {
    color: #ef4444;
}
QLabel#dl_status[state="running"] {
    color: @ACCENT2@;
}
QPushButton#primary_small {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 @ACCENT@, stop:1 @ACCENT2@);
    border: none;
    border-radius: 9px;
    padding: 7px 12px;
    font-size: 13px;
    font-weight: 700;
    color: #ffffff;
}
QPushButton#primary_small:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 @ACCENT_HI@, stop:1 @ACCENT2_HI@);
}
QPushButton#anchor_btn {
    background-color: @FIELD@;
    border: 1px solid @BORDER@;
    border-radius: 5px;
    padding: 0px;
}
QPushButton#anchor_btn:hover {
    border-color: @ACCENT_HI@;
}
QPushButton#anchor_btn:checked {
    background-color: @SEL@;
    border-color: @ACCENT@;
}
QPushButton#theme_btn {
    background-color: @SURFACE@;
    border: 1px solid @BORDER@;
    border-radius: 15px;
    padding: 5px 16px;
    font-size: 12px;
    font-weight: 600;
    color: @TEXT@;
    min-width: 80px;
}
QPushButton#theme_btn:hover {
    border-color: @ACCENT@;
}

/* ── status / log ── */
QLabel#status {
    font-size: 12px;
    font-weight: 600;
    color: @TEXT_MUTED@;
}
QWidget#log_inner {
    background-color: @FIELD@;
    border: 1px solid @BORDER@;
    border-radius: 10px;
}
QTextEdit#log {
    background-color: @FIELD@;
    border: 1px solid @BORDER@;
    border-radius: 10px;
    padding: 8px;
    font-family: "Cascadia Code", "JetBrains Mono", "Fira Code", "Consolas", monospace;
    font-size: 11px;
    color: @TEXT_MUTED@;
    selection-background-color: @ACCENT@;
}
QProgressBar {
    background-color: @FIELD@;
    border: 1px solid @BORDER@;
    border-radius: 6px;
    max-height: 12px;
    min-height: 12px;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 @ACCENT@, stop:1 @ACCENT2@);
    border-radius: 5px;
}
QStatusBar {
    background-color: @SIDEBAR@;
    border-top: 1px solid @BORDER@;
    font-size: 11px;
    color: @TEXT_MUTED@;
    padding: 5px 12px;
}
QScrollArea#page_scroll {
    background: transparent;
    border: none;
}
QScrollArea#page_scroll > QWidget#qt_scrollarea_viewport {
    background: transparent;
}
QScrollArea#page_scroll > QWidget#qt_scrollarea_viewport > QWidget {
    background: transparent;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background: transparent;
    width: 9px;
    height: 9px;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background-color: @SCROLL@;
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background-color: @SCROLL_HI@;
}
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
    height: 0px;
    width: 0px;
}

/* ── dialogs (Qt file dialog, message boxes) and generic widgets ── */
QDialog, QMessageBox {
    background-color: @SURFACE@;
}
QDialog QLabel, QMessageBox QLabel {
    color: @TEXT@;
}
QDialog QPushButton {
    background-color: @SURFACE_HI@;
    border: 1px solid @BORDER@;
    border-radius: 8px;
    padding: 6px 16px;
    min-width: 64px;
    font-size: 13px;
    color: @TEXT@;
}
QDialog QPushButton:hover {
    border-color: @ACCENT@;
}
QDialog QPushButton:default {
    border-color: @ACCENT@;
}
QDialog QPushButton:disabled {
    color: @DISABLED_TEXT@;
}
QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px;
    color: @TEXT@;
}
QToolButton:hover {
    background-color: @SURFACE_HI@;
    border-color: @BORDER@;
}
QToolButton:checked {
    background-color: @SEL@;
}
QTreeView, QListView {
    background-color: @FIELD@;
    alternate-background-color: @SURFACE@;
    border: 1px solid @BORDER@;
    border-radius: 8px;
    color: @TEXT@;
    font-size: 13px;
    selection-background-color: @SEL@;
    selection-color: @TEXT@;
    outline: 0;
}
QTreeView::item, QListView::item {
    padding: 3px 0px;
}
QTreeView::item:hover, QListView::item:hover {
    background-color: @SURFACE_HI@;
}
QTreeView::item:selected, QListView::item:selected {
    background-color: @SEL@;
    color: @TEXT@;
}
QMenu {
    background-color: @SURFACE@;
    border: 1px solid @BORDER@;
    color: @TEXT@;
    padding: 4px;
}
QMenu::item {
    padding: 6px 18px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: @SEL@;
}
QSplitter::handle {
    background-color: @BORDER@;
}
QToolTip {
    background-color: @SURFACE_HI@;
    border: 1px solid @BORDER@;
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 11px;
    color: @TEXT@;
}
"""


def _render_qss(theme: str) -> str:
    qss = _QSS_TEMPLATE
    for key, value in _PALETTES[theme].items():
        qss = qss.replace(f"@{key}@", value)
    return qss


DARK_QSS = _render_qss("dark")
LIGHT_QSS = _render_qss("light")

_THEMES: dict[str, str] = {"dark": DARK_QSS, "light": LIGHT_QSS}

_CARD_ACCENTS: dict[str, dict[str, str]] = {
    "dark": {
        "source": "#f43f5e", "format": "#10b981", "flip": "#06b6d4",
        "speed": "#f59e0b", "trim": "#8b5cf6", "save": "#7c5cff", "settings": "#8b5cf6",
        "preview": "#22d3ee", "clips": "#f472b6", "output": "#10b981",
        "subs": "#facc15", "music": "#22d3ee", "medley": "#a78bfa",
    },
    "light": {
        "source": "#e11d48", "format": "#059669", "flip": "#0891b2",
        "speed": "#d97706", "trim": "#7c3aed", "save": "#6a4cff", "settings": "#7c3aed",
        "preview": "#0891b2", "clips": "#db2777", "output": "#059669",
        "subs": "#ca8a04", "music": "#0284c7", "medley": "#7c3aed",
    },
}

# ── config ─────────────────────────────────────────────────────────────────


def _config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
        return base / "VidGrab"
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "vidgrab"


# every persisted setting with its default; config.json may hold any subset
DEFAULT_SETTINGS: dict = {
    "theme": "dark",
    "lang": "en",
    "out_dir": "",  # "" = ~/Downloads/VidGrab
    "fmt": "mp4",  # mp4 | mp3 | both
    "video_quality": None,  # None = best available
    "audio_quality": "192",
    "sub_enabled": False,
    "sub_lang": "zh-Hant",
    "sub_mode": "file",  # file | burn
    "name_template": "title",  # key of downloader.NAME_TEMPLATES
    "notify": True,
    "render_quality": "balanced",  # key of studio.RENDER_QUALITY
    "studio_resolution": "auto",
    "subtitle_presets": {},  # name -> SubtitleStyle fields
    "recent_projects": [],  # Studio .vgproj files, newest first
    "caption_language": "auto",  # key of captions.LANGUAGES
    "caption_model": "balanced",  # key of captions.MODELS
}


def _load_config() -> dict:
    try:
        data = json.loads((_config_dir() / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    cfg = json.loads(json.dumps(DEFAULT_SETTINGS))  # deep copy of the defaults
    cfg.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    if cfg["theme"] not in _THEMES:
        cfg["theme"] = "dark"
    if cfg["lang"] not in LANGUAGES:
        cfg["lang"] = "en"
    return cfg


def _save_config(theme: str, lang: str = "en", extra: dict | None = None) -> None:
    """Persist theme / language plus any *extra* settings, keeping the rest."""
    cfg = _load_config()
    cfg.update(theme=theme, lang=lang)
    cfg.update(extra or {})
    try:
        d = _config_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    except OSError:
        pass


def _dir_size(path: Path) -> int:
    try:
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    except OSError:
        return 0


def _chime_path() -> Path | None:
    """A short two-note chime (generated once) for 'downloads finished'."""
    path = _config_dir() / "chime.wav"
    if path.is_file():
        return path
    try:
        import struct
        import wave

        rate = 44100
        frames = bytearray()
        for freq, length in ((880.0, 0.13), (1318.5, 0.26)):
            n = int(rate * length)
            for i in range(n):
                env = min(1.0, i / 400) * (1 - i / n) ** 2
                value = int(9000 * env * math.sin(2 * math.pi * freq * i / rate))
                frames += struct.pack("<h", value)
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(bytes(frames))
        return path
    except OSError:
        return None


def _versions() -> list[tuple[str, str]]:
    import platform

    import PySide6
    import yt_dlp

    ff = find_ffmpeg()
    ff_ver = "—"
    if ff:
        try:
            out = subprocess.run([ff, "-version"], capture_output=True, text=True,
                                 timeout=10, check=False).stdout.split("\n", 1)[0]
            ff_ver = out.split(" version ", 1)[-1].split(" ", 1)[0] if out else "—"
        except (OSError, subprocess.SubprocessError):
            pass
    return [
        ("VidGrab", __version__),
        ("yt-dlp", yt_dlp.version.__version__),
        ("ffmpeg", ff_ver),
        ("Qt / PySide6", PySide6.__version__),
        ("Python", platform.python_version()),
    ]


def _thumb_cache_dir() -> Path:
    d = _config_dir() / "cache"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def _fmt_duration(seconds: float) -> str:
    """Render a duration in seconds as M:SS or H:MM:SS."""
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _fmt_count(n: int) -> str:
    """Compact count for metric-style numbers: 19393948 -> 19.4M."""
    value = float(n)
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B".rstrip("0").rstrip(".")
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".rstrip("0").rstrip(".")
    if value >= 1_000:
        return f"{value / 1_000:.1f}K".rstrip("0").rstrip(".")
    return str(int(value))


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
    elif kind == "film":
        p.drawRoundedRect(3, 3, m - 6, m - 6, 2, 2)
        p.drawLine(7, 3, 7, m - 3)
        p.drawLine(m - 7, 3, m - 7, m - 3)
        p.drawLine(3, m // 2, 7, m // 2)
        p.drawLine(m - 7, m // 2, m - 3, m // 2)
    elif kind == "music":
        p.drawLine(7, m - 5, 7, 4)
        p.drawLine(7, 4, m - 3, 2)
        p.drawLine(m - 3, 2, m - 3, m - 7)
        p.setBrush(QColor(color))
        p.drawEllipse(2, m - 7, 5, 4)
        p.drawEllipse(m - 8, m - 9, 5, 4)
    elif kind == "captions":
        p.drawRoundedRect(2, 4, m - 4, m - 8, 3, 3)
        p.drawLine(5, m // 2 - 1, m // 2 - 1, m // 2 - 1)
        p.drawLine(m // 2 + 2, m // 2 - 1, m - 5, m // 2 - 1)
        p.drawLine(5, m // 2 + 3, m - 8, m // 2 + 3)
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


def _qpalette(theme: str) -> QPalette:
    """Qt palette matching *theme*, for widgets the stylesheet doesn't fully
    cover — notably Qt's own file dialog and message boxes."""
    c = {k: QColor(v) for k, v in _PALETTES[theme].items()}
    pal = QPalette()
    for role, key in (
        (QPalette.Window, "SURFACE"),
        (QPalette.WindowText, "TEXT"),
        (QPalette.Base, "FIELD"),
        (QPalette.AlternateBase, "SURFACE"),
        (QPalette.Text, "TEXT"),
        (QPalette.Button, "SURFACE_HI"),
        (QPalette.ButtonText, "TEXT"),
        (QPalette.ToolTipBase, "SURFACE_HI"),
        (QPalette.ToolTipText, "TEXT"),
        (QPalette.PlaceholderText, "TEXT_MUTED"),
        (QPalette.Highlight, "ACCENT"),
        (QPalette.Link, "ACCENT2"),
        (QPalette.Mid, "BORDER"),
        (QPalette.Midlight, "BORDER_HI"),
    ):
        pal.setColor(role, c[key])
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, c["DISABLED_TEXT"])
    return pal


def _chevron_path(color: str, *, down: bool) -> str:
    """Return (generating if needed) a small chevron PNG for combo/spin arrows."""
    d = _config_dir()
    p = d / f"chevron_{'down' if down else 'up'}_{color.lstrip('#')}.png"
    if not p.is_file():
        try:
            d.mkdir(parents=True, exist_ok=True)
            pix = QPixmap(12, 8)
            pix.fill(Qt.transparent)
            qp = QPainter(pix)
            qp.setRenderHint(QPainter.Antialiasing)
            qp.setPen(QPen(QColor(color), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if down:
                qp.drawLine(2, 2, 6, 6)
                qp.drawLine(6, 6, 10, 2)
            else:
                qp.drawLine(2, 6, 6, 2)
                qp.drawLine(6, 2, 10, 6)
            qp.end()
            pix.save(str(p), "PNG")
        except Exception:  # noqa: BLE001 - fall back to no image
            return ""
    return p.as_posix()


# ── brand icon ─────────────────────────────────────────────────────────────


def _icon_path() -> Path:
    return get_app_dir() / "assets" / "icon.png"


def _flag_icon(lang_code: str) -> QIcon:
    """Bundled color flag icon for a language code (PNG, not emoji)."""
    cc = FLAGS.get(lang_code, "us")
    p = get_app_dir() / "assets" / "flags" / f"{cc}.png"
    if p.is_file():
        return QIcon(str(p))
    return QIcon()


def _app_icon() -> QIcon:
    p = _icon_path()
    if p.is_file():
        return QIcon(str(p))
    return QIcon()


def _brand_pixmap(size: int = 30) -> QPixmap | None:
    """Sidebar logo at a fixed render size (None if the asset is missing)."""
    pm = QPixmap(str(_icon_path()))
    if pm.isNull():
        return None
    return pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


# ── file pickers ───────────────────────────────────────────────────────────
#
# Same call shape as QFileDialog's static helpers, but the dialog opens at a
# size where Name / Size / Type / Date columns aren't truncated. (On Windows
# and macOS Qt still shows the native dialog.)

_DIALOG_SIZE = QSize(980, 600)


def _run_dialog(
    parent: QWidget, caption: str, directory: str, name_filter: str,
    mode: QFileDialog.FileMode, *, save: bool = False,
) -> list[str]:
    dlg = QFileDialog(parent, caption, directory, name_filter)
    dlg.setFileMode(mode)
    if save:
        dlg.setAcceptMode(QFileDialog.AcceptSave)
    if mode == QFileDialog.Directory:
        dlg.setOption(QFileDialog.ShowDirsOnly)
    dlg.resize(_DIALOG_SIZE)
    # Qt's (non-native) dialog uses fixed, narrow columns: let Name take the
    # spare width and size the rest to their contents.
    tree = dlg.findChild(QTreeView, "treeView")
    if tree is not None:
        head = tree.header()
        head.setStretchLastSection(False)
        head.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, head.count()):
            head.setSectionResizeMode(col, QHeaderView.ResizeToContents)
    splitter = dlg.findChild(QSplitter, "splitter")
    if splitter is not None:
        splitter.setSizes([180, _DIALOG_SIZE.width() - 180])
    if dlg.exec() != QFileDialog.Accepted:
        return []
    return dlg.selectedFiles()


def _get_open_file_names(parent, caption, directory="", name_filter=""):
    files = _run_dialog(parent, caption, directory, name_filter, QFileDialog.ExistingFiles)
    return files, name_filter


def _get_open_file_name(parent, caption, directory="", name_filter=""):
    files = _run_dialog(parent, caption, directory, name_filter, QFileDialog.ExistingFile)
    return (files[0] if files else ""), name_filter


def _get_save_file_name(parent, caption, directory="", name_filter=""):
    files = _run_dialog(
        parent, caption, directory, name_filter, QFileDialog.AnyFile, save=True
    )
    return (files[0] if files else ""), name_filter


def _get_existing_directory(parent, caption, directory=""):
    files = _run_dialog(parent, caption, directory, "", QFileDialog.Directory)
    return files[0] if files else ""


# ── worker thread ──────────────────────────────────────────────────────────


class _Worker(QThread):
    """Run a download / processing / probe task off the main thread."""

    finished = Signal(object)
    error = Signal(str)
    cancelled = Signal()
    progress = Signal(str, object)
    log = Signal(str)
    probed = Signal(object)
    probe_error = Signal(str)

    def __init__(self, task: str, **kwargs) -> None:
        super().__init__()
        self._task = task
        self._kw = kwargs
        self._cancel = False

    def cancel(self) -> None:
        """Ask the task to stop at its next progress update."""
        self._cancel = True

    def _cb_progress(self, msg: str, pct: float | None) -> None:
        if self._cancel:
            raise DownloadCancelled()
        self.progress.emit(msg, pct)

    def _cb_log(self, msg: str) -> None:
        self.log.emit(msg)

    def run(self) -> None:
        try:
            if self._task == "probe":
                result = probe(
                    self._kw["url"],
                    thumb_dir=self._kw.get("thumb_dir"),
                    translate=self._kw.get("translate"),
                )
                if result.get("is_playlist") is False and result.get("dislike_count") is None:
                    dislike = fetch_dislikes(result.get("id") or "")
                    if dislike is not None:
                        result["dislike_count"] = dislike
                self.probed.emit(result)
                return
            common = {
                "video_filter": self._kw.get("video_filter"),
                "speed": self._kw.get("speed"),
                "quality": self._kw.get("quality"),
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
            elif self._task == "download_playlist":
                result = download_playlist(
                    self._kw["url"], self._kw["output_dir"], self._kw["fmt"],
                    quality=self._kw.get("quality"),
                    on_progress=self._cb_progress,
                    on_log=self._cb_log,
                    translate=self._kw.get("translate"),
                )
            elif self._task == "job":
                result = run_job(
                    self._kw["job"],
                    on_progress=self._cb_progress,
                    on_log=self._cb_log,
                    translate=self._kw.get("translate"),
                )
            elif self._task == "compose_video":
                result = compose_video(
                    self._kw["clips"], self._kw["output_file"],
                    resolution=self._kw.get("resolution", "auto"),
                    subtitles=self._kw.get("subtitles"),
                    subtitle_style=self._kw.get("subtitle_style"),
                    music=self._kw.get("music"),
                    images=self._kw.get("images"),
                    quality=self._kw.get("render_quality", "balanced"),
                    on_progress=self._cb_progress,
                    on_log=self._cb_log,
                    translate=self._kw.get("translate"),
                )
            elif self._task == "transcribe":
                result = transcribe(
                    self._kw["sources"], _config_dir() / "models",
                    language=self._kw.get("language", "auto"),
                    size=self._kw.get("size", "balanced"),
                    on_progress=self._cb_progress,
                    on_log=self._cb_log,
                    translate=self._kw.get("translate"),
                )
            elif self._task == "compose_audio":
                result = compose_audio(
                    self._kw["clips"], self._kw["output_file"],
                    crossfade=self._kw.get("crossfade", 0.0),
                    bitrate=self._kw.get("bitrate"),
                    on_progress=self._cb_progress,
                    on_log=self._cb_log,
                    translate=self._kw.get("translate"),
                )
            else:
                raise RuntimeError(f"Unknown task: {self._task}")
            self.finished.emit(result)
        except DownloadCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001
            if self._task == "probe":
                self.probe_error.emit(str(exc))
            else:
                self.error.emit(str(exc))


# ── sidebar ────────────────────────────────────────────────────────────────

_NAV_ITEMS: list[tuple[str, str]] = [
    ("download", "Download"),
    ("film", "Studio"),
    ("gear", "Settings"),
]

# page index -> (title key, subtitle key) for the header above each page
_PAGE_HEADERS: list[tuple[str, str]] = [
    ("Download", "Grab videos, playlists and music from YouTube"),
    ("Studio", "Join clips, add subtitles and background music"),
    ("Settings", "Appearance, language and app info"),
]

PAGE_DOWNLOAD, PAGE_STUDIO, PAGE_SETTINGS = range(3)

_THUMB_SIZE = QSize(320, 180)


class _Sidebar(QWidget):
    """Compact navigation rail: logo, then icon-over-label page buttons."""

    page_changed = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(84)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 14, 8, 12)
        lay.setSpacing(6)

        icon = QLabel()
        icon.setObjectName("brand_icon")
        icon.setAlignment(Qt.AlignCenter)
        pm = _brand_pixmap(40)
        if pm:
            icon.setPixmap(pm)
        icon.setToolTip(f"VidGrab v{__version__}")
        lay.addWidget(icon)
        divider = QFrame()
        divider.setObjectName("brand_divider")
        divider.setFrameShape(QFrame.NoFrame)
        lay.addWidget(divider)
        lay.addSpacing(6)

        self._buttons: list[QToolButton] = []
        for idx, (_kind, _key) in enumerate(_NAV_ITEMS):
            btn = QToolButton()
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setIconSize(QSize(24, 24))
            btn.setFixedSize(68, 62)
            btn.setCursor(QCursor(_HAND))
            if idx == 0:
                btn.setChecked(True)
            btn.toggled.connect(
                lambda checked, i=idx: self.page_changed.emit(i) if checked else None
            )
            lay.addWidget(btn, alignment=Qt.AlignHCenter)
            self._buttons.append(btn)

        lay.addStretch()
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("sidebar_foot")
        ver.setAlignment(Qt.AlignCenter)
        lay.addWidget(ver)

    def retranslate(self, t, theme: str = "dark") -> None:
        pal = _PALETTES[theme]
        for btn, (kind, key) in zip(self._buttons, _NAV_ITEMS):
            if btn.isChecked():
                color = pal["ACCENT_HI"] if theme == "dark" else pal["ACCENT"]
            else:
                color = pal["TEXT_MUTED"]
            btn.setIcon(_icon(kind, color, 24))
            btn.setText(t(key))
            btn.setToolTip(
                t(
                    {
                        "download": "tooltip_page_download",
                        "film": "tooltip_page_studio",
                        "gear": "tooltip_page_settings",
                    }[kind]
                )
            )

    def select(self, idx: int) -> None:
        self._buttons[idx].setChecked(True)


# ── page fade animation ────────────────────────────────────────────────────


class _FadeStack(QStackedWidget):
    """QStackedWidget for the main pages.

    Pages switch instantly. A per-page opacity fade was removed: a
    QGraphicsOpacityEffect over the stack forces a software compositing
    pass that can draw all pages on top of one another (and destroy
    performance) on systems with broken GL."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

    def setCurrentIndex(self, idx: int) -> None:
        super().setCurrentIndex(idx)


class _WheelGuard(QObject):
    """The mouse wheel never changes a dropdown, number box or slider — it
    scrolls the panel underneath instead (no accidental edits while scrolling)."""

    _KINDS = (QComboBox, QAbstractSpinBox, QSlider)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Wheel and isinstance(obj, self._KINDS):
            event.ignore()  # handled here, but unaccepted: Qt passes it to the parent
            return True
        return False


_wheel_guard: _WheelGuard | None = None


def _install_wheel_guard() -> None:
    global _wheel_guard
    app = QApplication.instance()
    if app is not None and _wheel_guard is None:
        _wheel_guard = _WheelGuard(app)
        app.installEventFilter(_wheel_guard)


# ── main window ────────────────────────────────────────────────────────────


class VidGrabWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        _install_wheel_guard()
        cfg = _load_config()
        self._settings = cfg
        self._i18n_widgets: list[tuple[QWidget, str, str]] = []
        self._finished_since_idle = 0
        self._theme = cfg["theme"]
        self._lang = cfg["lang"]
        self._t = make_translator(self._lang)
        self._busy = False
        self._internet_online: bool | None = None
        self._worker: _Worker | None = None  # Studio render
        self._dl_worker: _Worker | None = None  # current queued download
        self._dl_item: DownloadItem | None = None
        self._queue: list[DownloadItem] = []
        self._probe_cache: dict[str, dict] = {}  # url -> video info
        self._probe_errors: dict[str, str] = {}
        self._link_rows: dict[str, tuple[QListWidgetItem, LinkRow]] = {}
        self._card_titles: list[tuple[QLabel, str]] = []
        self._probe_data: dict | None = None

        self.setWindowTitle("VidGrab")
        self.setMinimumSize(1180, 820)
        self.resize(1500, 1000)
        self.setAcceptDrops(True)

        self._apply_theme()
        self._build_ui()
        self._setup_probe()
        self._load_history()
        self._apply_language()
        self._apply_download_defaults()
        self._studio.set_default_resolution(self.setting("studio_resolution"))
        self._update_ffmpeg_status()
        self._start_internet_check()
        self._setup_shortcuts()
        if QApplication.platformName() != "offscreen":  # not in tests / scripts
            QTimer.singleShot(600, self._offer_recovery)

    # ── ui construction ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        body = QHBoxLayout(central)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar = _Sidebar()
        self._sidebar.page_changed.connect(self._switch_page)
        body.addWidget(self._sidebar)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        content.addWidget(self._build_header())

        self._stack = _FadeStack()
        self._stack.addWidget(self._build_download_form())
        self._studio = StudioPage(self)
        self._studio.render_requested.connect(self._start_studio)
        self._studio.cancel_requested.connect(
            lambda: self._worker.cancel() if self._worker is not None else None)
        self._studio.apply_theme(self._theme, _PALETTES[self._theme], _CARD_ACCENTS[self._theme])
        self._stack.addWidget(self._studio)
        self._stack.addWidget(self._build_settings_form())
        content.addWidget(self._stack, stretch=4)
        body.addLayout(content, stretch=1)

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
        w.setAttribute(Qt.WA_StyledBackground, True)
        w.setFixedHeight(64)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(24, 8, 24, 8)

        col = QVBoxLayout()
        col.setSpacing(2)
        self._page_title = QLabel()
        self._page_title.setObjectName("page_title")
        self._page_sub = QLabel()
        self._page_sub.setObjectName("page_sub")
        col.addWidget(self._page_title)
        col.addWidget(self._page_sub)
        lay.addLayout(col)
        lay.addStretch()

        self._theme_btn = QPushButton()
        self._theme_btn.setObjectName("theme_btn")
        self._theme_btn.setFixedHeight(28)
        self._theme_btn.setCursor(QCursor(_HAND))
        self._theme_btn.clicked.connect(self._toggle_theme)
        lay.addWidget(self._theme_btn)
        return w

    # ── download form ──────────────────────────────────────────────────

    def _card(self, text: str, objname: str, kind: str) -> tuple[QGroupBox, QLabel, QVBoxLayout]:
        """Create a card (QGroupBox) with an accent header label + content layout.

        Returns (groupbox, title_label, content_vbox)."""
        g = QGroupBox()
        g.setObjectName(objname)
        vl = QVBoxLayout(g)
        vl.setContentsMargins(16, 12, 16, 14)
        vl.setSpacing(9)
        head = QHBoxLayout()
        head.setSpacing(8)
        bar = QFrame()
        bar.setObjectName("card_bar")
        t = QLabel(text)
        t.setProperty("card_bar", bar)
        self._style_card_title(t, kind)
        head.addWidget(bar, alignment=Qt.AlignVCenter)
        head.addWidget(t)
        head.addStretch()
        vl.addLayout(head)
        self._card_titles.append((t, kind))
        return g, t, vl

    def _style_card_title(self, label: QLabel, kind: str) -> None:
        accent = _CARD_ACCENTS[self._theme][kind]
        label.setStyleSheet(
            f"color:{accent}; background-color:transparent; font-size:11px; "
            "font-weight:800; letter-spacing:1.5px; margin:0; padding:0;"
        )
        bar = label.property("card_bar")
        if bar is not None:
            bar.setStyleSheet(
                "background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                f"stop:0 {accent}, stop:1 {_PALETTES[self._theme]['ACCENT2']});"
            )

    def _build_download_form(self) -> QWidget:
        """Link bar (paste + Download) on top, then the video card beside the
        options card. The Download button lives in the link bar so the whole
        flow reads left to right, top to bottom."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 16, 24, 8)
        lay.setSpacing(14)

        # ── link bar ──
        bar = QWidget()
        bar.setObjectName("url_bar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 10, 10, 10)
        bl.setSpacing(10)
        self._dl_source_title = QLabel()  # kept for _apply_language
        self._dl_source_title.hide()
        self._url = QLineEdit()
        self._url.setObjectName("url_input")
        self._url.setPlaceholderText("Paste a YouTube link…")
        self._url.setClearButtonEnabled(True)
        self._url.returnPressed.connect(self._start_action)
        bl.addWidget(self._url, stretch=1)
        pb = QPushButton("Paste")
        pb.setObjectName("secondary")
        pb.setFixedHeight(44)
        pb.setMinimumWidth(84)
        pb.setCursor(QCursor(_HAND))
        pb.clicked.connect(self._paste_url)
        bl.addWidget(pb)
        self._dl_paste = pb
        self._action = QPushButton("⬇  Download")
        self._action.setObjectName("primary")
        self._action.setProperty("compact", True)
        self._action.setFixedHeight(48)
        self._action.setMinimumWidth(190)
        self._action.setCursor(QCursor(_HAND))
        self._action.setEnabled(False)
        self._action.clicked.connect(self._start_action)
        bl.addWidget(self._action)
        lay.addWidget(bar)

        body = QHBoxLayout()
        body.setSpacing(14)

        # ── video card ──
        info, info_title, card_lay = self._card("VIDEO INFO", "info_card", "source")
        self._dl_info_title = info_title
        # two views: one video's details, or a list when several links are pasted
        self._info_stack = QStackedWidget()
        card_lay.addWidget(self._info_stack, stretch=1)
        single = QWidget()
        ivl = QVBoxLayout(single)
        ivl.setContentsMargins(0, 0, 0, 0)
        ivl.setSpacing(6)
        self._info_stack.addWidget(single)
        multi = QWidget()
        mvl = QVBoxLayout(multi)
        mvl.setContentsMargins(0, 0, 0, 0)
        mvl.setSpacing(6)
        self._multi_lbl = QLabel()
        self._multi_lbl.setObjectName("info_name")
        mvl.addWidget(self._multi_lbl)
        self._link_list = QListWidget()
        self._link_list.setObjectName("dl_list")
        self._link_list.setSelectionMode(QListWidget.NoSelection)
        self._link_list.setFocusPolicy(Qt.NoFocus)
        self._link_list.setSpacing(2)
        self._link_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        mvl.addWidget(self._link_list, stretch=1)
        self._info_stack.addWidget(multi)
        self._info_thumb = QLabel()
        self._info_thumb.setObjectName("info_thumb")
        self._info_thumb.setFixedSize(_THUMB_SIZE)
        self._info_thumb.setAlignment(Qt.AlignCenter)
        ivl.addWidget(self._info_thumb, alignment=Qt.AlignHCenter)
        self._info_name = QLabel()
        self._info_name.setObjectName("info_name")
        self._info_name.setWordWrap(True)
        self._info_meta = QLabel()
        self._info_meta.setObjectName("info_meta")
        self._info_meta.setWordWrap(True)
        self._playlist_cb = QCheckBox()
        self._playlist_cb.setCursor(QCursor(_HAND))
        self._playlist_cb.hide()
        ivl.addSpacing(4)
        ivl.addWidget(self._info_name)
        ivl.addWidget(self._info_meta)
        ivl.addWidget(self._playlist_cb)
        ivl.addStretch()
        body.addWidget(info, stretch=5)

        # ── options card: one labelled row per setting ──
        opts, _opts_title, ol = self._card("OPTIONS", "options_card", "format")
        self._dl_options_title = _opts_title
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        def cap(attr: str) -> QLabel:
            lbl = QLabel()
            lbl.setObjectName("field_cap")
            setattr(self, attr, lbl)
            return lbl

        self._mp4 = _colored_check("MP4 (video)", "#10b981")
        self._mp4.setChecked(True)
        self._mp3 = _colored_check("MP3 (audio)", "#f59e0b")
        self._mp4.toggled.connect(self._populate_quality)
        self._mp3.toggled.connect(self._populate_quality)
        fr = QHBoxLayout()
        fr.setSpacing(16)
        fr.addWidget(self._mp4)
        fr.addWidget(self._mp3)
        fr.addStretch()
        grid.addWidget(cap("_dl_format_title"), 0, 0)
        grid.addLayout(fr, 0, 1)

        self._quality_lbl = cap("_quality_lbl")
        self._quality = QComboBox()
        self._quality.setCursor(QCursor(_HAND))
        self._quality.setMinimumWidth(170)
        qr = QHBoxLayout()
        qr.addWidget(self._quality)
        qr.addStretch()
        grid.addWidget(self._quality_lbl, 1, 0)
        grid.addLayout(qr, 1, 1)
        self._populate_quality()

        self._ts = QLineEdit()
        self._ts.setPlaceholderText("0:00")
        self._ts.setMaximumWidth(100)
        self._te = QLineEdit()
        self._te.setPlaceholderText("∞")
        self._te.setMaximumWidth(100)
        self._ts_lbl = QLabel("Start:")
        self._te_lbl = QLabel("End:")
        tr = QHBoxLayout()
        tr.setSpacing(8)
        for w in (self._ts_lbl, self._ts):
            tr.addWidget(w)
        tr.addSpacing(8)
        for w in (self._te_lbl, self._te):
            tr.addWidget(w)
        tr.addStretch()
        grid.addWidget(cap("_dl_trim_title"), 2, 0)
        grid.addLayout(tr, 2, 1)

        self._hflip = QCheckBox("Horizontal")
        self._vflip = QCheckBox("Vertical")
        flr = QHBoxLayout()
        flr.setSpacing(16)
        flr.addWidget(self._hflip)
        flr.addWidget(self._vflip)
        flr.addStretch()
        grid.addWidget(cap("_dl_flip_title"), 3, 0)
        grid.addLayout(flr, 3, 1)

        self._speed, _sv, srow = _build_speed_row()
        grid.addWidget(cap("_dl_speed_title"), 4, 0)
        grid.addLayout(srow, 4, 1)

        self._out = QLineEdit(str(default_output_dir()))
        self._out.setClearButtonEnabled(True)
        bb = QPushButton("Browse…")
        bb.setObjectName("secondary")
        bb.setCursor(QCursor(_HAND))
        bb.clicked.connect(lambda: self._browse_folder(self._out))
        self._dl_browse = bb
        sr = QHBoxLayout()
        sr.setSpacing(8)
        sr.addWidget(self._out, stretch=1)
        sr.addWidget(bb)
        self._sub_cb = QCheckBox("Download subtitles")
        self._sub_cb.setCursor(QCursor(_HAND))
        self._sub_lang = QComboBox()
        self._sub_mode = QComboBox()
        for w in (self._sub_lang, self._sub_mode):
            w.setCursor(QCursor(_HAND))
            w.setEnabled(False)
        self._sub_cb.toggled.connect(self._sync_sub_options)
        self._mp4.toggled.connect(self._sync_sub_options)
        self._mp3.toggled.connect(self._sync_sub_options)
        subr = QHBoxLayout()
        subr.setSpacing(10)
        subr.addWidget(self._sub_cb)
        subr.addWidget(self._sub_lang)
        subr.addWidget(self._sub_mode)
        subr.addStretch()
        grid.addWidget(cap("_dl_subs_title"), 5, 0)
        grid.addLayout(subr, 5, 1)

        grid.addWidget(cap("_dl_save_title"), 6, 0)
        grid.addLayout(sr, 6, 1)
        ol.addLayout(grid)
        ol.addStretch()
        body.addWidget(opts, stretch=6)
        lay.addLayout(body)
        # progress + log fill the rest of the page
        self._bottom = self._build_bottom()
        lay.addWidget(self._bottom, stretch=1)
        return _wrap_scroll(page)

    # ── settings form ──────────────────────────────────────────────────


    def _build_settings_form(self) -> QWidget:
        """Appearance + download defaults (left); Studio, storage, about (right)."""
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(24, 14, 24, 10)
        outer.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(12)
        right = QVBoxLayout()
        right.setSpacing(12)
        outer.addLayout(left, stretch=1)
        outer.addLayout(right, stretch=1)

        # appearance ----------------------------------------------------------
        g1, a_title, fl = self._card("APPEARANCE", "settings_card", "settings")
        self._settings_title = a_title
        afl = QFormLayout()
        afl.setSpacing(8)
        self._theme_combo = QComboBox()
        self._theme_combo.setCursor(QCursor(_HAND))
        self._theme_combo.activated.connect(
            lambda _i: self._set_theme(self._theme_combo.currentData() or "dark")
        )
        self._lang_combo = QComboBox()
        self._lang_combo.setCursor(QCursor(_HAND))
        for code, name in LANGUAGES.items():
            label = name.split(" ", 1)[1] if " " in name else name
            self._lang_combo.addItem(_flag_icon(code), label, code)
        idx = self._lang_combo.findData(self._lang)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.currentIndexChanged.connect(self._on_lang_change)
        self._theme_lbl = QLabel("Theme:")
        self._lang_lbl = QLabel("Language:")
        afl.addRow(self._theme_lbl, self._theme_combo)
        afl.addRow(self._lang_lbl, self._lang_combo)
        fl.addLayout(afl)
        left.addWidget(g1)

        # download defaults ---------------------------------------------------
        g2, t2, dl = self._card("DOWNLOAD DEFAULTS", "settings_card", "format")
        self._trw(t2, "DOWNLOAD DEFAULTS")
        form = QFormLayout()
        form.setSpacing(9)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self._set_out = QLineEdit(self.setting("out_dir") or str(default_output_dir()))
        self._set_out.editingFinished.connect(
            lambda: self._set_default_dir(self._set_out.text().strip()))
        browse = QPushButton()
        browse.setObjectName("secondary")
        browse.setCursor(QCursor(_HAND))
        browse.clicked.connect(self._browse_default_dir)
        self._trw(browse, "Browse…")
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._set_out, stretch=1)
        row.addWidget(browse)
        form.addRow(self._trw(QLabel(), "Save to:"), row)
        self._set_fmt = QComboBox()
        self._set_vq = QComboBox()
        self._set_aq = QComboBox()
        self._set_sub_lang = QComboBox()
        self._set_sub_mode = QComboBox()
        self._set_name = QComboBox()
        for combo in (self._set_fmt, self._set_vq, self._set_aq, self._set_sub_lang,
                      self._set_sub_mode, self._set_name):
            combo.setCursor(QCursor(_HAND))
        self._set_fmt.activated.connect(lambda _i: self._default_changed("fmt", self._set_fmt))
        self._set_vq.activated.connect(
            lambda _i: self._default_changed("video_quality", self._set_vq))
        self._set_aq.activated.connect(
            lambda _i: self._default_changed("audio_quality", self._set_aq))
        self._set_sub_lang.activated.connect(
            lambda _i: self._default_changed("sub_lang", self._set_sub_lang))
        self._set_sub_mode.activated.connect(
            lambda _i: self._default_changed("sub_mode", self._set_sub_mode))
        self._set_name.activated.connect(
            lambda _i: self._default_changed("name_template", self._set_name))
        form.addRow(self._trw(QLabel(), "Format:"), self._set_fmt)
        form.addRow(self._trw(QLabel(), "Video quality:"), self._set_vq)
        form.addRow(self._trw(QLabel(), "Audio quality:"), self._set_aq)
        self._set_sub = QCheckBox()
        self._set_sub.setCursor(QCursor(_HAND))
        self._set_sub.setChecked(bool(self.setting("sub_enabled")))
        self._set_sub.toggled.connect(lambda on: self._default_changed("sub_enabled", on))
        self._trw(self._set_sub, "Download subtitles")
        sub_row = QHBoxLayout()
        sub_row.setSpacing(8)
        sub_row.addWidget(self._set_sub)
        sub_row.addWidget(self._set_sub_lang, stretch=1)
        sub_row.addWidget(self._set_sub_mode, stretch=1)
        form.addRow(self._trw(QLabel(), "Subtitles:"), sub_row)
        form.addRow(self._trw(QLabel(), "File names:"), self._set_name)
        self._set_name_example = QLabel()
        self._set_name_example.setObjectName("hint")
        form.addRow(QLabel(), self._set_name_example)
        self._set_notify = QCheckBox()
        self._set_notify.setCursor(QCursor(_HAND))
        self._set_notify.setChecked(bool(self.setting("notify")))
        self._set_notify.toggled.connect(lambda on: self.set_setting("notify", on))
        self._trw(self._set_notify, "Play a sound and show a message when downloads finish")
        form.addRow(QLabel(), self._set_notify)
        dl.addLayout(form)
        hint = QLabel()
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        self._trw(hint, "These are the options the Download page starts with; you can still "
                        "change them there for each download.")
        dl.addWidget(hint)
        left.addWidget(g2)
        left.addStretch()

        # studio ----------------------------------------------------------------
        g3, t3, sl = self._card("STUDIO", "settings_card", "clips")
        self._trw(t3, "STUDIO")
        sform = QFormLayout()
        sform.setSpacing(9)
        sform.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self._set_rq = QComboBox()
        self._set_res = QComboBox()
        for combo in (self._set_rq, self._set_res):
            combo.setCursor(QCursor(_HAND))
        self._set_rq.activated.connect(
            lambda _i: self._default_changed("render_quality", self._set_rq))
        self._set_res.activated.connect(
            lambda _i: self._default_changed("studio_resolution", self._set_res))
        sform.addRow(self._trw(QLabel(), "Render quality:"), self._set_rq)
        sform.addRow(self._trw(QLabel(), "Default resolution:"), self._set_res)
        sl.addLayout(sform)
        sl.addWidget(self._trw(QLabel(), "Subtitle style presets:"))
        prow = QHBoxLayout()
        prow.setSpacing(8)
        self._set_presets = QListWidget()
        self._set_presets.setObjectName("preset_list")
        self._set_presets.setFixedHeight(86)
        prow.addWidget(self._set_presets, stretch=1)
        delete = QPushButton()
        delete.setObjectName("secondary")
        delete.setCursor(QCursor(_HAND))
        delete.clicked.connect(self._delete_preset_from_settings)
        self._trw(delete, "Delete")
        prow.addWidget(delete, alignment=Qt.AlignTop)
        sl.addLayout(prow)
        phint = QLabel()
        phint.setObjectName("hint")
        phint.setWordWrap(True)
        self._trw(phint, "Save a preset from the subtitle panel in the Studio to reuse fonts, "
                         "colours and position in other projects.")
        sl.addWidget(phint)
        right.addWidget(g3)

        # storage ---------------------------------------------------------------
        g4, t4, stl = self._card("STORAGE", "settings_card", "save")
        self._trw(t4, "STORAGE")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        self._cache_lbl = QLabel()
        self._history_lbl = QLabel()
        self._log_lbl = QLabel()
        rows = (
            (self._cache_lbl, "Clear", self._clear_cache),
            (self._history_lbl, "Clear", self._clear_history),
            (self._log_lbl, "Export…", self._export_log),
        )
        for r, (lbl, key, slot) in enumerate(rows):
            b = QPushButton()
            b.setObjectName("secondary")
            b.setCursor(QCursor(_HAND))
            b.clicked.connect(slot)
            self._trw(b, key)
            grid.addWidget(lbl, r, 0)
            grid.addWidget(b, r, 1)
        stl.addLayout(grid)
        reset = QPushButton()
        reset.setObjectName("secondary")
        reset.setCursor(QCursor(_HAND))
        reset.clicked.connect(self._reset_settings)
        self._trw(reset, "Reset all settings…")
        stl.addWidget(reset, alignment=Qt.AlignLeft)
        right.addWidget(g4)

        # about -----------------------------------------------------------------
        g5, b_title, al = self._card("ABOUT", "settings_card", "settings")
        self._about_title = b_title
        self._about_lbl = QLabel()
        self._about_lbl.setWordWrap(True)
        self._about_lbl.setTextFormat(Qt.RichText)
        al.addWidget(self._about_lbl)
        self._versions_lbl = QLabel()
        self._versions_lbl.setObjectName("hint")
        self._versions_lbl.setTextFormat(Qt.RichText)
        self._versions_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        al.addWidget(self._versions_lbl)
        right.addWidget(g5)
        right.addStretch()
        return _wrap_scroll(page)

    # ── settings helpers ───────────────────────────────────────────────

    def _trw(self, widget, key: str, method: str = "setText"):
        """Register *widget* so _apply_language re-applies t(key) to it."""
        self._i18n_widgets.append((widget, key, method))
        getattr(widget, method)(self._t(key))
        return widget

    def setting(self, key: str):
        return self._settings.get(key, DEFAULT_SETTINGS.get(key))

    def set_setting(self, key: str, value) -> None:
        self._settings[key] = value
        _save_config(self._theme, self._lang, {key: value})

    def _fill_settings_combos(self) -> None:
        t = self._t
        fill = StudioPage._fill
        fill(self._theme_combo, [(t("Dark"), "dark"), (t("Light"), "light")])
        self._theme_combo.setCurrentIndex(max(0, self._theme_combo.findData(self._theme)))
        fill(self._set_fmt, [("MP4", "mp4"), ("MP3", "mp3"), ("MP4 + MP3", "both")])
        fill(self._set_vq, [(t("Best available"), "")] + [(label, token) for label, token in (
            ("4K (2160p)", "2160p"), ("1440p (QHD)", "1440p"), ("1080p (FHD)", "1080p"),
            ("720p (HD)", "720p"), ("480p (SD)", "480p"), ("360p", "360p"))])
        fill(self._set_aq, [(f"{b} kbps", b) for b in ("320", "256", "192", "128")])
        fill(self._set_sub_lang, [(t("Traditional Chinese"), "zh-Hant"),
                                  (t("Simplified Chinese"), "zh-Hans"),
                                  (t("English"), "en"), (t("Japanese"), "ja")])
        fill(self._set_sub_mode, [(t("Save as .srt file"), "file"),
                                  (t("Burn into video"), "burn")])
        fill(self._set_name, [(t("Title"), "title"), (t("Title [video ID]"), "title_id"),
                              (t("Channel - Title"), "uploader_title"),
                              (t("Upload date + Title"), "date_title")])
        fill(self._set_rq, [(t("Fast (smaller file)"), "fast"), (t("Balanced"), "balanced"),
                            (t("High quality (larger file)"), "high")])
        fill(self._set_res, [
            (t("Same as first clip"), "auto"), (t("1080p landscape (16:9)"), "1080p"),
            (t("720p landscape (16:9)"), "720p"), (t("480p landscape (16:9)"), "480p"),
            (t("Vertical 1080×1920 (9:16)"), "vertical"),
            (t("Square 1080×1080 (1:1)"), "square")])
        for combo, key in ((self._set_fmt, "fmt"), (self._set_vq, "video_quality"),
                           (self._set_aq, "audio_quality"), (self._set_sub_lang, "sub_lang"),
                           (self._set_sub_mode, "sub_mode"), (self._set_name, "name_template"),
                           (self._set_rq, "render_quality"),
                           (self._set_res, "studio_resolution")):
            idx = combo.findData(self.setting(key) or "")
            combo.setCurrentIndex(max(idx, 0))
        self._update_name_example()
        self._refresh_storage()
        self._refresh_presets()

    def _update_name_example(self) -> None:
        examples = {
            "title": "Me at the zoo.mp4",
            "title_id": "Me at the zoo [jNQXAC9IVRw].mp4",
            "uploader_title": "jawed - Me at the zoo.mp4",
            "date_title": "2005-04-24 Me at the zoo.mp4",
        }
        key = self.setting("name_template") or "title"
        self._set_name_example.setText(self._t("e.g. {name}", name=examples.get(key, "")))

    def _default_changed(self, key: str, source) -> None:
        value = source if isinstance(source, bool) else (source.currentData() or None)
        if key in ("fmt", "audio_quality", "sub_lang", "sub_mode", "name_template",
                   "render_quality", "studio_resolution") and value is None:
            value = DEFAULT_SETTINGS[key]
        self.set_setting(key, value)
        if key == "name_template":
            self._update_name_example()
        if key == "studio_resolution":
            self._studio.set_default_resolution(value)
        else:
            self._apply_download_defaults()

    def _apply_download_defaults(self) -> None:
        """Start the Download page from the saved defaults."""
        self._out.setText(self.setting("out_dir") or str(default_output_dir()))
        fmt = self.setting("fmt") or "mp4"
        self._mp4.setChecked(fmt in ("mp4", "both"))
        self._mp3.setChecked(fmt in ("mp3", "both"))
        self._populate_quality()
        want = self.setting("video_quality") if self._mp4.isChecked() \
            else self.setting("audio_quality")
        idx = self._quality.findData(want)
        if idx >= 0:
            self._quality.setCurrentIndex(idx)
        self._sub_cb.setChecked(bool(self.setting("sub_enabled")))
        for combo, key in ((self._sub_lang, "sub_lang"), (self._sub_mode, "sub_mode")):
            idx = combo.findData(self.setting(key))
            if idx >= 0:
                combo.setCurrentIndex(idx)
        self._sync_sub_options()

    def _set_default_dir(self, path: str) -> None:
        self.set_setting("out_dir", path)
        self._out.setText(path or str(default_output_dir()))
        self._studio.out_dir.setText(path or str(default_output_dir()))

    def _browse_default_dir(self) -> None:
        folder = _get_existing_directory(self, self._t("Save to:"), self._set_out.text())
        if folder:
            self._set_out.setText(folder)
            self._set_default_dir(folder)

    # subtitle presets -----------------------------------------------------

    def subtitle_presets(self) -> dict:
        return dict(self.setting("subtitle_presets") or {})

    def save_subtitle_preset(self, name: str, style: dict) -> None:
        presets = self.subtitle_presets()
        presets[name] = style
        self.set_setting("subtitle_presets", presets)
        self._refresh_presets()

    def delete_subtitle_preset(self, name: str) -> None:
        presets = self.subtitle_presets()
        presets.pop(name, None)
        self.set_setting("subtitle_presets", presets)
        self._refresh_presets()

    def _refresh_presets(self) -> None:
        self._set_presets.clear()
        names = sorted(self.subtitle_presets())
        for name in names:
            self._set_presets.addItem(name)
        if not names:
            item = QListWidgetItem(self._t("No presets yet"))
            item.setFlags(Qt.NoItemFlags)
            self._set_presets.addItem(item)
        self._studio.refresh_presets()

    def _delete_preset_from_settings(self) -> None:
        item = self._set_presets.currentItem()
        if item is not None and item.text() in self.subtitle_presets():
            self.delete_subtitle_preset(item.text())

    # storage ----------------------------------------------------------------

    def _refresh_storage(self) -> None:
        cache = _dir_size(_config_dir() / "cache")
        self._cache_lbl.setText(self._t("Thumbnail cache: {size}", size=human_size(cache)))
        done = sum(1 for i in self._queue if i.status == DONE)
        self._history_lbl.setText(self._t("Download history: {n} items", n=done))
        log = _config_dir() / "vidgrab.log"
        size = log.stat().st_size if log.is_file() else 0
        self._log_lbl.setText(self._t("Log file: {size}", size=human_size(size)))

    def _clear_cache(self) -> None:
        shutil.rmtree(_config_dir() / "cache", ignore_errors=True)
        self._refresh_storage()

    def _clear_history(self) -> None:
        self._clear_finished()
        self._refresh_storage()

    def _export_log(self) -> None:
        log = _config_dir() / "vidgrab.log"
        if not log.is_file():
            QMessageBox.information(self, self._t("Export…"), self._t("The log is empty."))
            return
        start = str(Path(self._start_dir("Desktop", "Downloads")) / "vidgrab.log")
        path, _ = _get_save_file_name(self, self._t("Export…"), start, "Log (*.log *.txt)")
        if path:
            shutil.copy2(log, path)

    def _reset_settings(self) -> None:
        answer = QMessageBox.question(
            self, self._t("Reset all settings…"),
            self._t("Reset every setting (including subtitle presets) to its default? "
                    "Downloaded files and the download history are kept."),
        )
        if answer != QMessageBox.Yes:
            return
        try:
            (_config_dir() / "config.json").unlink(missing_ok=True)
        except OSError:
            pass
        self._settings = _load_config()
        self._set_out.setText(str(default_output_dir()))
        self._set_sub.setChecked(False)
        self._set_notify.setChecked(True)
        self._fill_settings_combos()
        self._apply_download_defaults()
        self._studio.set_default_resolution("auto")
        self._studio.out_dir.setText(str(default_output_dir()))
        if self._theme != "dark":
            self._set_theme("dark")
        if self._lang != "en":
            self._lang_combo.setCurrentIndex(self._lang_combo.findData("en"))

    # downloads-finished notification -------------------------------------------

    def _notify_downloads_done(self, count: int) -> None:
        if not self.setting("notify"):
            return
        msg = self._t("{n} downloads finished.", n=count)
        self._statusbar.showMessage(msg, 10000)
        QApplication.alert(self)  # flash the taskbar entry
        if _QT_MULTIMEDIA_OK:
            # headless (tests, scripts): never make a sound on the speakers
            chime = _chime_path() if QApplication.platformName() != "offscreen" else None
            if chime is not None:
                from PySide6.QtMultimedia import QSoundEffect

                self._chime = QSoundEffect(self)
                self._chime.setSource(QUrl.fromLocalFile(str(chime)))
                self._chime.setVolume(0.6)
                self._chime.play()
        if QSystemTrayIcon.isSystemTrayAvailable():
            if getattr(self, "_tray", None) is None:
                self._tray = QSystemTrayIcon(_app_icon(), self)
                self._tray.show()
            self._tray.showMessage("VidGrab", msg, _app_icon(), 6000)

    # ── shared bottom (log + progress + button) ────────────────────────

    def _build_bottom(self) -> QWidget:
        """Downloads card: the queue on top, recent downloads below it."""
        g, title, ll = self._card("DOWNLOADS", "downloads_card", "settings")
        self._log_title = title
        tools = QHBoxLayout()
        tools.setSpacing(10)
        tools.addStretch()
        self._queue_lbl = QLabel()
        self._queue_lbl.setObjectName("status")
        tools.addWidget(self._queue_lbl)
        self._clear_done_btn = QPushButton()
        self._clear_done_btn.setObjectName("secondary")
        self._clear_done_btn.setCursor(QCursor(_HAND))
        self._clear_done_btn.clicked.connect(self._clear_finished)
        tools.addWidget(self._clear_done_btn)
        # put the tools on the card's title row
        ll.itemAt(0).layout().addLayout(tools)
        self._downloads = DownloadsPanel(self._t, lambda kind: _icon(kind, "#7b80aa", 28))
        self._downloads.action.connect(self._on_download_action)
        ll.addWidget(self._downloads, stretch=1)
        g.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return g

    # ── page switching ─────────────────────────────────────────────────



    def _switch_page(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)
        # Force a full repaint: on some Wayland/software renderers the
        # previous page's pixels are left in the framebuffer, making pages
        # look like they overlap ("collapsed together").
        self._stack.repaint()
        self._update_page_header()
        # the log / progress / Download panel belongs to the Download page;
        # the Studio has its own toolbar with Render + progress
        self._bottom.setVisible(idx == PAGE_DOWNLOAD)
        if idx == PAGE_DOWNLOAD:
            self._action.setText(self._t("\u2b07  Download"))
        self._refresh_btn()
        self._sidebar.retranslate(self._t, self._theme)

    def _update_page_header(self) -> None:
        title, sub = _PAGE_HEADERS[self._stack.currentIndex()]
        self._page_title.setText(self._t(title))
        self._page_sub.setText(self._t(sub))

    # ── theme ──────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        check = _checkmark_path()
        qss = _THEMES[self._theme]
        muted = _PALETTES[self._theme]["TEXT_MUTED"]
        qss = qss.replace("@ARROW_DOWN@", _chevron_path(muted, down=True))
        qss = qss.replace("@ARROW_UP@", _chevron_path(muted, down=False))
        qss = qss.replace("@FONT_CHAIN@", _font_chain(self._lang))
        self.setStyleSheet(qss.replace("@CHECK@", check))
        app = QApplication.instance()
        if app is not None:
            app.setPalette(_qpalette(self._theme))
        for label, kind in self._card_titles:
            self._style_card_title(label, kind)
        if hasattr(self, "_studio"):
            self._studio.apply_theme(
                self._theme, _PALETTES[self._theme], _CARD_ACCENTS[self._theme]
            )

    def _toggle_theme(self) -> None:
        self._set_theme("light" if self._theme == "dark" else "dark")

    def _set_theme(self, name: str) -> None:
        if name not in _THEMES:
            return
        self._theme = name
        self._apply_theme()
        self._theme_combo.blockSignals(True)
        self._theme_combo.setCurrentIndex(max(0, self._theme_combo.findData(self._theme)))
        self._theme_combo.blockSignals(False)
        self._apply_language()
        _save_config(self._theme, self._lang)

    # ── language ───────────────────────────────────────────────────────

    def _on_lang_change(self) -> None:
        self._lang_combo.hidePopup()
        code = self._lang_combo.currentData()
        if code and code != self._lang:
            self._lang = code
            self._t = make_translator(code)
            try:
                self._apply_language()
                self._apply_theme()
                _save_config(self._theme, self._lang)
            finally:
                # Re-applying the global stylesheet can leave the popup stuck
                # open on some platforms; always force it closed afterwards.
                self._lang_combo.hidePopup()
        self._lang_combo.view().scrollTo(
            self._lang_combo.model().index(self._lang_combo.currentIndex(), 0)
        )

    def _apply_language(self) -> None:
        t = self._t
        self._sidebar.retranslate(t, self._theme)
        self._theme_btn.setText(
            t("\u263e Dark") if self._theme == "light" else t("\u2600 Light")
        )
        self._theme_btn.setToolTip(t("tooltip_switch_theme"))
        self._action.setToolTip(t("tooltip_action_download"))
        self._update_page_header()
        self._studio.retranslate()
        # download page
        self._dl_source_title.setText(t("SOURCE"))
        self._dl_options_title.setText(t("OPTIONS"))
        self._dl_info_title.setText(t("VIDEO INFO"))
        self._dl_format_title.setText(t("FORMAT"))
        self._dl_flip_title.setText(t("FLIP"))
        self._dl_trim_title.setText(t("TRIM"))
        self._dl_speed_title.setText(t("SPEED"))
        self._dl_save_title.setText(t("SAVE TO"))
        self._url.setPlaceholderText(t("Paste a YouTube link\u2026"))
        if self._probe_data is not None:
            self._render_info(self._probe_data)
        else:
            self._info_meta.setText(
                t("Paste a YouTube link to see its details\u2026")
            )
        self._hflip.setText(t("Horizontal"))
        self._vflip.setText(t("Vertical"))
        self._mp4.setText(t("MP4 (video)"))
        self._mp3.setText(t("MP3 (audio)"))
        self._ts_lbl.setText(t("Start:"))
        self._te_lbl.setText(t("End:"))
        self._dl_paste.setText(t("Paste"))
        self._dl_browse.setText(t("Browse\u2026"))
        self._dl_paste.setToolTip(t("tooltip_paste"))
        self._dl_browse.setToolTip(t("tooltip_browse_out"))
        self._quality_lbl.setText(t("Quality:").rstrip(":：").upper())
        self._populate_quality()
        # settings page
        self._settings_title.setText(t("APPEARANCE"))
        self._theme_lbl.setText(t("Theme:"))
        self._lang_lbl.setText(t("Language:"))
        self._about_title.setText(t("ABOUT"))
        self._about_lbl.setText(
            t("about_text", ver=__version__)
        )
        for widget, key, method in self._i18n_widgets:
            getattr(widget, method)(t(key))
        self._fill_settings_combos()
        self._versions_lbl.setText(
            "<table cellspacing='4'>" + "".join(
                f"<tr><td>{name}</td><td>&nbsp;&nbsp;<b>{ver}</b></td></tr>"
                for name, ver in _versions()) + "</table>")
        # bottom
        self._log_title.setText(t("DOWNLOADS"))
        self._clear_done_btn.setText(t("Clear finished"))
        self._downloads.set_translator(t)
        for _item, row in self._link_rows.values():
            row._t = t
            row.refresh()
        if self._info_stack.currentIndex() == 1:
            self._multi_lbl.setText(t("{n} links ready to download", n=len(self._link_rows)))
        self._update_queue_summary()
        self._sub_cb.setText(t("Download subtitles"))
        self._dl_subs_title.setText(t("SUBTITLES"))
        self._fill_sub_options()
        if not self._dl_worker:
            self._action.setText(t("\u2b07  Download"))
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
        if self._stack.currentIndex() == PAGE_STUDIO:  # Ctrl+V there pastes Studio items
            self._studio.paste()
            return
        text = QApplication.clipboard().text()
        if text:
            links = re.findall(r"https?://\S+", text)
            self._url.setText(" ".join(links) if len(links) > 1 else text.strip())

    # ── URL auto-detect / info card ───────────────────────────────────────

    def _setup_probe(self) -> None:
        """Debounce URL edits; fetching metadata starts ~700 ms after the
        user stops typing (or pastes a link)."""
        self._probe_token = 0
        self._probe_workers: list[_Worker] = []
        self._probe_timer = QTimer(self)
        self._probe_timer.setSingleShot(True)
        self._probe_timer.setInterval(700)
        self._probe_timer.timeout.connect(self._start_probe)
        self._url.textChanged.connect(self._on_url_changed)

    def _on_url_changed(self, text: str) -> None:
        # Ctrl+V of a multi-line list keeps line breaks in the one-line box;
        # show the links separated by spaces instead
        if "\n" in text or "\r" in text or "\t" in text:
            clean = " ".join(text.split())
            self._url.blockSignals(True)
            self._url.setText(clean)
            self._url.blockSignals(False)
        self._probe_timer.start()

    def _start_probe(self) -> None:
        self._probe_token += 1
        links = self._links()
        if len(links) > 1:
            self._show_links(links)
            return
        self._info_stack.setCurrentIndex(0)
        url = links[0] if links else ""
        if not url or self._internet_online is not True:
            if not url:
                self._reset_info_card()
            return
        self._info_meta.setText(self._t("Loading\u2026"))
        token = self._probe_token
        worker = _Worker(
            "probe",
            url=url,
            thumb_dir=_thumb_cache_dir(),
            translate=self._t,
        )
        worker.probed.connect(lambda r, u=url: self._probe_cache.__setitem__(u, r))
        worker.probed.connect(lambda r, tok=token: self._on_probe_result(r, tok))
        worker.probe_error.connect(lambda e, tok=token: self._on_probe_error(e, tok))
        worker.finished.connect(lambda w=worker: self._drop_probe_worker(w))
        self._probe_workers.append(worker)
        worker.start()

    def _drop_probe_worker(self, worker: _Worker) -> None:
        if worker in self._probe_workers:
            self._probe_workers.remove(worker)

    def _on_probe_result(self, result: dict, token: int) -> None:
        if token != self._probe_token:
            return
        self._render_info(result)

    # ── several links: one row per link ───────────────────────────────

    def _show_links(self, links: list[str]) -> None:
        """Show every pasted link with its thumbnail / title; fetch the
        details of each link once, in the background."""
        self._probe_data = None
        self._info_stack.setCurrentIndex(1)
        self._multi_lbl.setText(self._t("{n} links ready to download", n=len(links)))
        for url in [u for u in self._link_rows if u not in links]:
            item, _row = self._link_rows.pop(url)
            self._link_list.takeItem(self._link_list.row(item))
        for pos, url in enumerate(links):
            if url in self._link_rows:
                item, _row = self._link_rows[url]
                cur = self._link_list.row(item)
                if cur != pos:
                    widget = self._link_list.itemWidget(item)
                    self._link_list.takeItem(cur)
                    self._link_list.insertItem(pos, item)
                    self._link_list.setItemWidget(item, widget)
                continue
            row = LinkRow(url, self._t, lambda kind: _icon(kind, "#7b80aa", 22))
            row.remove_requested.connect(self._remove_link)
            item = QListWidgetItem()
            item.setSizeHint(QSize(100, 70))
            self._link_list.insertItem(pos, item)
            self._link_list.setItemWidget(item, row)
            self._link_rows[url] = (item, row)
            if url in self._probe_cache:
                row.set_info(self._probe_cache[url])
            elif url in self._probe_errors:
                row.set_info(None, self._probe_errors[url])
            elif self._internet_online:
                self._probe_link(url)

    def _probe_link(self, url: str) -> None:
        worker = _Worker("probe", url=url, thumb_dir=_thumb_cache_dir(), translate=self._t)

        def ok(result: dict, u=url) -> None:
            self._probe_cache[u] = result
            if u in self._link_rows:
                self._link_rows[u][1].set_info(result)

        def fail(msg: str, u=url) -> None:
            self._probe_errors[u] = msg
            if u in self._link_rows:
                self._link_rows[u][1].set_info(None, msg)

        worker.probed.connect(ok)
        worker.probe_error.connect(fail)
        worker.finished.connect(lambda w=worker: self._drop_probe_worker(w))
        self._probe_workers.append(worker)
        worker.start()

    def _remove_link(self, url: str) -> None:
        links = [u for u in self._links() if u != url]
        self._url.setText(" ".join(links))
        self._start_probe()

    def _on_probe_error(self, msg: str, token: int) -> None:
        if token != self._probe_token:
            return
        self._probe_data = None
        self._info_name.setText("")
        self._info_thumb.setPixmap(QPixmap())
        self._playlist_cb.hide()
        self._info_meta.setText(msg)

    def _reset_info_card(self) -> None:
        self._probe_data = None
        self._info_stack.setCurrentIndex(0)
        self._info_name.setText("")
        self._info_thumb.setPixmap(QPixmap())
        self._playlist_cb.hide()
        self._info_meta.setText(
            self._t("Paste a YouTube link to see its details\u2026")
        )

    def _render_info(self, result: dict) -> None:
        self._probe_data = result
        self._info_name.setText(result.get("title") or "")
        meta: list[str] = []
        uploader = result.get("uploader") or ""
        if uploader:
            meta.append(uploader)
        duration = result.get("duration")
        if duration:
            meta.append(_fmt_duration(duration))
        if result.get("is_playlist"):
            count = result.get("playlist_count")
            if count:
                meta.append(self._t("{count} videos", count=count))
                self._playlist_cb.setText(
                    self._t("Download playlist ({count} videos)", count=count)
                )
            else:
                self._playlist_cb.setText(self._t("Download playlist"))
            self._playlist_cb.setVisible(True)
        else:
            formats = result.get("formats") or []
            if formats:
                top = formats[0].split(" \u00b7 ", 1)[0]
                meta.append(self._t("Up to {res}", res=top))
            likes = result.get("like_count")
            if likes:
                meta.append(self._t("Likes: {n}", n=_fmt_count(likes)))
            dislikes = result.get("dislike_count")
            if dislikes:
                meta.append(self._t("Dislikes: {n}", n=_fmt_count(dislikes)))
            comments = result.get("comment_count")
            if comments:
                meta.append(self._t("Comments: {n}", n=_fmt_count(comments)))
            self._playlist_cb.setVisible(False)
        self._info_meta.setText("  \u00b7  ".join(meta))
        self._info_thumb.setPixmap(QPixmap())
        thumb = result.get("thumbnail_local")
        if thumb and Path(thumb).is_file():
            pm = QPixmap(thumb)
            if not pm.isNull():
                scaled = pm.scaled(
                    _THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self._info_thumb.setPixmap(scaled)

    def _start_dir(self, *prefer: str) -> str:
        """Folder file pickers open in: the last folder used, else the first
        existing of ~/<prefer…>, else home (never the app's own folder)."""
        last = getattr(self, "_last_dir", None)
        if last and Path(last).is_dir():
            return last
        for name in prefer:
            d = Path.home() / name
            if d.is_dir():
                return str(d)
        return str(Path.home())

    def _remember_dir(self, path: str) -> None:
        if path:
            self._last_dir = str(Path(path).parent)

    def _browse_folder(self, target: QLineEdit) -> None:
        folder = _get_existing_directory(
            self, "Select Output Folder", target.text()
        )
        if folder:
            target.setText(folder)

    # ── host interface used by StudioPage ──────────────────────────────

    def t(self, key: str, **kw) -> str:
        return self._t(key, **kw)

    def icon(self, kind: str, color: str, size: int = 18) -> QIcon:
        return _icon(kind, color, size)

    def log(self, msg: str) -> None:
        self._append_log(msg)
        self._statusbar.showMessage(msg, 8000)

    def default_output_dir(self) -> Path:
        custom = self.setting("out_dir") if hasattr(self, "_settings") else ""
        return Path(custom) if custom else default_output_dir()

    def pick_files(self, caption: str, prefer: tuple[str, ...], name_filter: str) -> list[str]:
        paths, _ = _get_open_file_names(self, caption, self._start_dir(*prefer), name_filter)
        if paths:
            self._remember_dir(paths[0])
        return paths

    def pick_file(self, caption: str, prefer: tuple[str, ...], name_filter: str) -> str:
        path, _ = _get_open_file_name(self, caption, self._start_dir(*prefer), name_filter)
        if path:
            self._remember_dir(path)
        return path

    def pick_save(self, caption: str, default_name: str, name_filter: str) -> str:
        start = str(Path(self._start_dir("Videos")) / default_name)
        path, _ = _get_save_file_name(self, caption, start, name_filter)
        return path

    def pick_dir(self, caption: str, start: str) -> str:
        return _get_existing_directory(self, caption, start)

    def autosave_path(self) -> Path:
        return _config_dir() / "studio-recovery.vgproj"

    def models_dir(self) -> Path:
        """Where the auto-caption speech models are downloaded to."""
        return _config_dir() / "models"

    def _offer_recovery(self) -> None:
        """VidGrab closed with unsaved Studio work last time: offer it back."""
        path = self.autosave_path()
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            return
        when = data.get("autosaved_at", "")
        answer = QMessageBox.question(
            self, self._t("Recover unsaved work?"),
            self._t("VidGrab closed before your Studio project was saved. Restore the copy "
                    "from {time}?", time=when),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            self._sidebar.select(PAGE_STUDIO)
            self._studio.recover(str(path))
        else:
            path.unlink(missing_ok=True)

    def ffmpeg_ok(self) -> bool:
        if find_ffmpeg():
            return True
        QMessageBox.critical(
            self, self._t("ffmpeg required"),
            self._t("ffmpeg is required for the Studio. "
                    "Install ffmpeg or place it next to the app."),
        )
        return False

    # ── log ────────────────────────────────────────────────────────────

    def _append_log(self, msg: str) -> None:
        """Technical details go to vidgrab.log (not shown in the UI)."""
        try:
            path = _config_dir() / "vidgrab.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file() and path.stat().st_size > 1_000_000:
                path.unlink()
            with path.open("a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}\n")
        except OSError:
            pass

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

    # how often the connection is re-checked (ms): quickly while offline so
    # the app notices a reconnect, more lazily while online
    _RECHECK_OFFLINE_MS = 5_000
    _RECHECK_ONLINE_MS = 30_000

    def _start_internet_check(self) -> None:
        self._pending_status: ConnectionStatus | None = None
        self._probe_thread: threading.Thread | None = None
        # the probe runs on a plain thread; this timer hands its result to the UI
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_internet)
        self._poll.start(200)
        self._recheck = QTimer(self)
        self._recheck.setSingleShot(True)
        self._recheck.timeout.connect(self._do_probe)
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
        came_back = status.online and self._internet_online is False
        self._internet_online = status.online
        self._recheck.start(
            self._RECHECK_ONLINE_MS if status.online else self._RECHECK_OFFLINE_MS
        )
        if came_back and self._url.text().strip() and self._probe_data is None:
            self._probe_timer.start()  # fetch the video info we couldn't before
        if status.online:
            self._net_lbl.setText(f"\u25cf {self._t('Online')}")
            self._label_pill(self._net_lbl, "#10b981")
        else:
            self._net_lbl.setText(f"\u25cb {self._t('Offline')}")
            self._label_pill(self._net_lbl, "#ef4444")
        self._refresh_btn()

    # ── busy / button state ────────────────────────────────────────────

    def _refresh_btn(self) -> None:
        self._action.setEnabled(self._internet_online is True)

    def _set_busy(self, busy: bool) -> None:
        """Studio render in progress (downloads run in their own queue)."""
        self._busy = busy
        self._studio.set_busy(busy)

    # ── start action ───────────────────────────────────────────────────

    def _start_action(self) -> None:
        if self._stack.currentIndex() == PAGE_DOWNLOAD:
            self._start_download()

    def _start_studio(self, task: str, kwargs: dict) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._run(task, **kwargs)

    def _links(self) -> list[str]:
        """Every link in the URL box (several can be pasted at once)."""
        text = self._url.text().strip()
        found = re.findall(r"https?://\S+", text)
        return found or ([text] if text else [])

    def _start_download(self) -> None:
        links = self._links()
        if not links:
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
        fmt = "both" if (self._mp4.isChecked() and self._mp3.isChecked()) else (
            "mp3" if self._mp3.isChecked() else "mp4")
        single_playlist = (len(links) == 1 and self._playlist_cb.isVisible()
                           and self._playlist_cb.isChecked())
        subs = self._sub_lang.currentData() if self._sub_cb.isChecked() else None
        for url in links:
            job = DownloadJob(
                url=url,
                output_dir=self._out.text().strip() or str(default_output_dir()),
                fmt=fmt,
                quality=self._quality.currentData(),
                video_filter=_build_filter(self._hflip, self._vflip),
                speed=_read_speed(self._speed),
                section_start=self._ts.text().strip() or None,
                section_end=self._te.text().strip() or None,
                playlist=single_playlist if len(links) == 1 else (
                    url in self._link_rows and self._link_rows[url][1].whole_playlist()),
                subtitles=subs,
                burn_subtitles=bool(subs) and self._sub_mode.currentData() == "burn"
                and fmt != "mp3",
                name_template=NAME_TEMPLATES.get(self.setting("name_template") or "title",
                                                 NAME_TEMPLATES["title"]),
            )
            item = DownloadItem(job=job)
            probe = (self._probe_data if (len(links) == 1 and self._probe_data)
                     else self._probe_cache.get(url))
            if probe:
                item.title = probe.get("title") or ""
                item.thumb = probe.get("thumbnail_local") or ""
            self._queue.append(item)
            self._downloads.add(item)
            if not probe:
                self._probe_item(item)
        self._probe_token += 1  # ignore an in-flight info fetch for the old link
        self._url.clear()
        self._reset_info_card()
        self._link_list.clear()
        self._link_rows.clear()
        self._update_queue_summary()
        self._run_next_job()

    # ── download queue ────────────────────────────────────────────────

    def _probe_item(self, item: DownloadItem) -> None:
        """Fill in title / thumbnail for a queued link in the background."""
        worker = _Worker("probe", url=item.job.url, thumb_dir=_thumb_cache_dir(),
                         translate=self._t)

        def done(result: dict, it=item) -> None:
            if not it.title:
                it.title = result.get("title") or ""
            it.thumb = it.thumb or result.get("thumbnail_local") or ""
            self._downloads.refresh(it.id)
            if it.status == DONE:
                save_history(self._history_path(), self._queue)

        worker.probed.connect(done)
        worker.finished.connect(lambda w=worker: self._drop_probe_worker(w))
        self._probe_workers.append(worker)
        worker.start()

    def _history_path(self) -> Path:
        return _config_dir() / "history.json"

    def _load_history(self) -> None:
        for item in load_history(self._history_path()):
            self._queue.append(item)
            self._downloads.add(item, top=False)
        self._update_queue_summary()

    def _run_next_job(self) -> None:
        if self._dl_worker is not None and self._dl_worker.isRunning():
            return
        item = next((i for i in self._queue if i.status == QUEUED), None)  # oldest first
        if item is None:
            self._dl_worker = None
            self._update_queue_summary()
            if self._finished_since_idle:
                self._notify_downloads_done(self._finished_since_idle)
                self._finished_since_idle = 0
                self._refresh_storage()
            return
        item.status, item.progress, item.message = RUNNING, None, ""
        self._downloads.refresh(item.id)
        worker = _Worker("job", job=item.job, translate=self._t)
        worker.progress.connect(lambda msg, pct, it=item: self._on_job_progress(it, msg, pct))
        worker.log.connect(self._append_log)
        worker.finished.connect(lambda res, it=item: self._on_job_done(it, res))
        worker.error.connect(lambda msg, it=item: self._on_job_failed(it, msg))
        worker.cancelled.connect(lambda it=item: self._on_job_cancelled(it))
        self._dl_worker = worker
        self._dl_item = item
        self._update_queue_summary()
        worker.start()

    def _on_job_progress(self, item: DownloadItem, msg: str, pct: object) -> None:
        item.message = msg
        item.progress = float(pct) if isinstance(pct, (int, float)) else None
        self._downloads.refresh(item.id)

    def _on_job_done(self, item: DownloadItem, result: object) -> None:
        files = [str(p) for p in (result if isinstance(result, (list, tuple)) else [result])]
        item.status, item.files, item.message = DONE, files, ""
        self._finished_since_idle += 1
        item.finished_at = datetime.now().astimezone().isoformat(timespec="minutes")
        if not item.title and item.media():
            item.title = Path(item.media()[0]).stem
        self._downloads.refresh(item.id)
        save_history(self._history_path(), self._queue)
        self._run_next_job()

    def _on_job_failed(self, item: DownloadItem, msg: str) -> None:
        item.status, item.message = FAILED, msg
        self._append_log(f"Error ({item.job.url}): {msg}")
        self._downloads.refresh(item.id)
        self._run_next_job()

    def _on_job_cancelled(self, item: DownloadItem) -> None:
        item.status, item.message = CANCELLED, ""
        self._downloads.refresh(item.id)
        self._run_next_job()

    def _update_queue_summary(self) -> None:
        waiting = sum(1 for i in self._queue if i.status in (QUEUED, RUNNING))
        done = sum(1 for i in self._queue if i.status == DONE)
        if waiting:
            text = self._t("{n} in queue", n=waiting)
        else:
            text = self._t("{n} downloaded", n=done) if done else ""
        self._queue_lbl.setText(text)
        self._clear_done_btn.setVisible(any(
            i.status in (DONE, FAILED, CANCELLED) for i in self._queue))

    def _on_download_action(self, item_id: str, action: str) -> None:
        item = next((i for i in self._queue if i.id == item_id), None)
        if item is None:
            return
        if action == "cancel" and item is self._dl_item and self._dl_worker is not None:
            self._dl_worker.cancel()
            item.message = self._t("Cancelling…")
            self._downloads.refresh(item.id)
        elif action == "retry":
            item.status, item.progress, item.message = QUEUED, 0.0, ""
            self._downloads.refresh(item.id)
            self._run_next_job()
        elif action == "remove":
            self._queue.remove(item)
            self._downloads.remove(item.id)
            save_history(self._history_path(), self._queue)
        elif action == "studio":
            self._send_to_studio(item)
        self._update_queue_summary()

    def _send_to_studio(self, item: DownloadItem) -> None:
        media = [f for f in item.media() if Path(f).is_file()]
        # MP4 + MP3 pairs: the video is what belongs on the timeline
        videos = [f for f in media if f.lower().endswith(".mp4")] or media
        if not videos:
            return
        first = not self._studio.clips()
        self._studio.add_clips(videos[:1])
        srt = item.subtitles()
        if first and srt and Path(srt).is_file():
            self._studio.load_srt(srt)
        self._sidebar.select(PAGE_STUDIO)

    def _clear_finished(self) -> None:
        for item in [i for i in self._queue if i.status in (DONE, FAILED, CANCELLED)]:
            self._queue.remove(item)
            self._downloads.remove(item.id)
        save_history(self._history_path(), self._queue)
        self._update_queue_summary()

    def _fill_sub_options(self) -> None:
        t = self._t
        for combo, items in (
            (self._sub_lang, [(t("Traditional Chinese"), "zh-Hant"),
                              (t("Simplified Chinese"), "zh-Hans"),
                              (t("English"), "en"), (t("Japanese"), "ja")]),
            (self._sub_mode, [(t("Save as .srt file"), "file"),
                              (t("Burn into video"), "burn")]),
        ):
            prev = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for label, data in items:
                combo.addItem(label, data)
            combo.setCurrentIndex(max(0, combo.findData(prev)))
            combo.blockSignals(False)
        self._sync_sub_options()

    def _sync_sub_options(self) -> None:
        on = self._sub_cb.isChecked()
        self._sub_lang.setEnabled(on)
        # burning needs a video; MP3-only downloads always save a .srt
        video = self._mp4.isChecked()
        self._sub_mode.setEnabled(on and video)
        if not video:
            self._sub_mode.setCurrentIndex(0)

    def _populate_quality(self) -> None:
        """Fill the Quality combo from the checked format (video vs audio)."""
        video = self._mp4.isChecked()
        prev = self._quality.currentData()
        self._quality.blockSignals(True)
        self._quality.clear()
        if video:
            self._quality.addItem(self._t("Best available"), None)
            for label, token in (
                ("4K (2160p)", "2160p"),
                ("1440p (QHD)", "1440p"),
                ("1080p (FHD)", "1080p"),
                ("720p (HD)", "720p"),
                ("480p (SD)", "480p"),
                ("360p", "360p"),
            ):
                self._quality.addItem(label, token)
        else:
            for bitrate in ("320", "256", "192", "128"):
                self._quality.addItem(f"{bitrate} kbps", bitrate)
        idx = self._quality.findData(prev)
        self._quality.setCurrentIndex(idx if idx >= 0 else (2 if not video else 0))
        self._quality.blockSignals(False)

    # ── drag & drop ────────────────────────────────────────────────────

    def dragEnterEvent(self, event) -> None:
        md = event.mimeData()
        if md.hasUrls() and any(u.isLocalFile() for u in md.urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        files = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if not files:
            return
        self._sidebar.select(PAGE_STUDIO)
        self._studio.add_clips(files)

    def _run(self, task: str, **kwargs) -> None:
        """Studio render on its own worker (downloads use the queue)."""
        self._worker = _Worker(task, translate=self._t, **kwargs)
        self._worker.finished.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self._append_log)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.start()

    # ── callbacks ──────────────────────────────────────────────────────

    def _on_progress(self, msg: str, pct: object) -> None:
        self._studio.show_progress(msg, pct if isinstance(pct, (int, float)) else None)

    def _on_result(self, result: object) -> None:
        if self._worker is not None and self._worker._task == "transcribe":
            replace_lines = bool(self._worker._kw.get("replace"))
            self._set_busy(False)
            self._studio.finish(True)
            self._studio.captions_ready(list(result), replace_lines)
            return
        self._set_busy(False)
        files = list(result) if isinstance(result, (tuple, list)) else [str(result)]
        self._studio.finish(True)
        QMessageBox.information(
            self, self._t("Success"),
            self._t("Saved to:\n{paths}", paths="\n".join(str(f) for f in files)),
        )

    def _on_cancelled(self) -> None:
        self._set_busy(False)
        self._studio.finish(False)
        self._studio.status.setText(self._t("Stopped"))

    def _on_error(self, msg: str) -> None:
        self._set_busy(False)
        self._studio.finish(False)
        self._append_log(f"Error: {msg}")
        QMessageBox.critical(self, self._t("Something went wrong"), msg)

    # ── shortcuts ──────────────────────────────────────────────────────

    def _setup_shortcuts(self) -> None:
        from PySide6.QtGui import QKeySequence, QShortcut

        QShortcut(QKeySequence("Ctrl+V"), self, self._paste_url)
        QShortcut(QKeySequence("F1"), self, self._show_about)

    # ── close ──────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        if self.isVisible() and not self._studio.maybe_save():
            event.ignore()
            return
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
        if self._dl_worker is not None and self._dl_worker.isRunning():
            answer = QMessageBox.question(
                self, self._t("Task in progress"),
                self._t("Downloads are still running. Stop them and quit?"),
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            for item in self._queue:
                if item.status == QUEUED:
                    item.status = CANCELLED
            self._dl_worker.cancel()
            self._dl_worker.wait(5000)
        # give any in-flight info fetch a moment to finish before teardown
        self._probe_token += 1
        for worker in list(self._probe_workers):
            if worker.isRunning():
                worker.wait(3000)
        self._studio.preview.stop()
        self._studio.shutdown()
        self._studio.clear_autosave()  # a normal close: nothing to recover
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


_SPEED_MIN = 25
_SPEED_MAX = 400


def _build_speed_row() -> tuple[QSlider, QLabel, QHBoxLayout]:
    """A horizontal speed slider (0.25x..4x) + live value readout.

    Returns (slider, value_label, row_layout) so callers can drop the row
    into a card and keep the reference labels."""
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setObjectName("speed_slider")
    slider.setRange(_SPEED_MIN, _SPEED_MAX)
    slider.setValue(100)
    slider.setSingleStep(5)
    slider.setPageStep(25)
    slider.setTickPosition(QSlider.TicksBelow)
    slider.setTickInterval(50)
    slider.setCursor(QCursor(_HAND))
    val = QLabel("1\u00d7")
    val.setObjectName("speed_value")
    val.setMinimumWidth(48)
    val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    slider.valueChanged.connect(lambda v: val.setText(_format_speed(v)))
    row = QHBoxLayout()
    row.setSpacing(8)
    lo = QLabel("0.25\u00d7")
    lo.setObjectName("speed_marker")
    hi = QLabel("4\u00d7")
    hi.setObjectName("speed_marker")
    row.addWidget(lo)
    row.addWidget(slider, stretch=1)
    row.addWidget(hi)
    row.addWidget(val)
    return slider, val, row


def _format_speed(value: int) -> str:
    """Render a slider value (percent) as e.g. '1.5x'."""
    return f"{value / 100:g}\u00d7"


def _read_speed(slider: QSlider) -> float | None:
    """Read the slider as a speed factor; None when it is 1.0x (no change)."""
    value = slider.value()
    return None if value == 100 else value / 100


class _FitScrollArea(QScrollArea):
    """QScrollArea whose sizeHint tracks its child, so the default window
    fits the page; smaller windows gracefully show a scrollbar instead of
    compressing the cards."""

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        child = self.widget()
        if child is not None:
            frame = 2 * self.frameWidth()
            return QSize(
                max(hint.width(), child.sizeHint().width() + frame),
                max(hint.height(), child.sizeHint().height() + frame),
            )
        return hint


def _wrap_scroll(page: QWidget) -> QScrollArea:
    """Wrap a form page so it scrolls instead of collapsing on small windows."""
    scroll = _FitScrollArea()
    scroll.setObjectName("page_scroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(page)
    return scroll


def _build_filter(hflip: QCheckBox, vflip: QCheckBox) -> str | None:
    parts = []
    if hflip.isChecked():
        parts.append("hflip")
    if vflip.isChecked():
        parts.append("vflip")
    return ",".join(parts) or None


# ── entry point ────────────────────────────────────────────────────────────


# Fallback font chain used everywhere (QSS + app font). Noto Sans CJK TC
# (bundled) covers Traditional Chinese; it is pulled to the front for zh so
# glyphs render in their Traditional regional form.
_FONT_FALLBACK = (
    "Segoe UI", "Noto Sans",
    "Noto Sans CJK TC", "Noto Sans TC", "Source Han Sans TC",
    "PingFang TC", "Microsoft JhengHei", "WenQuanYi Zen Hei",
    "Droid Sans Fallback", "Ubuntu", "Cantarell", "sans-serif",
)

_LANG_FONT_PREF = {
    "zh": "Noto Sans CJK TC",
}


def _font_chain(lang: str) -> str:
    """Return the QSS `font-family` list, leading with *lang*'s CJK font."""
    fams = list(_FONT_FALLBACK)
    pref = _LANG_FONT_PREF.get(lang)
    if pref in fams:
        fams.remove(pref)
        fams.insert(0, pref)
    return ", ".join(f'"{f}"' for f in fams)


_APP_FONT_FAMILIES = list(_FONT_FALLBACK)

_BUNDLED_FONTS = (
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
    for root in (get_bundle_dir(), get_app_dir()):
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


def main() -> None:
    _enable_input_method()
    app = QApplication(sys.argv)
    app.setApplicationName("VidGrab")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(_app_icon())
    app.setStyle("Fusion")

    _register_bundled_fonts()

    font = QFont()
    font.setFamilies(_APP_FONT_FAMILIES)
    app.setFont(font)

    window = VidGrabWindow()

    # Hidden build-verification flag: construct the full UI headlessly and
    # report whether QtMultimedia (inline preview) and the auto-caption speech
    # engine are available in a packaged or source build, then exit. Used by CI to catch exclusion mistakes.
    if "--selftest" in sys.argv:
        from vidgrab.captions import engine_ok

        print(f"VIDGRAB_SELFTEST multimedia={int(_QT_MULTIMEDIA_OK)} "
              f"captions={int(engine_ok())}", flush=True)
        window.close()
        return

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
