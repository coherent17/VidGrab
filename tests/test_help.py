"""The Help page: both languages for every topic, search, and the window wiring."""
from __future__ import annotations

import os

import pytest

from vidgrab import help_content


def test_every_topic_has_both_languages_and_a_known_section() -> None:
    ids = [t[0] for t in help_content.TOPICS]
    assert len(ids) == len(set(ids))
    for tid, sec, page, title, body in help_content.TOPICS:
        assert sec in help_content.SECTIONS, tid
        assert page in (None, 0, 1, 2), tid
        for lang in ("en", "zh"):
            assert title[lang].strip() and body[lang].strip(), (tid, lang)
        assert body["en"].count("<ol>") == body["en"].count("</ol>")
    for names in help_content.SECTIONS.values():
        assert set(names) == {"en", "zh"}


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
    from vidgrab import app as m

    monkeypatch.setattr(m, "_config_dir", lambda: tmp_path)
    w = m.VidGrabWindow()
    try:
        w._sidebar.select(m.PAGE_HELP)
        assert w._stack.currentIndex() == m.PAGE_HELP
        h = w._help
        assert h.current_id() == help_content.TOPICS[0][0] and h.title.text()
        h.search.setText("silence")
        assert h.current_id() == "silences"
        h.open_btn.click()  # the guide is about the Studio
        assert w._stack.currentIndex() == m.PAGE_STUDIO
        h.search.setText("zzzzqqq")
        assert h.current_id() is None and not h.open_btn.isVisible()
        h.search.clear()
        w._lang = "zh"
        w._t = m.make_translator("zh")
        w._apply_language()
        assert h.topic_list.item(0).text() == help_content.SECTIONS["start"]["zh"].upper()
        h.open_topic("silences")
        assert h.title.text() == help_content.TOPICS[[t[0] for t in help_content.TOPICS].index("silences")][3]["zh"]
    finally:
        w._studio.shutdown()
        w.close()
