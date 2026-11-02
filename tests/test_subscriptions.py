from __future__ import annotations

from vidgrab import subscriptions as sb


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
