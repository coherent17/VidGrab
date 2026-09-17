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
    assert codes == [
        "en", "zh", "ja", "ko", "es", "fr",
        "de", "pt", "it", "ru", "vi", "id",
    ]
    for label in LANGUAGES.values():
        assert " " in label
        flag, _, name = label.partition(" ")
        assert flag and not flag.isascii()
        assert name


def test_fallback_to_english() -> None:
    assert translate("fr", "Paste a YouTube link to see its details\u2026")
    assert translate("fr", "{count} videos", count=3).startswith("3")


def test_format_strings_render_in_sample_languages() -> None:
    spot = {
        "de": "Playlist herunterladen ({count} videos)",
        "ko": "\ub3d9\uc601\uc0c1 \uc815\ubcf4",
    }
    for lang in spot:
        assert lang in TRANS, f"language {lang!r} not registered"
    assert (
        translate("de", "Download playlist ({count} videos)", count=3)
        == "Playlist herunterladen (3 Videos)"
    )
    assert TRANS["ko"]["VIDEO INFO"] == "\ub3d9\uc601\uc0c1 \uc815\ubcf4"


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
        "Playlists download each video in the selected format; trim, flip and speed are skipped.",
        "Playlist",
    ]
    for lang in TRANS:
        for key in new_keys:
            assert key in TRANS[lang], f"{lang} missing {key!r}"