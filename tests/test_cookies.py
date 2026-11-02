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


def test_browser_login_goes_to_every_request():
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
