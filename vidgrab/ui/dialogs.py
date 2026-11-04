"""File dialogs and the modal-dialog runner."""
from __future__ import annotations

from PySide6.QtCore import (
    QSize,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QHeaderView,
    QSplitter,
    QTreeView,
    QWidget,
)

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
