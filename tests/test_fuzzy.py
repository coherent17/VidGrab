from __future__ import annotations

from vidgrab import fuzzy
from vidgrab.fuzzy import FuzzyIndex, Trie


def test_trie_prefix_and_typo_walks() -> None:
    t = Trie()
    for w in ("caption", "captions", "capture", "cat", "shrink", "silence"):
        t.add(w)
    assert "cat" in t and "ca" not in t and t.size == 6
    assert t.with_prefix("capt") == ["caption", "capture", "captions"]
    assert t.with_prefix("zzz") == []
    near = dict(t.within("captoin", 2))  # letters swapped
    assert near["caption"] == 1 and "cat" not in near
    assert dict(t.within("shrnk", 1))["shrink"] == 1
    assert t.prefix_within("captoi", 1) and "caption" in t.prefix_within("captoi", 1)


def test_normalising_and_cjk_words() -> None:
    assert fuzzy.normalize("Café ÉCOLE") == "cafe ecole"
    assert fuzzy.words("字幕 Auto") == ["字", "幕", "字幕", "auto"]
    assert fuzzy.allowed_typos("cat") == 0 and fuzzy.allowed_typos("caption") == 2


def _idx() -> FuzzyIndex:
    ix = FuzzyIndex()
    ix.add("shrink", "Make a video fit a size limit", ("Shrink to a size", 3.0), ("compress video size discord", 1.0))
    ix.add("captions", "Automatic captions", ("Automatic captions", 3.0), ("speech model language subtitles", 1.0))
    ix.add("music", "Background music and volume", ("Background music", 3.0), ("song fade loop", 1.0))
    ix.add("字幕", "自動字幕", ("自動字幕", 3.0), ("語音 模型", 1.0))
    return ix


def test_search_finds_typos_prefixes_and_subsequences() -> None:
    ix = _idx()
    assert ix.search("captions")[0][0] == "captions"
    assert ix.search("captoins")[0][0] == "captions"  # swapped letters
    assert ix.search("shrnk")[0][0] == "shrink"  # a dropped letter
    assert ix.search("compres vid")[0][0] == "shrink"  # half-typed last word, a missing letter
    assert ix.search("auto capt")[0][0] == "captions"  # prefixes of both words
    assert ix.search("MUSIC")[0][0] == "music"
    assert ix.search("zzzzqqq") == [] and ix.search("") == []
    assert ix.search("captions video") == []  # every word has to match something


def test_search_chinese_and_ranking() -> None:
    ix = _idx()
    assert ix.search("字幕")[0][0] == "字幕" and ix.search("幕")[0][0] == "字幕"
    ix2 = FuzzyIndex()
    ix2.add("body", "Other", ("Other", 3.0), ("how to cut a video in the studio", 1.0))
    ix2.add("title", "Video cutter", ("Video cutter", 3.0))
    assert [k for k, _ in ix2.search("video")] == ["title", "body"]  # a title hit beats a body hit
    ix3 = FuzzyIndex()
    ix3.add(1, "red car blue")
    ix3.add(2, "blue car red")
    assert next(k for k, _ in ix3.search("car red")) == 2  # the whole phrase scores extra


def test_suggest_and_did_you_mean() -> None:
    ix = _idx()
    assert ix.suggest("auto")[0] == "Automatic captions"
    assert ix.suggest("backgr mus")[0] == "Background music and volume"
    assert ix.did_you_mean("captoins") == "captions"
    assert ix.did_you_mean("captions") is None
    assert ix.did_you_mean("qqqqqqq") is None
