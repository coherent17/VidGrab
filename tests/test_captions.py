"""Auto captions: line breaking, punctuation, time mapping and fallbacks
(a fake model stands in for Whisper; no download, no speech model)."""

from __future__ import annotations

import itertools
import shutil
import subprocess
import sys
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
from vidgrab.downloader import DownloadCancelled


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
    filter on and `vad_hears` off (like singing over music)."""

    def __init__(self, vad_hears: bool = True):
        self.vad_hears = vad_hears
        self.calls: list[dict] = []

    def transcribe(self, audio, **opts):
        self.calls.append(opts)
        seg = SimpleNamespace(start=1.0, end=3.0, text=" Hello there.", no_speech_prob=0.1,
                              avg_logprob=-0.3,
                              words=[SimpleNamespace(start=1.0, end=1.5, word=" Hello"),
                                     SimpleNamespace(start=1.6, end=3.0, word=" there.")])
        segs = [] if opts.get("vad_filter") and not self.vad_hears else [seg]
        return iter(segs), SimpleNamespace(language="en")


class _Recogniser:
    """Stands in for a loaded engine: one sentence per clip, 1-3 s in."""

    def __init__(self, engine: str, fail: Exception | None = None):
        self.engine, self.fail = engine, fail

    def words(self, audio, on_segment):
        on_segment(5.0)
        if self.fail:
            raise self.fail
        return [Word(1.0, 1.5, " Hello"), Word(1.6, 3.0, " there.")], "en"


def _patch(monkeypatch, recognisers: dict[str, _Recogniser], gpus=(), length_s: float = 10.0):
    loaded: list[str] = []

    def recogniser(engine, *_a, **_k):
        loaded.append(engine)
        return recognisers[engine]

    monkeypatch.setattr(captions, "_recogniser", recogniser)
    monkeypatch.setattr(captions, "detect_gpus", lambda timeout=20.0: list(gpus))
    monkeypatch.setattr(captions, "_require_ffmpeg", lambda tr=None: "ffmpeg")
    monkeypatch.setattr(captions, "load_audio",
                        lambda src, ff: np.full(int(length_s * captions.SAMPLE_RATE), 0.1, np.float32))
    return loaded


CUDA = captions.SpeechGpu("cuda", "cuda", "NVIDIA GPU")
INTEL = captions.SpeechGpu("openvino", "GPU", "Intel Arc 140T GPU")


def test_transcribe_maps_source_time_to_montage_time(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, {"cpu": _Recogniser("cpu")})
    progress = []
    cues = captions.transcribe(
        [CaptionSource("a.mp4", 20.0, 30.0, 2.0, 5.0)], tmp_path, language="zh-Hant",
        on_progress=lambda m, p: progress.append(p))
    # 1 s and 3 s into the part, at 2x, from montage time 5
    assert [(c.start, c.text) for c in cues] == [(5.5, "Hello there.")]
    assert 6.4 < cues[0].end <= 10.0
    assert progress and all(p is None or 0 <= p <= 100 for p in progress)


def test_engine_order_and_the_switch(monkeypatch) -> None:
    monkeypatch.setattr(captions, "detect_gpus", lambda timeout=20.0: [CUDA, INTEL])
    assert captions.speech_engines(True) == ["cuda", "openvino", "cpu"]
    assert captions.speech_engines(False) == ["cpu"]  # the switch is off
    monkeypatch.setattr(captions, "detect_gpus", lambda timeout=20.0: [])
    assert captions.speech_engines(True) == ["cpu"]


def test_transcribe_falls_back_engine_by_engine(monkeypatch, tmp_path) -> None:
    recognisers = {"cuda": _Recogniser("cuda", RuntimeError("Library libcublas.so.12 is not found")),
                   "openvino": _Recogniser("openvino", RuntimeError("GPU plugin failed")),
                   "cpu": _Recogniser("cpu")}
    loaded = _patch(monkeypatch, recognisers, gpus=[CUDA, INTEL])
    monkeypatch.setattr(captions.cuda_runtime, "runtime_ready", lambda models_dir: True)
    log: list[str] = []
    cues = captions.transcribe([CaptionSource("a.mp4", 0.0, 10.0)], tmp_path, on_log=log.append)
    assert loaded == ["cuda", "openvino", "cpu"]
    assert [c.text for c in cues] == ["Hello there."]
    assert any("cuda failed" in line and "openvino" in line for line in log)

    loaded[:] = []  # the switch off: straight to the CPU
    captions.transcribe([CaptionSource("a.mp4", 0.0, 10.0)], tmp_path, gpu=False)
    assert loaded == ["cpu"]

    # the CPU engine's own failure is not swallowed; neither is a cancel
    recognisers["cpu"] = _Recogniser("cpu", RuntimeError("out of memory"))
    with pytest.raises(RuntimeError, match="out of memory"):
        captions.transcribe([CaptionSource("a.mp4", 0.0, 10.0)], tmp_path, gpu=False)
    loaded[:] = []
    recognisers["cuda"] = _Recogniser("cuda", DownloadCancelled())
    with pytest.raises(DownloadCancelled):
        captions.transcribe([CaptionSource("a.mp4", 0.0, 10.0)], tmp_path)
    assert loaded == ["cuda"]  # stopped, not retried on the next engine


def test_faster_whisper_retries_without_the_voice_filter() -> None:
    model = _FakeModel(vad_hears=False)
    engine = captions._FasterWhisper.__new__(captions._FasterWhisper)
    engine.model, engine.opts = model, {"vad_filter": True}
    loud = np.full(captions.SAMPLE_RATE, 0.3, np.float32)  # music, not silence
    words, lang = engine.words(loud, lambda t: None)
    assert [w.text for w in words] == [" Hello", " there."] and lang == "en"
    assert [c["vad_filter"] for c in model.calls] == [True, False]
    model.calls.clear()
    assert engine.words(np.zeros(captions.SAMPLE_RATE, np.float32), lambda t: None)[0] == []
    assert len(model.calls) == 1  # silence stays silence


def test_speech_device_messages(monkeypatch) -> None:
    monkeypatch.setattr(captions, "speech_threads", lambda: 6)
    monkeypatch.setattr(captions, "gpus_checked", lambda: False)
    assert captions.speech_device(True)[0] == "Checking this computer…"
    assert captions.speech_device(False) == ("Auto captions run on the CPU ({n} threads).", {"n": 6})
    monkeypatch.setattr(captions, "gpus_checked", lambda: True)
    monkeypatch.setattr(captions, "detect_gpus", lambda timeout=20.0: [INTEL])
    key, fill = captions.speech_device(True)
    assert key.startswith("Ready: {name}") and fill == {"name": "Intel Arc 140T GPU"}
    assert captions.speech_device(False)[1] == {"n": 6}  # switched off: CPU even with a GPU
    monkeypatch.setattr(captions, "detect_gpus", lambda timeout=20.0: [])
    assert captions.speech_device(True)[0].startswith("No supported graphics card") \
        and captions.speech_device(True)[1] == {"n": 6}


def test_chunk_words_spreads_a_segment_over_its_text() -> None:
    words = captions.chunk_words("這是Alumni，對", 10.0, 14.0)
    assert [w.text for w in words] == ["這", "是", "Alumni", "，", "對"]
    assert words[0].start == 10.0 and words[-1].end == 14.0
    assert all(a.end == b.start for a, b in itertools.pairwise(words))  # no gaps
    assert words[3].start == words[3].end  # punctuation takes no time
    assert words[2].end - words[2].start > words[0].end - words[0].start  # a long word, longer
    lines = split_lines(captions.chunk_words("Hello there. How are you", 0.0, 3.0))
    assert [c.text for c in lines] == ["Hello there.", "How are you"]
    assert captions.chunk_words("  ", 0, 1) == [] and captions.chunk_words("，", 0, 1)[0].text == "，"


def test_audio_slices_cut_in_quiet_places_and_lose_nothing() -> None:
    sr = captions.SAMPLE_RATE
    rng = np.random.default_rng(1)
    audio = (rng.standard_normal(150 * sr) * 0.1).astype(np.float32)
    audio[int(62.0 * sr):int(62.5 * sr)] = 0  # a pause just after the 60 s mark
    pieces = list(captions.audio_slices(audio))
    assert 62.0 <= pieces[0][1].size / sr <= 62.5  # cut inside the pause, not at 60.0
    assert sum(p.size for _, p in pieces) == audio.size and pieces[0][0] == 0.0
    assert all(abs(off * sr - sum(q.size for _, q in pieces[:k])) < 1 for k, (off, _) in enumerate(pieces))
    assert [round(o) for o, _ in captions.audio_slices(audio[:30 * sr])] == [0]  # short: one piece


def test_openvino_engine_reads_segments_and_skips_silence_and_stock_lines() -> None:
    chunk = lambda a, b, text: SimpleNamespace(start_ts=a, end_ts=b, text=text)

    class Pipe:
        def __init__(self):
            self.sent = []

        def get_generation_config(self):
            return SimpleNamespace(language=None, task=None, return_timestamps=False, initial_prompt=None)

        def generate(self, samples, cfg):
            self.sent.append((len(samples), cfg.language, cfg.initial_prompt))
            return SimpleNamespace(language="zh", chunks=[chunk(0.0, 2.0, "你好嗎"),
                                                          chunk(2.0, 3.0, "請不吝點贊訂閱")])

    engine = captions._OpenVino.__new__(captions._OpenVino)
    engine.pipe, engine.language, engine.prompt = Pipe(), None, "繁體"
    sr = captions.SAMPLE_RATE
    audio = np.concatenate([np.full(60 * sr, 0.2, np.float32), np.zeros(60 * sr, np.float32),
                            np.full(5 * sr, 0.2, np.float32)])
    words, lang = engine.words(audio, lambda t: None)
    assert "".join(w.text for w in words).count("你好嗎") == 2  # loud pieces only
    assert "訂閱" not in "".join(w.text for w in words) and lang == "zh"
    assert engine.language == "zh" and engine.pipe.sent[1][1] == "<|zh|>"  # kept for the next piece
    assert len(engine.pipe.sent) == 2 and engine.pipe.sent[0][2] == "繁體"


def test_model_layout_and_sizes(tmp_path) -> None:
    assert captions.model_dir(tmp_path, "best") == tmp_path / "best"
    assert captions.model_dir(tmp_path, "best", "cuda") == tmp_path / "best"
    assert captions.model_dir(tmp_path, "best", "openvino") == tmp_path / "openvino" / "best"
    assert captions.model_info("best", "openvino")[0].startswith("OpenVINO/")
    assert captions.model_info("best")[1] == "1.6 GB"
    assert not captions.model_ready(tmp_path, "fast", "openvino")
    (tmp_path / "openvino" / "fast").mkdir(parents=True)
    (tmp_path / "openvino" / "fast" / "COMPLETE").write_text("x")
    assert captions.model_ready(tmp_path, "fast", "openvino") and not captions.model_ready(tmp_path, "fast")


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


def test_openvino_never_loads_its_telemetry() -> None:
    """`import openvino` alone posts to Google Analytics through
    openvino_telemetry; VidGrab must keep it unimportable so nothing is sent."""
    pytest.importorskip("openvino")
    code = (
        "import sys, socket\n"
        "def no_network(*a, **k): raise AssertionError('network used: %r' % (a,))\n"
        "socket.socket.connect = no_network\n"
        "from vidgrab import captions\n"
        "import openvino as ov\n"
        "ov.Core().available_devices\n"
        "import openvino_genai, openvino_tokenizers\n"
        "assert sys.modules['openvino_telemetry'] is None\n"
        "assert not any(k.startswith('openvino_telemetry.') for k in sys.modules)\n"
        "print('quiet')\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          timeout=120, check=False)
    assert done.returncode == 0 and "quiet" in done.stdout, done.stderr[-600:]


def test_nvidia_waits_for_its_download_when_an_intel_gpu_can_start_now(monkeypatch, tmp_path) -> None:
    from vidgrab import cuda_runtime

    monkeypatch.setattr(captions, "detect_gpus", lambda timeout=20.0: [CUDA, INTEL])
    monkeypatch.setattr(cuda_runtime, "runtime_ready", lambda models_dir: False)
    assert captions.speech_engines(True, tmp_path) == ["openvino", "cuda", "cpu"]
    monkeypatch.setattr(cuda_runtime, "runtime_ready", lambda models_dir: True)
    assert captions.speech_engines(True, tmp_path) == ["cuda", "openvino", "cpu"]
    # with only NVIDIA there is nothing to wait for: it downloads, then runs
    monkeypatch.setattr(captions, "detect_gpus", lambda timeout=20.0: [CUDA])
    monkeypatch.setattr(cuda_runtime, "runtime_ready", lambda models_dir: False)
    assert captions.speech_engines(True, tmp_path) == ["cuda", "cpu"]
    monkeypatch.setattr(captions, "gpus_checked", lambda: True)
    key, fill = captions.speech_device(True, tmp_path)
    assert "download the NVIDIA CUDA libraries" in key and fill["name"] == "NVIDIA GPU" and fill["size"]


def test_cuda_engine_gets_its_libraries_before_the_model(monkeypatch, tmp_path) -> None:
    from vidgrab import cuda_runtime

    order: list[str] = []
    monkeypatch.setattr(cuda_runtime, "ensure_runtime", lambda *a, **k: order.append("libs"))
    monkeypatch.setattr(captions, "ensure_model", lambda *a, **k: order.append("model") or tmp_path)
    monkeypatch.setattr(captions, "_FasterWhisper", lambda path, device, lang, log: order.append(device))
    captions._recogniser("cuda", tmp_path, "fast", "auto", None, None, None)
    assert order == ["libs", "model", "cuda"]
    order.clear()
    captions._recogniser("cpu", tmp_path, "fast", "auto", None, None, None)
    assert order == ["model", "cpu"]  # the CPU needs no CUDA


# ── fallbacks: nothing may hang or crash ────────────────────────────────


@pytest.fixture
def fresh_detection(monkeypatch):
    """Empty the module-level detection state (shared across tests otherwise)."""
    monkeypatch.setattr(captions, "_gpus", [])
    monkeypatch.setattr(captions, "_detector", [])
    monkeypatch.setattr(captions, "_gave_up", [])
    monkeypatch.setattr(captions, "cuda_available", lambda: False)


def test_gpu_detection_never_waits_on_a_hung_driver(monkeypatch, fresh_detection) -> None:
    import threading
    import time

    release = threading.Event()
    monkeypatch.setattr(captions, "_openvino_gpu", lambda: release.wait(30) and INTEL)
    t0 = time.monotonic()
    assert captions.detect_gpus(timeout=0.3) == []  # gave up: counts as "no card"
    assert time.monotonic() - t0 < 5 and captions.gpus_checked()
    assert captions.speech_engines(True, timeout=0.1) == ["cpu"]  # captions go to the CPU, no waiting
    release.set()  # the driver answers after all
    captions._detector[0].join(5)
    assert captions.detect_gpus(timeout=0.3) == [INTEL]  # later calls use the answer
    # a driver that raises is just "no card"
    monkeypatch.setattr(captions, "_gpus", [])
    monkeypatch.setattr(captions, "_detector", [])
    monkeypatch.setattr(captions, "_openvino_gpu", lambda: (_ for _ in ()).throw(OSError("driver")))
    assert captions.detect_gpus(timeout=5) == []


def _fake_openvino(monkeypatch, *, kind: str, units, name: str = "Intel(R) UHD Graphics 620"):
    props = {"FULL_DEVICE_NAME": name, "DEVICE_TYPE": f"Type.{kind}"}

    class Core:
        @property
        def available_devices(self):
            return ["CPU", "GPU"]

        def get_property(self, dev, prop):
            if prop == "GPU_EXECUTION_UNITS_COUNT":
                if units is None:
                    raise RuntimeError("unsupported")
                return units
            return props[prop]

    monkeypatch.setitem(sys.modules, "openvino", SimpleNamespace(Core=Core))


@pytest.mark.parametrize(("kind", "units", "basic"), [
    ("INTEGRATED", 24, True),    # UHD 620 (6th-10th gen): kept, but flagged
    ("INTEGRATED", 128, False),  # Arc 140T
    ("INTEGRATED", 96, False),   # Iris Xe
    ("INTEGRATED", None, False),  # size unknown: not flagged
    ("DISCRETE", 32, False),     # a discrete card is never flagged
])
def test_basic_integrated_graphics_are_kept_and_described(monkeypatch, fresh_detection,
                                                          kind, units, basic) -> None:
    _fake_openvino(monkeypatch, kind=kind, units=units)
    gpu = captions._openvino_gpu()
    assert gpu is not None and gpu.basic is basic  # never left out: the user decides
    assert gpu.name == "Intel UHD Graphics 620"
    monkeypatch.setattr(captions, "gpus_checked", lambda: True)
    monkeypatch.setattr(captions, "detect_gpus", lambda timeout=20.0: [gpu])
    assert captions.speech_engines(True) == ["openvino", "cpu"]  # it is used
    key, fill = captions.speech_device(True)
    assert key.startswith("{name} found. It is basic graphics") == basic
    assert key.startswith("Ready: {name}") == (not basic) and fill == {"name": gpu.name}


def test_model_download_failures_are_friendly_and_leave_no_half_files(monkeypatch, tmp_path) -> None:
    import io
    import json as jsonlib
    import urllib.error

    from vidgrab.downloader import DownloadCancelled

    def offline(*_a, **_k):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr(captions.urllib.request, "urlopen", offline)
    with pytest.raises(RuntimeError, match="Check your internet connection"):
        captions.ensure_model(tmp_path, "fast", engine="cpu")

    # an error object instead of a file list (rate limit)
    monkeypatch.setattr(captions.urllib.request, "urlopen",
                        lambda *_a, **_k: io.BytesIO(jsonlib.dumps({"error": "rate limited"}).encode()))
    with pytest.raises(RuntimeError, match="Check your internet connection"):
        captions.ensure_model(tmp_path, "fast", engine="cpu")

    # the connection drops half way / the user cancels: no .part file stays behind
    tree = [{"type": "file", "path": "model.bin", "size": 3 << 20}, {"type": "file", "path": "config.json", "size": 2}]

    class Stream(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(url, **_k):
        if "/api/models/" in url:
            return Stream(jsonlib.dumps(tree).encode())
        return Stream(b"x" * (3 << 20))

    monkeypatch.setattr(captions.urllib.request, "urlopen", opener)

    def cancel(msg, pct):
        raise DownloadCancelled

    with pytest.raises(DownloadCancelled):
        captions.ensure_model(tmp_path, "fast", engine="cpu", on_progress=cancel)
    assert not list(tmp_path.rglob("*.part")) and not captions.model_ready(tmp_path, "fast")
    captions.ensure_model(tmp_path, "fast", engine="cpu")  # and a retry completes
    assert captions.model_ready(tmp_path, "fast")


def test_installed_tells_a_pip_install_without_the_extra(monkeypatch):
    import importlib.util

    assert captions.installed()  # this environment has the add-on
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a: None if name == "faster_whisper" else real(name, *a))
    assert not captions.installed()
