from vidgrab.core import downloader


def _opts(fmt):
    return downloader._ytdl_options("u", downloader.Path("."), fmt, ffmpeg=None)


def test_sponsorblock_is_off_by_default():
    downloader.configure_network()
    assert "postprocessors" not in _opts("mp4")
    assert [p["key"] for p in _opts("mp3")["postprocessors"]] == ["FFmpegExtractAudio"]


def test_sponsorblock_cuts_before_the_audio_is_extracted():
    downloader.configure_network(sponsorblock=True)
    try:
        assert [p["key"] for p in _opts("mp4")["postprocessors"]] == ["SponsorBlock", "ModifyChapters"]
        assert [p["key"] for p in _opts("mp3")["postprocessors"]] == [
            "SponsorBlock", "ModifyChapters", "FFmpegExtractAudio"]
        live = downloader._ytdl_options("u", downloader.Path("."), "mp4", ffmpeg=None, live=True)
        assert "postprocessors" not in live
    finally:
        downloader.configure_network()
