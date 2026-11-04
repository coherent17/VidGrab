import re

from vidgrab.ai import captions
from vidgrab.media import studio
from vidgrab.media.studio import SubtitleCue


def _cue(anim):
    # "Hello big world": Hello 0.2-0.5 s, big 0.6-0.9 s, world 1.0-1.6 s
    return SubtitleCue(10.0, 12.0, "Hello big world", animation=anim,
                       words=[[0, 5, 0.2, 0.5], [6, 9, 0.6, 0.9], [10, 15, 1.0, 1.6]])


def test_captions_carry_when_each_word_is_said():
    W = captions.Word
    words = [W(1.0, 1.4, " Hello"), W(1.4, 1.9, " wor"), W(1.9, 2.2, "ld,"), W(2.6, 3.0, " again")]
    (cue,) = captions.split_lines(words)
    assert cue.text == "Hello world, again"
    assert cue.words == [[0, 5, 0.0, 0.4], [6, 11, 0.4, 1.2], [13, 18, 1.6, 2.0]]
    zh = [W(0, .3, "你"), W(.3, .6, "好"), W(.6, 1.0, "，"), W(1.0, 1.4, "世"), W(1.4, 1.8, "界")]
    (cue,) = captions.split_lines(zh)
    assert cue.text == "你好 世界" and [w[:2] for w in cue.words] == [[0, 1], [1, 2], [3, 4], [4, 5]]


def test_word_spans_ignore_timings_that_no_longer_fit_the_text():
    cue = _cue("karaoke")
    assert len(studio.word_spans(cue)) == 3
    cue.text = "Hi"  # edited: the old spans point past the end
    assert studio.word_spans(cue) == []
    assert studio.word_spans(SubtitleCue(0, 1, "x", words=[[0, 1, 0.5, 0.2]])) == []


def test_karaoke_sweeps_at_the_pace_of_the_words():
    ass = studio.format_ass([_cue("karaoke")], 1280, 720)
    line = next(ln for ln in ass.splitlines() if ln.startswith("Dialogue"))
    cs = [int(x) for x in re.findall(r"\\kf(\d+)", line)]
    assert len(cs) == len("Hello big world")
    assert sum(cs[:5]) == 50  # Hello: 0.5 s
    assert sum(cs[:9]) == 90  # up to the end of "big" (0.9 s)
    assert sum(cs) == 160  # the whole line ends with the last word


def test_highlight_makes_one_event_per_word():
    ass = studio.format_ass([_cue("highlight")], 1280, 720)
    events = [ln for ln in ass.splitlines() if ln.startswith("Dialogue")]
    assert len(events) == 4  # nothing said yet, then each of the three words
    hot = studio._bgr(studio.HIGHLIGHT)
    assert [hot in e for e in events] == [False, True, True, True]
    assert events[0].startswith("Dialogue: 0,0:00:10.00,0:00:10.20")  # the line is on before the first word
    assert events[1].count("Hello") == 1 and f"{{\\1c{hot}" in events[1].split("Hello")[0]


def test_highlight_without_timings_falls_back_to_an_even_sweep():
    cue = SubtitleCue(0, 2, "Plain line", animation="highlight")
    ass = studio.format_ass([cue], 1280, 720)
    events = [ln for ln in ass.splitlines() if ln.startswith("Dialogue")]
    assert len(events) == 1 and "\\kf" in events[0]


def test_char_times_and_active_word():
    spans = studio.word_spans(_cue("karaoke"))
    src = list(range(15))
    ends = studio.char_end_times(src, spans)
    assert ends[4] == 0.5 and ends[8] == 0.9 and ends[14] == 1.6
    assert studio.active_word(spans, 0.2) == 0 and studio.active_word(spans, 0.55) is None
    assert studio.active_word(spans, 1.2) == 2
