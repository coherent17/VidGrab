"""Tests for jobs.py — download + subtitle orchestration (network mocked)."""

from __future__ import annotations

from pathlib import Path

from vidgrab import jobs
from vidgrab.jobs import DownloadJob, run_job
from vidgrab.studio import SubtitleCue, retime_cues

SRT = "1\n00:00:01,000 --> 00:00:03,000\nfirst\n\n2\n00:00:10,000 --> 00:00:12,000\nsecond\n"


def test_retime_cues_trim_and_speed() -> None:
    cues = [SubtitleCue(1, 3, "a"), SubtitleCue(10, 12, "b"), SubtitleCue(20, 22, "c")]
    out = retime_cues(cues, start=2.0, end=11.0, speed=2.0)
    assert [(c.start, c.end, c.text) for c in out] == [(0.0, 0.5, "a"), (4.0, 4.5, "b")]


def test_run_job_saves_retimed_subtitles(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "Song.mp4"
    media.write_bytes(b"x")
    monkeypatch.setattr(jobs, "download", lambda *a, **k: media)

    def fake_fetch(url, out_dir, lang, base, **kw):
        srt = Path(out_dir) / f"{base}.{lang}.srt"
        srt.write_text(SRT, encoding="utf-8")
        return srt

    monkeypatch.setattr(jobs, "fetch_subtitles", fake_fetch)
    job = DownloadJob(url="u", output_dir=str(tmp_path), subtitles="en", section_start="0:09")
    files = run_job(job)
    assert files[0] == media and files[1].name == "Song.en.srt"
    text = files[1].read_text(encoding="utf-8")
    # trimmed to start at 0:09 -> the second line now starts at 1 s; the first is gone
    assert "first" not in text and "00:00:01,000 --> 00:00:03,000\nsecond" in text


def test_run_job_without_captions_returns_media_only(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "a.mp3"
    media.write_bytes(b"x")
    monkeypatch.setattr(jobs, "download", lambda *a, **k: media)
    monkeypatch.setattr(jobs, "fetch_subtitles", lambda *a, **k: None)
    assert run_job(DownloadJob(url="u", output_dir=str(tmp_path), fmt="mp3",
                               subtitles="ja")) == [media]


def test_run_job_playlist_skips_subtitles(tmp_path: Path, monkeypatch) -> None:
    out = [tmp_path / "01 - a.mp4"]
    monkeypatch.setattr(jobs, "download_playlist", lambda *a, **k: out)
    monkeypatch.setattr(jobs, "fetch_subtitles", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert run_job(DownloadJob(url="u", output_dir=str(tmp_path), playlist=True,
                               subtitles="en")) == out
