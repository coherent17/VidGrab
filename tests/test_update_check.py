from __future__ import annotations

import json

from vidgrab import opener
from vidgrab import update_check as uc


class _Resp:
    def __init__(self, body: dict | bytes) -> None:
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self) -> bytes:
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_a) -> None: ...


def _patch(monkeypatch, answer) -> None:
    class Fake:
        def open(self, req, timeout=None):
            if isinstance(answer, Exception):
                raise answer
            return _Resp(answer)

    monkeypatch.setattr(uc.urllib.request, "build_opener", lambda *a: Fake())


def test_versions_compare_by_number_not_text() -> None:
    assert uc.parse_version("v4.10.0") == (4, 10, 0) and uc.parse_version("junk") == ()
    assert uc.is_newer("v4.10.0", "4.9.9") and not uc.is_newer("4.1.1", "4.1.1")
    assert uc.is_newer("4.2", "4.1.9") and not uc.is_newer("4.1", "4.1.0") and not uc.is_newer("", "4.1.1")


def test_a_newer_release_is_reported_and_the_rest_is_ignored(monkeypatch) -> None:
    _patch(monkeypatch, {"tag_name": "v9.0.0", "html_url": "https://github.com/x/y/releases/v9", "body": "hi"})
    news = uc.latest_release(current="4.1.1")
    assert news == {"version": "9.0.0", "url": "https://github.com/x/y/releases/v9", "notes": "hi"}
    _patch(monkeypatch, {"tag_name": "v4.1.1"})
    assert uc.latest_release(current="4.1.1") is None  # already on it
    _patch(monkeypatch, {"tag_name": "v9.0.0", "prerelease": True})
    assert uc.latest_release(current="4.1.1") is None  # no betas
    _patch(monkeypatch, OSError("offline"))
    assert uc.latest_release(current="4.1.1") is None  # never raises
    _patch(monkeypatch, b"<html>")
    assert uc.latest_release(current="4.1.1") is None


def test_opening_a_link_picks_the_right_tool_and_refuses_odd_schemes() -> None:
    assert opener.url_commands("https://a.b", system="darwin") == [["open", "https://a.b"]]
    assert opener.url_commands("https://a.b", system="win32")[0][:3] == ["cmd", "/c", "start"]
    assert opener.url_commands("https://a.b", system="linux", wsl=True)[0][-1] == "https://a.b"
    assert opener.open_url("file:///etc/passwd") is False and opener.open_url("javascript:alert(1)") is False
