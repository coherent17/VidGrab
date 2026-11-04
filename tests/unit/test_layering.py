"""The engine stays free of Qt (so it runs, and is tested, without a window).

Only the modules listed in `QT_MODULES` may import PySide6, and nothing outside that list
may import one of them at the top of a file (a `cli` command importing the window inside a
function is fine). A new Qt module has to be added here on purpose; a new engine module is
checked without anyone remembering to."""
from __future__ import annotations

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "vidgrab"
QT_MODULES = {
    "app", "downloads_panel", "help_page", "icon", "library_page", "pick_dialogs", "preview",
    "silence_dialog", "split_dialog", "stickers", "studio_page", "subscriptions_page",
    "tools_page", "ui_kit",
}


def _imports(path: Path, *, top_level_only: bool) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text("utf-8"))
    nodes = tree.body if top_level_only else list(ast.walk(tree))
    found: list[tuple[str, int]] = []
    for node in nodes:
        if isinstance(node, ast.Import):
            found += [(a.name, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "vidgrab":
                found += [(f"vidgrab.{a.name}", node.lineno) for a in node.names]
            else:
                found.append((node.module, node.lineno))
    return found


def test_qt_is_imported_only_by_the_ui_modules() -> None:
    bad = [f"{p.name}:{line} imports {name}" for p in sorted(PKG.glob("*.py")) if p.stem not in QT_MODULES
           for name, line in _imports(p, top_level_only=False) if name.split(".")[0] == "PySide6"]
    assert not bad, "engine modules must not import Qt: " + "; ".join(bad)


def test_the_engine_does_not_pull_in_the_window_modules() -> None:
    bad = []
    for p in sorted(PKG.glob("*.py")):
        if p.stem in QT_MODULES:
            continue
        for name, line in _imports(p, top_level_only=True):
            parts = name.split(".")
            if parts[0] == "vidgrab" and len(parts) > 1 and parts[1] in QT_MODULES:
                bad.append(f"{p.name}:{line} imports {name}")
    assert not bad, "engine modules must not import UI modules at the top of the file: " + "; ".join(bad)


def test_the_list_of_qt_modules_is_not_stale() -> None:
    real = {p.stem for p in PKG.glob("*.py") if any(n.split(".")[0] == "PySide6" for n, _ in
                                                    _imports(p, top_level_only=False))}
    assert real == QT_MODULES
