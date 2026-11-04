"""Palettes and the application stylesheet."""
from __future__ import annotations

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
        "POPUP": "#1c1e3e", "EDGE": "#5b62b5",  # pop-up windows: lifted surface + clear outline
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
        "POPUP": "#ffffff", "EDGE": "#8f96cc",
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
    background-color: @POPUP@;
    border: 1px solid @EDGE@;
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
    background-color: @POPUP@;
    border: 2px solid @EDGE@;
}
QDialog QLabel, QMessageBox QLabel {
    color: @TEXT@;
}
QDialog QPushButton {
    background-color: @SURFACE_HI@;
    border: 1px solid @BORDER_HI@;
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
    background-color: @POPUP@;
    border: 1px solid @EDGE@;
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
    background-color: @POPUP@;
    border: 1px solid @EDGE@;
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
