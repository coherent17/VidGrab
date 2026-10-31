"""Auto captions: line breaking, punctuation, time mapping and fallbacks
(a fake model stands in for Whisper; no download, no speech model)."""

from __future__ import annotations

import shutil
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from vidgrab import captions
from vidgrab.captions import (
    CaptionSource,
    Word,
    is_hallucination,
    line_text,
    split_lines,
    tidy_punctuation,
)


def words(*items: tuple[float, float, str]) -> list[Word]:
    return [Word(s, e, t) for s, e, t in items]


def test_tidy_punctuation_and_chinese_line_style() -> None:
    assert tidy_punctuation("好,我們走﹐對﹖") == "好，我們走，對？"
    assert tidy_punctuation("Yes, ok.") == "Yes, ok."  # Latin text keeps ASCII marks
    # commas / full stops inside a Chinese line become spaces; none at the end
    assert line_text(words((0, 1, "難過。"), (1, 2, "好,我們"), (2, 3, "走，"))) == "難過 好 我們走"
    assert line_text(words((0, 1, " Hello,"), (1, 2, " world,"))) == "Hello, world"


def test_split_lines_breaks_at_pauses_sentences_and_width() -> None:
    cues = split_lines(words((0.0, 0.4, " Hello"), (0.4, 0.8, " there."), (0.9, 1.3, " How"),
                             (1.3, 1.6, " are"), (1.6, 2.0, " you?"), (3.5, 4.0, " Fine")))
    assert [c.text for c in cues] == ["Hello there.", "How are you?", "Fine"]
    assert cues[0].start == 0.0 and cues[0].end <= cues[1].start
    assert cues[2].start == 3.5 and cues[2].end >= 4.0
    # a long run of CJK characters is cut to fit (40 = 20 wide characters)
    long = words(*[(i * 0.2, i * 0.2 + 0.2, "字") for i in range(30)])
    assert all(captions.text_width(c.text) <= captions.MAX_WIDTH for c in split_lines(long))


def test_split_lines_never_breaks_inside_words_or_brackets() -> None:
    w = words(*[(i * 0.2, i * 0.2 + 0.2, "字") for i in range(18)],
              (3.6, 3.8, "《"), (3.8, 4.0, "Al"), (4.0, 4.2, "umni"), (4.2, 4.4, "》"),
              (4.4, 4.6, "好"))
    texts = [c.text for c in split_lines(w)]
    assert any("《Alumni》" in t for t in texts), texts


def test_is_hallucination() -> None:
    assert is_hallucination("請不吝點贊 訂閱 轉發")
    assert is_hallucination(" Thank you for watching!")
    assert is_hallucination("hmm", no_speech_prob=0.9, avg_logprob=-1.5)
    assert not is_hallucination("Let's go baby", no_speech_prob=0.69, avg_logprob=-0.82)


class _FakeModel:
    """Says one sentence 1-3 s into whatever it hears, except with the voice
    filter on (like singing over music)."""

    def __init__(self, device: str = "cpu", fail_cuda: bool = False, vad_hears: bool = True):
        self.device, self.fail_cuda, self.vad_hears = device, fail_cuda, vad_hears
        self.calls: list[dict] = []

    def transcribe(self, audio, **opts):
        self.calls.append(opts)
        if self.device == "cuda" and self.fail_cuda:
            def boom():
                raise RuntimeError("Library libcublas.so.12 is not found")
                yield  # pragma: no cover
            return boom(), SimpleNamespace(language="en")
        seg = SimpleNamespace(start=1.0, end=3.0, text=" Hello there.", no_speech_prob=0.1,
                              avg_logprob=-0.3,
                              words=[SimpleNamespace(start=1.0, end=1.5, word=" Hello"),
                                     SimpleNamespace(start=1.6, end=3.0, word=" there.")])
        segs = [] if opts.get("vad_filter") and not self.vad_hears else [seg]
        return iter(segs), SimpleNamespace(language="en")


def _patch(monkeypatch, tmp_path, model: _FakeModel, length_s: float = 10.0) -> list:
    loaded = []

    def load_model(path, on_log, *, gpu=True):
        loaded.append(gpu)
        if gpu and model.device == "cuda":
            return model, "cuda"
        model.device = "cpu"
        return model, "cpu"

    monkeypatch.setattr(captions, "ensure_model", lambda *a, **k: tmp_path)
    monkeypatch.setattr(captions, "_load_model", load_model)
    monkeypatch.setattr(captions, "_require_ffmpeg", lambda tr=None: "ffmpeg")
    monkeypatch.setattr(captions, "load_audio",
                        lambda src, ff: np.full(int(length_s * captions.SAMPLE_RATE), 0.1, np.float32))
    return loaded


def test_transcribe_maps_source_time_to_montage_time(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path, _FakeModel())
    progress = []
    cues = captions.transcribe(
        [CaptionSource("a.mp4", 20.0, 30.0, 2.0, 5.0)], tmp_path, language="zh-Hant",
        on_progress=lambda m, p: progress.append(p))
    # 1 s and 3 s into the part, at 2x, from montage time 5
    assert [(c.start, c.text) for c in cues] == [(5.5, "Hello there.")]
    assert 6.4 < cues[0].end <= 10.0
    assert progress and all(p is None or 0 <= p <= 100 for p in progress)


def test_transcribe_falls_back_from_gpu_and_voice_filter(monkeypatch, tmp_path) -> None:
    model = _FakeModel(device="cuda", fail_cuda=True, vad_hears=False)
    loaded = _patch(monkeypatch, tmp_path, model)
    cues = captions.transcribe([CaptionSource("a.mp4", 0.0, 10.0)], tmp_path)
    assert loaded == [True, False]  # CUDA failed while decoding -> reloaded on the CPU
    assert [c.text for c in cues] == ["Hello there."]  # found without the voice filter
    assert model.calls[-1]["vad_filter"] is False


def test_transcribe_options_per_language() -> None:
    assert captions._options("auto")["language"] is None
    zh = captions._options("zh-Hant")
    assert zh["language"] == "zh" and "繁體" in zh["hotwords"]
    assert captions._options("en")["language"] == "en" and "hotwords" not in captions._options("en")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")
def test_load_audio_decodes_the_kept_part(tmp_path) -> None:
    src = tmp_path / "tone.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=4",
                    "-f", "lavfi", "-i", "color=c=black:s=64x64:d=4", "-shortest",
                    "-c:a", "aac", str(src)], check=True)
    audio = captions.load_audio(CaptionSource(str(src), 1.0, 2.5), "ffmpeg")
    assert abs(audio.size / captions.SAMPLE_RATE - 1.5) < 0.05
    silent = tmp_path / "still.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
                    str(silent)], check=True)
    assert captions.load_audio(CaptionSource(str(silent)), "ffmpeg").size == 0
