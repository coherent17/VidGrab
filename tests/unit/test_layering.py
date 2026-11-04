"""The engine stays free of Qt (so it runs, and is tested, without a window).

`vidgrab/ui/` is the only place that may import PySide6; `core/`, `media/`, `ai/` and the
top-level modules may not, and may not import `vidgrab.ui` at the top of a file (`cli`
opening the window inside a function is fine). New files are checked without anyone
remembering to list them."""
from __future__ import annotations

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "vidgrab"
ENGINE_DIRS = ("core", "media", "ai")


def _engine_files() -> list[Path]:
    files = [p for p in PKG.glob("*.py")]
    for d in ENGINE_DIRS:
        files += list((PKG / d).rglob("*.py"))
    return sorted(files)


def _imports(path: Path, *, top_level_only: bool) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text("utf-8"))
    nodes = tree.body if top_level_only else list(ast.walk(tree))
    found: list[tuple[str, int]] = []
    for node in nodes:
        if isinstance(node, ast.Import):
            found += [(a.name, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.module, node.lineno))
            if node.module == "vidgrab":
                found += [(f"vidgrab.{a.name}", node.lineno) for a in node.names]
    return found


def test_engine_packages_exist() -> None:
    assert all((PKG / d / "__init__.py").is_file() for d in (*ENGINE_DIRS, "ui"))
    assert len(_engine_files()) > 25  # the glob is not silently empty


def test_qt_is_imported_only_under_ui() -> None:
    bad = [f"{p.relative_to(PKG)}:{line} imports {name}" for p in _engine_files()
           for name, line in _imports(p, top_level_only=False) if name.split(".")[0] == "PySide6"]
    assert not bad, "engine modules must not import Qt: " + "; ".join(bad)


def test_the_engine_does_not_pull_in_ui_at_import_time() -> None:
    bad = [f"{p.relative_to(PKG)}:{line} imports {name}" for p in _engine_files()
           for name, line in _imports(p, top_level_only=True) if name == "vidgrab.ui" or name.startswith("vidgrab.ui.")]
    assert not bad, "engine modules must not import vidgrab.ui at the top of a file: " + "; ".join(bad)


def test_package_inits_stay_empty() -> None:
    """vidgrab/__init__ runs the yt-dlp update before anything imports yt-dlp: a package
    __init__ that imported its modules would defeat that."""
    for d in (*ENGINE_DIRS, "ui"):
        tree = ast.parse((PKG / d / "__init__.py").read_text("utf-8"))
        assert not [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))], d
