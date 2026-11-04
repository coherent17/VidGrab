"""The Help page: both languages for every topic, search, and the window wiring."""
from __future__ import annotations

import os

import pytest

from vidgrab.ui import help_content


def test_every_topic_has_both_languages_and_a_known_section() -> None:
    ids = [t[0] for t in help_content.TOPICS]
    assert len(ids) == len(set(ids))
    for tid, sec, page, title, body in help_content.TOPICS:
        assert sec in help_content.SECTIONS, tid
        assert page in (None, "download", "studio", "settings", "library", "tools", "subscriptions"), tid
        for lang in ("en", "zh"):
            assert title[lang].strip() and body[lang].strip(), (tid, lang)
        assert body["en"].count("<ol>") == body["en"].count("</ol>")
    for sec, names in help_content.SECTIONS.items():
        assert set(names) == {"en", "zh"} == set(help_content.BLURBS[sec])
    assert set(help_content.FEATURED) <= set(ids)


def test_search_finds_words_in_titles_and_text() -> None:
    assert len(help_content.search("", "en")) == len(help_content.TOPICS)
    assert "silences" in help_content.search("pauses", "en")
    assert "silences" in help_content.search("停頓", "zh")
    assert "captions_auto" in help_content.search("model captions", "en")
    assert help_content.search("zzzzqqq", "en") == []


pytestmark_gui = pytest.mark.skipif(os.environ.get("SMOKE_GUI") != "1", reason="set SMOKE_GUI=1 to enable")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytestmark_gui
def test_help_page_in_the_window(qapp, tmp_path, monkeypatch) -> None:
    from vidgrab.ui import app as m

    monkeypatch.setattr(m, "_config_dir", lambda: tmp_path)
    w = m.VidGrabWindow()
    try:
        w._sidebar.select(m.PAGE_HELP)
        assert w._stack.currentIndex() == m.PAGE_HELP
        h = w._help
        assert h.stack.currentIndex() == 0 and set(h.tiles) == set(help_content.SECTIONS)
        h.tiles["studio"].clicked.emit()  # a section opens its guides
        assert h.stack.currentIndex() == 1 and h.topic_list.count() > 1 and h.title.text()
        h.back_btn.click()
        assert h.stack.currentIndex() == 0
        h.home_search.setText("silence")  # typing on the home goes to the results
        assert h.stack.currentIndex() == 1 and h.current_id() == "silences"
        h.open_btn.click()  # the guide is about the Studio
        assert w._stack.currentIndex() == m.PAGE_STUDIO
        h.search.setText("zzzzqqq")
        assert h.current_id() is None and not h.open_btn.isVisible()
        h.show_home()
        assert h.search.text() == "" and h.stack.currentIndex() == 0
        h.chips[0][0].click()
        assert h.current_id() == help_content.FEATURED[0]
        w._lang = "zh"
        w._t = m.make_translator("zh")
        w._apply_language()
        h.open_topic("silences")
        assert h.topic_list.item(0).text() == help_content.SECTIONS["studio"]["zh"].upper()
        assert h.title.text() == help_content.TOPICS[[t[0] for t in help_content.TOPICS].index("silences")][3]["zh"]
    finally:
        w._studio.shutdown()
        w.close()
