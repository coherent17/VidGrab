"""Pictures, cover boxes and stickers over the video."""
from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import (
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QCursor,
    QFontMetricsF,
    QImage,
)
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from vidgrab.media.studio import (
    IMAGE_EXTS,
    ImageOverlay,
    canvas_size,
    parse_timecode,
)
from vidgrab.ui import stickers
from vidgrab.ui.studio.clips import _fmt_precise
from vidgrab.ui.studio.common import _HAND


class ImagesMixin:
    """Pictures, cover boxes and stickers over the video."""

    def images(self) -> list[ImageOverlay]:
        return [replace(img) for img in self._images]

    def _image_thumb(self, path: str) -> QImage | None:
        cache = self.__dict__.setdefault("_thumb_cache", {})
        if path not in cache:
            img = QImage(path)
            cache[path] = img.scaledToHeight(48, Qt.SmoothTransformation) if not img.isNull() else None
        return cache[path]

    def _browse_images(self, *, at: float | None = None) -> None:
        exts = " ".join(f"*{e}" for e in IMAGE_EXTS)
        paths = self.host.pick_files(self.t("Add images"), ("Pictures", "Downloads"),
                                     f"Images ({exts});;All files (*)")
        if paths:
            self.add_images(paths, at=at)

    def add_images(self, paths: list[str], *, at: float | None = None,
                   tweak: Callable[[ImageOverlay], None] | None = None) -> None:
        """Add pictures from the playhead (or *at*), placed by what they look
        like: a cut-out with transparency (a logo, a sticker) goes small in a
        corner, a photo large in the middle. Several are shown one after another."""
        total = self.track.total()
        if total <= 0:
            self.status.setText(self.t("Add at least one clip first."))
            return
        t = self.preview.position() if at is None else at
        added = None
        for path in paths:
            pic = QImage(path)
            if pic.isNull():
                self.host.log(self.t("Could not read the image {name}.", name=Path(path).name))
                continue
            length = min(4.0, total)
            start = round(min(max(0.0, t), max(0.0, total - length)), 2)
            img = ImageOverlay(path, start, round(min(start + length, total), 2))
            frame_w, frame_h = canvas_size(self.res.currentData() or "auto",
                                           *self._first_video_size())
            if pic.hasAlphaChannel():  # a logo / sticker: top-right corner
                img.width = 0.22
                h = img.width * frame_w * pic.height() / max(1, pic.width()) / frame_h
                img.x, img.y = round(1 - 0.04 - img.width / 2, 4), round(0.06 + h / 2, 4)
            else:  # a photo: as large as fits, centred
                fit_w = min(0.8, 0.8 * frame_h / frame_w * pic.width() / max(1, pic.height()))
                img.width = round(fit_w, 4)
                img.fade = 0.3
            if tweak is not None:
                tweak(img)
            self._images.append(img)
            added = len(self._images) - 1
            t = img.end
        if added is None:
            return
        self._refresh_track()
        self._push_images()
        self.select_image(added)
        self.preview.seek(self._images[added].start + 0.01)
        self._record()

    def _image_label(self, img: ImageOverlay) -> str:
        if img.kind == "blur":
            return self.t("Blur")
        if img.kind == "pixel":
            return self.t("Pixelate")
        stem = Path(img.path).stem
        if stem.startswith("sticker-") and stem[8:] in stickers.NAMES:
            return self.t(stickers.label(stem[8:]))
        return Path(img.path).name

    def _image_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction(self.t("Picture from a file…"), self._browse_images)
        menu.addSeparator()
        menu.addAction(self.t("Blur box (hide a face or plate)"), lambda: self.add_cover("blur"))
        menu.addAction(self.t("Pixelate box"), lambda: self.add_cover("pixel"))
        menu.addSeparator()
        sub = menu.addMenu(self.t("Sticker"))
        for name in stickers.NAMES:
            sub.addAction(self.t(stickers.label(name)), lambda n=name: self.add_sticker(n))
        self._image_menu_obj = menu  # for tests
        menu.exec(self.image_btn.mapToGlobal(self.image_btn.rect().bottomLeft()))

    def add_cover(self, kind: str, *, at: float | None = None) -> None:
        """A box that blurs / pixelates part of the picture from the playhead."""
        total = self.track.total()
        if total <= 0 or not self.is_video():
            self.status.setText(self.t("Add at least one clip first."))
            return
        t = self.preview.position() if at is None else at
        length = min(4.0, total)
        start = round(min(max(0.0, t), max(0.0, total - length)), 2)
        img = ImageOverlay("", start, round(min(start + length, total), 2), 0.5, 0.5, 0.3,
                           kind=kind, height=0.2, strength=0.6)
        self._images.append(img)
        self._refresh_track()
        self._push_images()
        self.select_image(len(self._images) - 1)
        self.preview.seek(img.start + 0.01)
        self._record()

    def add_sticker(self, name: str) -> None:
        folder = Path(tempfile.gettempdir()) / "vidgrab-stickers"
        target = self._autosave_path()
        if target is not None:
            folder = target.parent / "stickers"
        try:
            paths = stickers.ensure(folder)
        except OSError as exc:
            self.status.setText(str(exc))
            return
        def place(img: ImageOverlay) -> None:
            img.width = 0.18  # stickers are punctuation: small, in the middle
            img.x, img.y = 0.5, 0.5
            img.fade = 0.2

        self.add_images([paths[name]], tweak=place)

    def _first_video_size(self) -> tuple[int, int]:
        first = next((c for c in self._clips if c.has_video), None)
        return (first.info.get("width", 0), first.info.get("height", 0)) if first else (1280, 720)

    def _cur_image(self) -> ImageOverlay | None:
        if self._sel and self._sel[0] == "image" and 0 <= self._sel[1] < len(self._images):
            return self._images[self._sel[1]]
        return None

    def select_image(self, k: int) -> None:
        if not 0 <= k < len(self._images):
            return
        self._sel = ("image", k)
        img = self._images[k]
        if not img.start <= self.preview.position() < img.end:
            self.preview.seek(img.start + 0.01)
        self._fill_image_inspector()
        self._show_inspector(self.INSP_IMAGE, "Image")
        self.track.set_selection(self._sel)
        self._push_images()

    def _push_images(self) -> None:
        sel = self._sel[1] if self._sel and self._sel[0] == "image" else None
        self.preview.set_images(list(enumerate(self._images)) if self.is_video() else [], sel)

    def _image_changed(self, kind: str = "", *, timeline: bool = False) -> None:
        if timeline:
            self._refresh_track()
            self.track.set_selection(self._sel)
        self._push_images()
        self._fill_image_inspector()
        self._record(kind)

    def _on_image_timing(self, k: int, start: float, end: float) -> None:
        if 0 <= k < len(self._images):
            self._images[k].start, self._images[k].end = start, end
            self._sel = ("image", k)
            self._image_changed(timeline=True)

    def _on_image_placed(self, k: int, x: float, y: float, width: float,
                         rotation: float = 0.0) -> None:
        if 0 <= k < len(self._images):
            img = self._images[k]
            if not img.is_picture() and img.width > 0:
                img.height = round(min(max(img.height * width / img.width, 0.02), 1.0), 4)  # keeps its shape
            img.x, img.y, img.width, img.rotation = x, y, width, rotation
            self._sel = ("image", k)
            self._image_changed()

    def _remove_image(self) -> None:
        if self._cur_image() is None:
            return
        del self._images[self._sel[1]]
        self.deselect()
        self._refresh_track()
        self._push_images()
        self._record()

    def _build_image_inspector(self) -> QWidget:
        inner, lay = self._page()
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(6)
        self.image_name = QLabel()
        self.image_name.setObjectName("info_name")
        self.image_name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay.addWidget(self.image_name)
        times = QHBoxLayout()
        times.setSpacing(8)
        self.image_fields: dict[str, QLineEdit] = {}
        for key, label in (("start", "Start:"), ("end", "End:")):
            f = QLineEdit()
            f.editingFinished.connect(lambda k=key: self._image_typed(k))
            self.image_fields[key] = f
            times.addWidget(self._label(label))
            times.addWidget(f, stretch=1)
        lay.addLayout(times)
        form = QFormLayout()
        form.setSpacing(7)
        self.image_size, srow = self._level(30)
        self.image_size.setRange(3, 200)
        self.image_size.valueChanged.connect(self._set_image_size)
        form.addRow(self._label("Size:"), srow)
        self.image_height, hrow = self._level(20)
        self.image_height.setRange(2, 100)
        self.image_height.valueChanged.connect(self._set_image_height)
        self.image_height_lbl = self._label("Height:")
        form.addRow(self.image_height_lbl, hrow)
        self.image_strength, trow = self._level(60)
        self.image_strength.setRange(0, 100)
        self.image_strength.valueChanged.connect(self._set_image_strength)
        self.image_strength_lbl = self._label("Strength:")
        form.addRow(self.image_strength_lbl, trow)
        self.image_opacity, orow = self._level(100)
        self.image_opacity.setRange(5, 100)
        self.image_opacity.valueChanged.connect(self._set_image_opacity)
        self.image_opacity_lbl = self._label("Opacity:")
        form.addRow(self.image_opacity_lbl, orow)
        self.image_fade = QDoubleSpinBox()
        self.image_fade.setRange(0.0, 5.0)
        self.image_fade.setSingleStep(0.1)
        self.image_fade.setDecimals(1)
        self.image_fade.setSuffix(" s")
        self.image_fade.valueChanged.connect(self._set_image_fade)
        self.image_fade_lbl = self._label("Fade in / out:")
        form.addRow(self.image_fade_lbl, self.image_fade)
        turn = QHBoxLayout()
        turn.setSpacing(6)
        self.image_rotation = QDoubleSpinBox()
        self.image_rotation.setRange(-180.0, 180.0)
        self.image_rotation.setSingleStep(5.0)
        self.image_rotation.setDecimals(1)
        self.image_rotation.setSuffix("°")
        self.image_rotation.setWrapping(True)
        self.image_rotation.valueChanged.connect(self._set_image_rotation)
        turn.addWidget(self.image_rotation, stretch=1)
        for text, step, tip in (("↺ 90°", -90.0, "Turn left 90°"), ("↻ 90°", 90.0, "Turn right 90°")):
            b = self._btn(text, lambda _c=False, d=step: self._turn_image(d), tip)
            turn.addWidget(b)
        self.image_rotation_lbl = self._label("Rotation:")
        form.addRow(self.image_rotation_lbl, turn)
        self.image_form = form
        lay.addLayout(form)
        self.image_move_cap = self._label("MOVEMENT", "field_cap")
        lay.addWidget(self.image_move_cap)
        self.image_motion_btns: dict[str, QPushButton] = {}
        self.image_motion_grid = self._choice_grid(
            [("none", "Still"), ("zoom_in", "Zoom in"), ("zoom_out", "Zoom out")], 3,
            self._set_image_motion, self.image_motion_btns)
        lay.addWidget(self.image_motion_grid)
        lay.addWidget(self._label("POSITION", "field_cap"))
        pos_row = QHBoxLayout()
        pos_row.setSpacing(12)
        grid_box = QWidget()
        grid = QGridLayout(grid_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(3)
        self._image_anchor_btns: dict[int, QPushButton] = {}
        for r, row_anchors in enumerate(((7, 8, 9), (4, 5, 6), (1, 2, 3))):
            for c, anchor in enumerate(row_anchors):
                b = QPushButton()
                b.setObjectName("anchor_btn")
                b.setFixedSize(34, 24)
                b.setIconSize(QSize(18, 12))
                b.setCursor(QCursor(_HAND))
                b.clicked.connect(lambda _c=False, a=anchor: self._place_image(a))
                grid.addWidget(b, r, c)
                self._image_anchor_btns[anchor] = b
        pos_row.addWidget(grid_box)
        col = QVBoxLayout()
        col.setSpacing(6)
        col.addWidget(self._btn("Fill the frame", self._fill_frame_image,
                                "Cover the whole frame (a full-screen picture)"))
        col.addWidget(self._btn("Remove", self._remove_image, "Remove this picture"))
        col.addStretch()
        pos_row.addLayout(col, stretch=1)
        lay.addLayout(pos_row)
        lay.addWidget(self._label(
            "Drag the picture in the preview to move it; drag its corner to resize. Drag its "
            "block in the Images row to change when it shows.", "hint"))
        lay.addStretch()
        return self._scroll(inner)

    def _fill_image_inspector(self) -> None:
        img = self._cur_image()
        if img is None:
            return
        self.image_name.setText(QFontMetricsF(self.image_name.font()).elidedText(
            self._image_label(img), Qt.ElideMiddle, max(120, self.insp.width() - 16)))
        self.image_name.setToolTip(img.path)
        cover = not img.is_picture()  # a blur / pixel box: height and strength, no picture options
        for lbl, shown in ((self.image_height_lbl, cover), (self.image_strength_lbl, cover),
                           (self.image_opacity_lbl, not cover), (self.image_fade_lbl, not cover),
                           (self.image_rotation_lbl, not cover)):
            self.image_form.setRowVisible(lbl, shown)
        self.image_move_cap.setVisible(not cover)
        self.image_motion_grid.setVisible(not cover)
        for key, value in (("start", img.start), ("end", img.end)):
            if not self.image_fields[key].hasFocus():
                self.image_fields[key].setText(_fmt_precise(value))
        for w, v in ((self.image_size, round(img.width * 100)),
                     (self.image_height, round(img.height * 100)),
                     (self.image_strength, round(img.strength * 100)),
                     (self.image_opacity, round(img.opacity * 100)), (self.image_fade, img.fade),
                     (self.image_rotation, img.rotation)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        for w in (self.image_size, self.image_height, self.image_strength, self.image_opacity):
            self._sync_level_label(w)
        for kind, b in self.image_motion_btns.items():
            b.setChecked(kind == img.motion)

    def _set_image_motion(self, kind: str) -> None:
        img = self._cur_image()
        if img is not None:
            img.motion = kind
            self._image_changed()

    def _image_typed(self, key: str) -> None:
        img = self._cur_image()
        value = parse_timecode(self.image_fields[key].text())
        if img is None or value is None:
            self._fill_image_inspector()
            return
        total = self.track.total()
        if key == "start" and value < img.end - 0.1:
            img.start = round(max(0.0, value), 2)
        elif key == "end" and value > img.start + 0.1:
            img.end = round(min(value, total) if total else value, 2)
        self._image_changed(timeline=True)

    def _set_image_size(self, value: int) -> None:
        img = self._cur_image()
        if img is not None:
            img.width = value / 100
            self._image_changed("image_size")

    def _set_image_height(self, value: int) -> None:
        img = self._cur_image()
        if img is not None:
            img.height = value / 100
            self._image_changed("image_height")

    def _set_image_strength(self, value: int) -> None:
        img = self._cur_image()
        if img is not None:
            img.strength = value / 100
            self._image_changed("image_strength")

    def _set_image_opacity(self, value: int) -> None:
        img = self._cur_image()
        if img is not None:
            img.opacity = value / 100
            self._image_changed("image_opacity")

    def _set_image_fade(self, value: float) -> None:
        img = self._cur_image()
        if img is not None:
            img.fade = round(value, 2)
            self._image_changed("image_fade")

    def _set_image_rotation(self, value: float) -> None:
        img = self._cur_image()
        if img is not None:
            img.rotation = round(value, 1)
            self._image_changed("image_rotation")

    def _turn_image(self, step: float) -> None:
        img = self._cur_image()
        if img is not None:
            angle = (img.rotation + step) % 360
            img.rotation = round(angle - 360 if angle > 180 else angle, 1)
            self._image_changed()

    def _place_image(self, anchor: int) -> None:
        """Snap the picture to one of 9 spots, its edge a small margin in."""
        img = self._cur_image()
        if img is None:
            return
        frame_w, frame_h = canvas_size(self.res.currentData() or "auto", *self._first_video_size())
        pic = QImage(img.path)
        h = img.width * frame_w * pic.height() / max(1, pic.width()) / frame_h if not pic.isNull() \
            else img.width
        col, row = (anchor - 1) % 3, (anchor - 1) // 3
        margin = 0.04
        img.x = round((margin + img.width / 2, 0.5, 1 - margin - img.width / 2)[col], 4)
        img.y = round((1 - margin - h / 2, 0.5, margin + h / 2)[row], 4)
        self._image_changed()

    def _fill_frame_image(self) -> None:
        img = self._cur_image()
        if img is None:
            return
        frame_w, frame_h = canvas_size(self.res.currentData() or "auto", *self._first_video_size())
        pic = QImage(img.path)
        # cover: wide enough for the frame's width and its height
        cover_h = (frame_h / frame_w) * pic.width() / max(1, pic.height()) if not pic.isNull() else 1
        img.x, img.y, img.width = 0.5, 0.5, round(max(1.0, cover_h), 4)
        self._image_changed()
