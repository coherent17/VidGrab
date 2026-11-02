from pathlib import Path

import pytest

from vidgrab import downloader


@pytest.fixture(autouse=True)
def _reset():
    downloader.configure_cookies("")
    yield
    downloader.configure_cookies("")


def _opts():
    return downloader._ytdl_options("u", Path("."), "mp4", ffmpeg=None)


def test_no_cookies_by_default():
    assert "cookiesfrombrowser" not in _opts()
    assert "cookiesfrombrowser" not in downloader._net_opts()


def _browser(monkeypatch, works: bool, calls=None):
    import yt_dlp.cookies as ytc

    def fake(name, profile=None, logger=None, **kw):
        if calls is not None:
            calls.append(name)
        if not works:
            raise RuntimeError(f"could not find {name} cookies database in \"/x\"")

    monkeypatch.setattr(ytc, "extract_cookies_from_browser", fake)


def test_browser_login_goes_to_every_request(monkeypatch):
    _browser(monkeypatch, True)
    downloader.configure_cookies("firefox")
    assert _opts()["cookiesfrombrowser"] == ("firefox",)
    assert downloader._net_opts()["cookiesfrombrowser"] == ("firefox",)
    downloader.configure_cookies("not-a-browser")  # unknown names are ignored
    assert "cookiesfrombrowser" not in downloader._net_opts()


def test_a_cookie_failure_says_what_to_do():
    downloader.configure_cookies("chrome")

    def boom(_client, _ipv4):
        raise ValueError("could not find chrome cookies database")

    with pytest.raises(RuntimeError, match="Close Chrome"):
        downloader._try_clients(boom, lambda _m: None, lambda text, **kw: text.format(**kw))


def test_an_unreadable_login_is_left_out_so_everything_still_works(monkeypatch):
    calls: list[str] = []
    _browser(monkeypatch, False, calls)
    downloader.configure_cookies("chrome")
    assert "cookiesfrombrowser" not in downloader._net_opts()  # search / probe / download go without it
    assert "cookiesfrombrowser" not in _opts()
    assert "cookies database" in downloader.cookies_problem()
    downloader._net_opts()
    assert calls == ["chrome"]  # not re-read on every request
    # the browser is closed later: it is tried again after a while, and then used
    _browser(monkeypatch, True, calls)
    downloader._COOKIE_CHECK["chrome"] = (False, downloader.time.monotonic() - 60, "old")
    assert downloader._net_opts()["cookiesfrombrowser"] == ("chrome",) and downloader.cookies_problem() == ""
    assert calls == ["chrome", "chrome"]
    downloader._net_opts()
    assert calls == ["chrome", "chrome"]  # a working login is kept
