"""Qt-free "open this file" / "show it in its folder" for every platform.

Qt's `QDesktopServices` finds no handler on WSL and many bare Linux setups, so
this picks the real tool: `os.startfile` / `explorer /select,` on Windows,
`open` / `open -R` on macOS, Windows Explorer through `wslpath` on WSL, and
`xdg-open` (the folder, since Linux file managers have no common "select")
elsewhere."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def is_wsl() -> bool:
    return bool(os.environ.get("WSL_DISTRO_NAME")) or "microsoft" in platform.uname().release.lower()


def _windows_path(path: str) -> str | None:
    try:
        out = subprocess.run(["wslpath", "-w", path], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def commands(path: str | Path, reveal: bool = False, *, system: str | None = None, wsl: bool | None = None,
             windows_path: str | None = None) -> list[list[str]]:
    """The command lines to try, in order. (Arguments override the detected
    platform so the choice is testable.)"""
    p = str(path)
    system = system or sys.platform
    if system == "darwin":
        return [["open", "-R", p] if reveal else ["open", p]]
    if system.startswith("win"):
        return [["explorer", f"/select,{os.path.normpath(p)}"] if reveal else ["cmd", "/c", "start", "", p]]
    wsl = is_wsl() if wsl is None else wsl
    if wsl:
        win = windows_path or _windows_path(p)
        if win:
            explorer = shutil.which("explorer.exe") or "explorer.exe"
            return [[explorer, f"/select,{win}"] if reveal else [explorer, win]]
    target = str(Path(p).parent) if reveal else p
    return [[exe, target] for exe in ("xdg-open", "gio open", "kde-open") if shutil.which(exe.split()[0])]


def open_path(path: str | Path, reveal: bool = False) -> bool:
    """Open *path* (or its folder with it selected). False if nothing worked."""
    if sys.platform == "win32" and not reveal:
        try:
            os.startfile(str(path))
            return True
        except OSError:
            return False
    for cmd in commands(path, reveal):
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            continue
        try:
            code = proc.wait(timeout=0.8)
        except subprocess.TimeoutExpired:
            return True  # still running: a viewer took the file
        if code == 0 or Path(cmd[0]).name.lower() in ("explorer", "explorer.exe"):
            return True  # explorer exits 1 even when it worked
    return False
