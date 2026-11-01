"""The "Two videos at once" dialog: pick two videos, a layout, and see them
placed in the frame before anything is rendered. Qt part only — the picture
itself is made by `studio.compose_split`, and the preview here draws the
panels from `studio.split_panels`, so both agree."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vidgrab import studio

# layout -> (button label, what it shows)
LAYOUT_LABELS = {
    "side": "Left | Right",
    "stack": "Top / Bottom",
    "wide": "Big + small",
    "pip": "Picture in picture",
}
SIZES = {"1080p": "1080p (16:9)", "720p": "720p (16:9)",
         "vertical": "Vertical 9:16", "square": "Square 1:1"}
_VIDEO_FILTER = "Videos (*.mp4 *.mkv *.webm *.mov *.avi *.m4v);;All files (*)"


class SourceFrame:
    """One chosen video: its path, an optional part, and a still for the preview."""

    def __init__(self) -> None:
        self.path = ""
        self.image: QImage | None = None


class LayoutPreview(QWidget):
    """The output frame with both videos in their panels (cropped or not)."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(190)
        self.layout_name = "side"
        self.size_name = "1080p"
        self.gap = 0
        self.fill = True
        self.frames: list[QImage | None] = [None, None]

    def paintEvent(self, _event) -> None:
        w, h = studio.split_canvas(self.size_name)
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        pad = 6
        box = QRectF(pad, pad, self.width() - 2 * pad, self.height() - 2 * pad)
        k = min(box.width() / w, box.height() / h)
        frame = QRectF(box.center().x() - w * k / 2, box.center().y() - h * k / 2, w * k, h * k)
        p.fillRect(frame, QColor("#000000"))
        for i, (x, y, pw, ph) in enumerate(studio.split_panels(
                self.layout_name, w, h, self.gap)):
            rect = QRectF(frame.x() + x * k, frame.y() + y * k, pw * k, ph * k)
            img = self.frames[i]
            p.save()
            p.setClipRect(rect)
            if img is None or img.isNull():
                p.fillRect(rect, QColor("#3a3f4b"))
                p.setPen(QColor("#9aa0ad"))
                p.drawText(rect, Qt.AlignCenter, str(i + 1))
            else:
                scale = (max if self.fill else min)(rect.width() / img.width(),
                                                    rect.height() / img.height())
                dw, dh = img.width() * scale, img.height() * scale
                p.drawImage(QRectF(rect.center().x() - dw / 2, rect.center().y() - dh / 2, dw, dh),
                            img)
            p.restore()
            p.setPen(QPen(QColor("#ffffff"), 1))
            p.drawRect(rect)
            p.setPen(QColor("#ffffff"))
            p.drawText(rect.adjusted(5, 3, 0, 0), Qt.AlignLeft | Qt.AlignTop, str(i + 1))
        p.end()


class SplitDialog(QDialog):
    """Collects what `studio.compose_split` needs. `values()` after accept."""

    def __init__(
        self,
        parent: QWidget,
        t: Callable[..., str],
        pick_file: Callable[[], str],
        initial: list[tuple[str, str, str]] | None = None,
        still: Callable[[str, float], QImage | None] | None = None,
    ) -> None:
        """*initial*: up to two (path, start, end) to begin with. *still* gives
        a picture of a file at a time (for the preview)."""
        super().__init__(parent)
        self.t = t
        self._pick = pick_file
        self._still = still or (lambda _p, _s: None)
        self._size_touched = False
        self.setWindowTitle(t("Two videos at once"))
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(8)
        intro = QLabel(t("Play two videos at the same time in one frame, for example "
                         "side by side. The result is added to the timeline as one clip."))
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.paths: list[QLineEdit] = []
        self.starts: list[QLineEdit] = []
        self.ends: list[QLineEdit] = []
        for i in range(2):
            cap = QLabel(t("VIDEO {n}", n=i + 1))
            cap.setObjectName("field_cap")
            lay.addWidget(cap)
            row = QHBoxLayout()
            path = QLineEdit()
            path.setReadOnly(True)
            path.setPlaceholderText(t("Choose a video…"))
            choose = QPushButton(t("Choose…"))
            choose.setObjectName("secondary")
            choose.setCursor(QCursor(Qt.PointingHandCursor))
            choose.clicked.connect(lambda _c=False, k=i: self._choose(k))
            start, end = QLineEdit(), QLineEdit()
            for e, ph in ((start, t("Start")), (end, t("End"))):
                e.setPlaceholderText(ph)
                e.setFixedWidth(80)
                e.editingFinished.connect(self._refresh_still)
            row.addWidget(path, 1)
            row.addWidget(start)
            row.addWidget(end)
            row.addWidget(choose)
            lay.addLayout(row)
            self.paths.append(path)
            self.starts.append(start)
            self.ends.append(end)

        swap = QPushButton(t("Swap 1 ⇄ 2"))
        swap.setObjectName("secondary")
        swap.setCursor(QCursor(Qt.PointingHandCursor))
        swap.clicked.connect(self.swap)
        lay.addWidget(swap, 0, Qt.AlignLeft)

        cap = QLabel(t("LAYOUT"))
        cap.setObjectName("field_cap")
        lay.addWidget(cap)
        box = QWidget()
        box.setObjectName("segmented")
        box.setAttribute(Qt.WA_StyledBackground, True)
        brow = QHBoxLayout(box)
        brow.setContentsMargins(4, 4, 4, 4)
        brow.setSpacing(4)
        self.layout_btns: dict[str, QPushButton] = {}
        for key, label in LAYOUT_LABELS.items():
            b = QPushButton(t(label))
            b.setObjectName("segment")
            b.setProperty("compact", True)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setMinimumHeight(30)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            b.clicked.connect(lambda _c=False, k=key: self.set_layout(k))
            brow.addWidget(b)
            self.layout_btns[key] = b
        lay.addWidget(box)
        self.preview = LayoutPreview()
        lay.addWidget(self.preview)

        opts = QHBoxLayout()
        opts.setSpacing(10)
        col = QVBoxLayout()
        cap = QLabel(t("FRAME SIZE"))
        cap.setObjectName("field_cap")
        col.addWidget(cap)
        self.size = QComboBox()
        for key, label in SIZES.items():
            self.size.addItem(t(label), key)
        self.size.activated.connect(self._size_chosen)
        col.addWidget(self.size)
        opts.addLayout(col)
        col = QVBoxLayout()
        cap = QLabel(t("SOUND"))
        cap.setObjectName("field_cap")
        col.addWidget(cap)
        self.sound = QComboBox()
        for key, label in (("both", "Both videos"), ("first", "Video 1 only"),
                           ("second", "Video 2 only"), ("none", "No sound")):
            self.sound.addItem(t(label), key)
        col.addWidget(self.sound)
        opts.addLayout(col)
        col = QVBoxLayout()
        cap = QLabel(t("LENGTH"))
        cap.setObjectName("field_cap")
        col.addWidget(cap)
        self.length = QComboBox()
        self.length.addItem(t("Until the longer one ends"), "longest")
        self.length.addItem(t("Until the shorter one ends"), "shortest")
        col.addWidget(self.length)
        opts.addLayout(col)
        lay.addLayout(opts)

        row = QHBoxLayout()
        self.fill = QCheckBox(t("Crop each video to fill its space"))
        self.fill.setChecked(True)
        self.fill.toggled.connect(self._options_changed)
        row.addWidget(self.fill, 1)
        row.addWidget(QLabel(t("Gap")))
        self.gap = QSpinBox()
        self.gap.setRange(0, 60)
        self.gap.setSuffix(" px")
        self.gap.setValue(6)
        self.gap.valueChanged.connect(self._options_changed)
        row.addWidget(self.gap)
        lay.addLayout(row)
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton(t("Cancel"))
        cancel.clicked.connect(self.reject)
        self.go = QPushButton(t("Combine"))
        self.go.setDefault(True)
        self.go.clicked.connect(self._accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.go)
        lay.addLayout(buttons)

        for i, (path, start, end) in enumerate((initial or [])[:2]):
            self.set_source(i, path, start, end)
        self.set_layout("side")
        self._options_changed()

    # state ---------------------------------------------------------------

    def set_source(self, i: int, path: str, start: str = "", end: str = "") -> None:
        self.paths[i].setText(path)
        self.paths[i].setToolTip(path)
        self.starts[i].setText(start)
        self.ends[i].setText(end)
        self._refresh_still()

    def _choose(self, i: int) -> None:
        path = self._pick()
        if path:
            self.set_source(i, path)

    def swap(self) -> None:
        for fields in (self.paths, self.starts, self.ends):
            a, b = fields[0].text(), fields[1].text()
            fields[0].setText(b)
            fields[1].setText(a)
        self.paths[0].setToolTip(self.paths[0].text())
        self.paths[1].setToolTip(self.paths[1].text())
        self._refresh_still()

    def set_layout(self, key: str) -> None:
        self.layout_btns[key].setChecked(True)
        self.preview.layout_name = key
        if not self._size_touched:  # stacked videos want a tall frame (Shorts, Reels)
            self.size.setCurrentIndex(self.size.findData("vertical" if key == "stack" else "1080p"))
        self._options_changed()

    def _size_chosen(self, _i: int) -> None:
        self._size_touched = True
        self._options_changed()

    def layout_key(self) -> str:
        return next(k for k, b in self.layout_btns.items() if b.isChecked())

    def _options_changed(self, *_a) -> None:
        self.preview.layout_name = self.layout_key()
        self.preview.size_name = self.size.currentData()
        self.preview.gap = self.gap.value() if self.layout_key() in ("side", "stack", "wide") else 0
        self.gap.setEnabled(self.layout_key() != "pip")
        self.preview.fill = self.fill.isChecked()
        self.preview.update()

    def _refresh_still(self) -> None:
        for i in range(2):
            path = self.paths[i].text()
            start = studio.parse_timecode(self.starts[i].text()) or 0.0
            self.preview.frames[i] = self._still(path, start) if path else None
        self.preview.update()

    # result ----------------------------------------------------------------

    def _accept(self) -> None:
        if not all(p.text() and Path(p.text()).is_file() for p in self.paths):
            self.hint.setText(self.t("Choose two videos first."))
            return
        for fields in (self.starts, self.ends):
            for e in fields:
                if e.text().strip() and studio.parse_timecode(e.text()) is None:
                    self.hint.setText(self.t("Times look like 1:30 or 90."))
                    return
        self.accept()

    def values(self) -> dict:
        fit = "fill" if self.fill.isChecked() else "fit"
        clips = [studio.Clip(self.paths[i].text(), self.starts[i].text().strip() or None,
                             self.ends[i].text().strip() or None, fit=fit) for i in range(2)]
        return {
            "clips": clips,
            "layout": self.layout_key(),
            "resolution": self.size.currentData(),
            "gap": self.preview.gap,
            "audio": self.sound.currentData(),
            "length": self.length.currentData(),
        }
