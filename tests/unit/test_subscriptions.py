from __future__ import annotations

import pytest

from vidgrab.core import subscriptions as sb


def test_save_load_and_add(tmp_path) -> None:
    p = tmp_path / "s.json"
    subs: list[sb.Subscription] = []
    assert sb.add(subs, " https://youtube.com/@a ", "A") is not None
    assert sb.add(subs, "https://youtube.com/@a") is None and sb.add(subs, "") is None
    sb.save(p, subs)
    assert sb.load(p) == subs
    p.write_text('[{"url": 3}, {"url": "u", "seen": ["x", 1]}, "bad"]')
    assert sb.load(p) == [sb.Subscription("u", "", ["x"])]
    p.write_text("not json")
    assert sb.load(p) == []


def test_channel_urls_point_at_videos() -> None:
    assert sb.feed_url("https://www.youtube.com/@name/") == "https://www.youtube.com/@name/videos"
    assert sb.feed_url("https://www.youtube.com/@name/shorts") == "https://www.youtube.com/@name/shorts"
    assert sb.feed_url("https://www.youtube.com/playlist?list=PL1") == "https://www.youtube.com/playlist?list=PL1"


def test_parse_feed_and_new_markers() -> None:
    info = {"title": "Chan", "entries": [None, {"id": "a1", "title": "One", "duration": 61},
                                         {"id": "b2", "url": "https://x/y", "title": "Two"}, {"title": "no id"}]}
    title, items = sb.parse_feed(info)
    assert title == "Chan" and [i.id for i in items] == ["a1", "b2"]
    assert items[0].url == "https://www.youtube.com/watch?v=a1" and items[1].url == "https://x/y"
    sub = sb.Subscription("u")
    assert sb.new_ids(sub, items) == set()  # nothing is "new" the first time
    sb.mark_seen(sub, items[:1])
    assert sb.new_ids(sub, items) == {"b2"}
    sb.mark_seen(sub, items)
    assert sb.new_ids(sub, items) == set() and sub.seen == ["a1", "b2"]


def test_feed_is_read_without_the_browser_login_first(monkeypatch) -> None:
    from vidgrab.core import downloader

    seen = []

    def fake(url, limit, opts):
        seen.append("cookiesfrombrowser" in opts)
        if "cookiesfrombrowser" in opts and len(seen) == 1:
            raise RuntimeError("failed to load cookies")
        return {"title": "T", "entries": [{"id": "a", "title": "A"}]}

    monkeypatch.setattr(sb, "_extract", fake)
    monkeypatch.setattr(downloader, "_net_opts", lambda **k: {"retries": 3, "cookiesfrombrowser": ("firefox",)})
    title, items = sb.fetch("https://x/@c")
    assert seen == [False] and title == "T" and len(items) == 1  # the public read worked: no login used
    seen.clear()
    monkeypatch.setattr(sb, "_extract", lambda u, n, o: (_ for _ in ()).throw(RuntimeError("members only"))
                        if "cookiesfrombrowser" not in o else {"title": "M", "entries": [{"id": "z", "title": "Z"}]})
    assert sb.fetch("https://x/@c")[0] == "M"  # then the login, for a members-only list
    monkeypatch.setattr(sb, "_extract", lambda u, n, o: (_ for _ in ()).throw(RuntimeError("failed to load cookies")))
    with pytest.raises(RuntimeError):
        sb.fetch("https://x/@c")
