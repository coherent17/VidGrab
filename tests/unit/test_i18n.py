"""i18n coverage: every language must translate the full English key set."""

from __future__ import annotations

from vidgrab.i18n import LANGUAGES, TRANS, translate


def test_all_languages_cover_english_keys() -> None:
    en = TRANS["en"]
    for lang, table in TRANS.items():
        missing = [k for k in en if k not in table]
        assert not missing, f"{lang} is missing {len(missing)} translation keys"


def test_no_stray_keys_outside_english() -> None:
    en = TRANS["en"]
    for lang, table in TRANS.items():
        extra = [k for k in table if k not in en]
        assert not extra, f"{lang} has {len(extra)} keys not present in English"


def test_languages_include_flags() -> None:
    codes = list(LANGUAGES)
    assert codes == ["en", "zh"]
    for label in LANGUAGES.values():
        assert " " in label
        flag, _, name = label.partition(" ")
        assert flag and not flag.isascii()
        assert name


def test_fallback_to_english() -> None:
    assert translate("fr", "Paste a YouTube link to see its details\u2026")
    assert translate("fr", "{count} videos", count=3).startswith("3")


def test_format_strings_render_in_chinese() -> None:
    assert translate("zh", "{n} clips \u00b7 {dur}", n=3, dur="1:05") == "3 \u500b\u7247\u6bb5 \u00b7 1:05"
    assert TRANS["zh"]["Subtitles"] == "\u5b57\u5e55"


def test_new_feature_keys_are_translated_everywhere() -> None:
    new_keys = [
        "VIDEO INFO",
        "Paste a YouTube link to see its details\u2026",
        "Loading\u2026",
        "Download playlist ({count} videos)",
        "Download playlist",
        "{count} videos",
        "Up to {res}",
        "Downloading video {n} of {total}\u2026",
    ]
    for lang in TRANS:
        for key in new_keys:
            assert key in TRANS[lang], f"{lang} missing {key!r}"