from __future__ import annotations

import subprocess

from vidgrab import opener


def test_commands_per_platform() -> None:
    assert opener.commands("/a/b.mp4", system="darwin") == [["open", "/a/b.mp4"]]
    assert opener.commands("/a/b.mp4", True, system="darwin") == [["open", "-R", "/a/b.mp4"]]
    assert opener.commands("C:/a/b.mp4", True, system="win32")[0][0] == "explorer"
    wsl = opener.commands("/mnt/c/b.mp4", True, system="linux", wsl=True, windows_path="C:\\b.mp4")
    assert wsl[0][1] == "/select,C:\\b.mp4" and wsl[0][0].endswith("explorer.exe")
    assert opener.commands("/mnt/c/b.mp4", system="linux", wsl=True, windows_path="C:\\b.mp4")[0][1] == "C:\\b.mp4"


def test_linux_reveal_opens_the_folder(monkeypatch) -> None:
    monkeypatch.setattr(opener.shutil, "which", lambda name: "/usr/bin/" + name if name == "xdg-open" else None)
    assert opener.commands("/home/u/v.mp4", True, system="linux", wsl=False) == [["xdg-open", "/home/u"]]
    assert opener.commands("/home/u/v.mp4", system="linux", wsl=False) == [["xdg-open", "/home/u/v.mp4"]]


def test_open_path_reports_failure_and_success(monkeypatch) -> None:
    class Done:
        def __init__(self, code): self.code = code
        def wait(self, timeout=None): return self.code

    monkeypatch.setattr(opener.sys, "platform", "linux")
    monkeypatch.setattr(opener, "commands", lambda p, r=False, **k: [["xdg-open", p], ["other", p]])
    seen = []

    def popen(cmd, **kw):
        seen.append(cmd[0])
        if cmd[0] == "xdg-open":
            return Done(3)  # no handler
        return Done(0)

    monkeypatch.setattr(subprocess, "Popen", popen)
    assert opener.open_path("/x") is True and seen == ["xdg-open", "other"]
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: (_ for _ in ()).throw(OSError("nope")))
    assert opener.open_path("/x") is False
    monkeypatch.setattr(opener, "commands", lambda p, r=False, **k: [])
    assert opener.open_path("/x") is False
