"""Auto captions: speech in the Studio's clips -> timed subtitle lines.

Qt-free, like studio.py. Speech recognition is Whisper, run locally; only the
model is downloaded, once, on first use (``<config>/models``). Audio is
decoded by our own ffmpeg straight to 16 kHz mono samples, so PyAV (which
faster-whisper would otherwise use) isn't needed and isn't bundled.

Three engines, tried in this order when the graphics-card switch is on, each
falling back to the next if it can't load or fails while decoding:

* ``cuda``     faster-whisper (CTranslate2) on an NVIDIA GPU;
* ``openvino`` OpenVINO GenAI on an Intel GPU (integrated or Arc): the large
               "Best" model runs there as fast as the small one does on the CPU;
* ``cpu``      faster-whisper int8 on the CPU, on its fast cores only
               (``gpu.speech_threads``).

``transcribe()`` takes each clip's kept part of its source (start / end /
speed / where it sits in the montage) and returns ``SubtitleCue``s in
montage time, split into readable lines by the word timings (or, for
OpenVINO, which gives segment times, by timings spread over each segment).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import types
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from vidgrab import cuda_runtime
from vidgrab.downloader import (
    DownloadCancelled,
    LogCallback,
    ProgressCallback,
    TranslateFn,
    _noop_tr,
)
from vidgrab.gpu import speech_threads
from vidgrab.studio import SubtitleCue, _no_window, _require_ffmpeg

# OpenVINO sends usage analytics to Google Analytics as soon as it is imported
# (through its `openvino_telemetry` package). VidGrab keeps everything on this
# computer, so make that package unimportable: OpenVINO then uses its own no-op
# stand-in. This must run before anything imports openvino.
sys.modules.setdefault("openvino_telemetry", None)  # type: ignore[arg-type]

SAMPLE_RATE = 16000  # what Whisper expects

# accuracy key -> (Hugging Face repo, download size label), per model format:
# CTranslate2 for faster-whisper (cuda / cpu), OpenVINO int8 for the Intel GPU
MODELS: dict[str, tuple[str, str]] = {
    "fast": ("Systran/faster-whisper-base", "150 MB"),
    "balanced": ("Systran/faster-whisper-small", "490 MB"),
    "best": ("deepdml/faster-whisper-large-v3-turbo-ct2", "1.6 GB"),
}
OV_MODELS: dict[str, tuple[str, str]] = {
    "fast": ("OpenVINO/whisper-base-int8-ov", "85 MB"),
    "balanced": ("OpenVINO/whisper-small-int8-ov", "260 MB"),
    "best": ("OpenVINO/whisper-large-v3-turbo-int8-ov", "830 MB"),
}
DEFAULT_MODEL = "balanced"
_MODEL_FILES = ("config.json", "preprocessor_config.json", "model.bin", "tokenizer.json",
                "vocabulary.txt", "vocabulary.json")
_HF = "https://huggingface.co"

# spoken language choices: code -> name in that language ("auto" = detect).
# Whisper knows ~100 languages and "auto" covers all of them; these are the
# ones worth picking by hand. Chinese is one Whisper language ("zh"), so the
# script is steered with a prompt written in it.
LANGUAGES: dict[str, str] = {
    "auto": "",
    "en": "English",
    "zh-Hant": "中文（繁體）",
    "zh-Hans": "中文（简体）",
    "ja": "日本語",
    "ko": "한국어",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "pt": "Português",
    "it": "Italiano",
    "ru": "Русский",
    "vi": "Tiếng Việt",
    "id": "Bahasa Indonesia",
}
_PROMPTS = {
    "zh-Hant": "以下是繁體中文的句子，請使用繁體字。",
    "zh-Hans": "以下是简体中文的句子。",
}

# line breaking: CJK characters count double, as they are about twice as wide
MAX_WIDTH = 40
MAX_LINE_S = 6.0
PAUSE_S = 0.7  # a silence this long starts a new line
MIN_LINE_S = 0.8


@dataclass
class CaptionSource:
    """One clip's kept part: source *start*..*end* seconds (end None = to the
    end of the file) played at *speed*, starting at montage time *offset*."""

    path: str
    start: float = 0.0
    end: float | None = None
    speed: float = 1.0
    offset: float = 0.0


@dataclass
class Word:
    start: float
    end: float
    text: str


# ── model download ─────────────────────────────────────────────────────


def model_info(size: str, engine: str = "cpu") -> tuple[str, str]:
    """(Hugging Face repo, download size label) of the *size* model *engine* uses."""
    return (OV_MODELS if engine == "openvino" else MODELS)[size]


def model_dir(models_dir: str | Path, size: str, engine: str = "cpu") -> Path:
    base = Path(models_dir)
    return base / "openvino" / size if engine == "openvino" else base / size


def model_ready(models_dir: str | Path, size: str, engine: str = "cpu") -> bool:
    return (model_dir(models_dir, size, engine) / "COMPLETE").is_file()


def ensure_model(
    models_dir: str | Path,
    size: str = DEFAULT_MODEL,
    *,
    engine: str = "cpu",
    on_progress: ProgressCallback | None = None,
    translate: TranslateFn | None = None,
) -> Path:
    """The model folder for *size* (in *engine*'s format), downloading it first
    if needed."""
    tr = translate or _noop_tr
    dest = model_dir(models_dir, size, engine)
    if model_ready(models_dir, size, engine):
        return dest
    ov = engine == "openvino"
    repo = model_info(size, engine)[0]
    offline = tr("The speech model could not be downloaded. Check your internet connection.")
    try:
        with urllib.request.urlopen(f"{_HF}/api/models/{repo}/tree/main", timeout=30) as resp:
            tree = json.load(resp)
        if not isinstance(tree, list):  # an error object (rate limit, removed repo)
            raise TypeError(str(tree)[:120])
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"{offline} ({exc})") from exc
    files = [(f["path"], int(f.get("size") or 0)) for f in tree
             if f.get("type", "file") == "file" and (
                 (not f["path"].startswith(".") and f["path"] != "README.md") if ov
                 else f["path"] in _MODEL_FILES)]
    if not any(name == ("openvino_encoder_model.xml" if ov else "model.bin") for name, _ in files):
        raise RuntimeError(tr("The speech model could not be found online."))
    dest.mkdir(parents=True, exist_ok=True)
    total = sum(size for _, size in files) or 1
    done = 0
    last = -1
    for name, expected in files:
        target = dest / name
        if target.is_file() and expected and target.stat().st_size == expected:
            done += expected
            continue
        part = target.with_name(name + ".part")
        try:
            with urllib.request.urlopen(f"{_HF}/{repo}/resolve/main/{name}", timeout=60) as resp, \
                    open(part, "wb") as fh:
                while chunk := resp.read(1 << 20):
                    fh.write(chunk)
                    done += len(chunk)
                    pct = int(done * 100 / total)
                    if on_progress and pct != last:
                        last = pct
                        on_progress(tr("Downloading the speech model…"), min(pct, 100))
        except OSError as exc:  # no network, a dropped connection, a full disk
            part.unlink(missing_ok=True)
            raise RuntimeError(f"{offline} ({exc})") from exc
        except BaseException:  # cancelled: don't leave a half file behind
            part.unlink(missing_ok=True)
            raise
        os.replace(part, target)
    (dest / "COMPLETE").write_text(repo + "\n", encoding="utf-8")
    return dest


# ── audio ──────────────────────────────────────────────────────────────


def load_audio(src: CaptionSource, ffmpeg: str):
    """The source part as 16 kHz mono float32 samples (empty if it has no sound)."""
    import numpy as np

    cmd = [ffmpeg, "-nostdin", "-v", "error", "-ss", f"{max(0.0, src.start):.3f}"]
    if src.end is not None:
        cmd += ["-t", f"{max(0.0, src.end - src.start):.3f}"]
    cmd += ["-i", str(src.path), "-map", "0:a:0?", "-vn", "-ac", "1",
            "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"]
    proc = subprocess.run(cmd, capture_output=True, check=False, **_no_window())
    return np.frombuffer(proc.stdout, dtype=np.float32)


# ── line breaking ──────────────────────────────────────────────────────


def text_width(text: str) -> int:
    return sum(2 if _wide(ch) else 1 for ch in text)


def _wide(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


# Whisper sometimes writes Chinese with small-form (U+FE50…) or ASCII marks
_SMALL_FORMS = str.maketrans("﹐﹑﹒﹔﹕﹖﹗", "，、。；：？！")
_HALF_TO_FULL = {",": "，", "!": "！", "?": "？", ";": "；", ":": "："}


def tidy_punctuation(text: str) -> str:
    """Full-width punctuation in Chinese / Japanese text: small forms, and
    ASCII marks that follow a CJK character (``好,我們`` -> ``好，我們``)."""
    text = text.translate(_SMALL_FORMS)
    out = []
    for i, ch in enumerate(text):
        if ch in _HALF_TO_FULL and i and _wide(text[i - 1]):
            ch = _HALF_TO_FULL[ch]
        elif ch == "." and i and _wide(text[i - 1]) and (i + 1 == len(text) or text[i + 1] == " "):
            ch = "。"
        out.append(ch)
    return "".join(out)


_SENTENCE_END = tuple(".!?。！？…")
_PAUSE_MARKS = tuple(",;:，、；：")
_OPENING = tuple("《「『（(“‘[")
_CLOSING = tuple("》」』）)”’]，。！？、,.!?")


def line_text(words: list[Word]) -> str:
    """The words as one subtitle line. Chinese / Japanese lines follow the
    usual subtitle style: a space instead of a comma, no full stop or comma at
    the end; other lines just lose a trailing comma."""
    text = tidy_punctuation("".join(w.text for w in words)).strip()
    if any(_wide(ch) for ch in text):
        text = text.rstrip("，、。；：,;: ")
        for mark in "，、；。":
            text = text.replace(mark, " ")
        return " ".join(text.split())
    return text.rstrip(",; ").strip()


def _joined(a: Word, b: Word) -> bool:
    """*b* continues the same Latin word / number / abbreviation as *a*
    ("S" + "ummer", "U." + "C"): never break a line there."""
    left, right = a.text.rstrip(), b.text
    return bool(left and right and not right[0].isspace() and right[0].isascii()
                and right[0].isalnum() and left[-1].isascii() and (left[-1].isalnum() or left[-1] == "."))


def _break_score(line: list[Word], i: int) -> float:
    """How good a place for a line break the gap before ``line[i]`` is."""
    prev = tidy_punctuation(line[i - 1].text).rstrip()
    if (_joined(line[i - 1], line[i]) or prev.endswith(_OPENING)
            or line[i].text.strip().startswith(_CLOSING)):
        return -1.0
    score = max(0.0, line[i].start - line[i - 1].end)  # a pause in the speech
    if prev.endswith(_SENTENCE_END):
        score += 3.0
    elif prev.endswith(_PAUSE_MARKS):
        score += 2.0
    elif line[i].text[:1].isspace():  # between two Latin words
        score += 0.5
    return score


def split_lines(words: list[Word], max_width: int = MAX_WIDTH) -> list[SubtitleCue]:
    """Group timed words into subtitle lines: a line ends after a sentence, at
    a pause, or after a comma once it is 40 % full. A line that would grow too
    wide or too long is broken at the best place in its second part
    (punctuation, a space, the longest pause), never inside a word."""
    lines: list[list[Word]] = []
    cur: list[Word] = []
    for w in (w for w in words if w.text.strip()):
        if cur and _break_score([cur[-1], w], 1) >= 0:
            have = text_width(line_text(cur))
            prev = tidy_punctuation(cur[-1].text).rstrip()
            if (w.start - cur[-1].end > PAUSE_S
                    or (have >= 8 and prev.endswith(_SENTENCE_END))
                    or (have >= max_width * 0.4 and prev.endswith(_PAUSE_MARKS))):
                lines.append(cur)
                cur = []
            elif (have + text_width(w.text.strip()) + 1 > max_width
                    or w.end - cur[0].start > MAX_LINE_S):
                first = max(1, len(cur) // 2)
                cut = max(range(first, len(cur)), key=lambda i: (_break_score(cur, i), i),
                          default=len(cur))
                if _break_score(cur, cut) < 0:
                    cut = len(cur)
                lines.append(cur[:cut])
                cur = cur[cut:]
        cur.append(w)
    if cur:
        lines.append(cur)
    cues: list[SubtitleCue] = []
    for k, line in enumerate(lines):
        text = line_text(line)
        if not text:
            continue
        start = line[0].start
        nxt = lines[k + 1][0].start if k + 1 < len(lines) else None
        end = max(line[-1].end + 0.2, start + MIN_LINE_S)
        if nxt is not None:
            end = max(min(end, nxt), min(line[-1].end, nxt))
        cues.append(SubtitleCue(round(start, 2), round(max(end, start + 0.1), 2), text))
    return cues


# ── engines ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SpeechGpu:
    engine: str  # "cuda" | "openvino"
    device: str  # the OpenVINO device name ("GPU", "GPU.1"); "cuda" for CUDA
    name: str  # shown to the user


def _whisper_model_class():
    try:
        import av  # noqa: F401  (faster-whisper imports it; we decode with ffmpeg)
    except ImportError:
        sys.modules.setdefault("av", types.ModuleType("av"))
    from faster_whisper import WhisperModel

    return WhisperModel


def engine_ok() -> bool:
    """Whether the CPU engine can run here (a packaged build checks this in
    --selftest): faster-whisper and the tokenizer import, CTranslate2's native
    library runs and the voice filter's model loads in onnxruntime."""
    try:
        _whisper_model_class()
        import ctranslate2
        import tokenizers  # noqa: F401
        from faster_whisper.vad import get_vad_model

        get_vad_model()  # an onnxruntime session on the bundled voice-filter model
        return "int8" in ctranslate2.get_supported_compute_types("cpu")
    except Exception:  # noqa: BLE001
        return False


def openvino_error() -> str:
    """"" when the OpenVINO engine really runs here, else why not (a packaged build checks
    this in --selftest): its libraries load, and a tiny model survives the
    path the Whisper models take: written and read back as OpenVINO IR, then
    compiled and run on the CPU plugin. (The GPU plugin only exists on Intel
    hardware, so a build machine can't be asked for it.)"""
    try:
        import tempfile

        import numpy as np
        import openvino as ov
        import openvino_genai  # noqa: F401
        import openvino_tokenizers
        from openvino import opset13 as ops

        core = ov.Core()
        if "CPU" not in core.available_devices:
            return f"no CPU device (found {core.available_devices})"
        # the Whisper models' tokenizer is an extension library loaded by path
        extension = Path(openvino_tokenizers._ext_path)
        if not extension.is_file():
            return f"tokenizer extension missing: {extension}"
        core.add_extension(str(extension))
        x = ops.parameter([1, 3], ov.Type.f32, name="x")
        model = ov.Model([ops.add(x, ops.constant(np.ones((1, 3), np.float32)))], [x], "probe")
        with tempfile.TemporaryDirectory() as tmp:
            ov.save_model(model, str(Path(tmp) / "probe.xml"))
            compiled = core.compile_model(core.read_model(str(Path(tmp) / "probe.xml")), "CPU")
            total = float(compiled(np.zeros((1, 3), np.float32))[0].sum())
            return "" if total == 3.0 else f"wrong result {total}"
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"


def openvino_ok() -> bool:
    return not openvino_error()


def cuda_available() -> bool:
    """An NVIDIA GPU that CTranslate2 can use (needs the driver and the CUDA 12
    libraries; without them speech recognition runs on the CPU)."""
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False


def _nvidia_name() -> str:
    """The NVIDIA card's name from the driver's own tool, if it is around."""
    try:
        done = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                              capture_output=True, text=True, timeout=10, check=False,
                              **_no_window())
        name = done.stdout.strip().splitlines()[0].strip() if done.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        name = ""
    return name or "NVIDIA GPU"


# An integrated GPU needs this many execution units to beat the CPU it sits next
# to: the Arc 140T has 128 and Iris Xe 80-96, while the UHD 600-series of 6th-10th
# generation Core chips (24 EUs, no hardware int8) is likely slower than their CPU.
# A heuristic, not a measurement; discrete cards are always used.
MIN_IGPU_EUS = 64
_basic_gpus: list[str] = []  # names of integrated GPUs left out for being too basic


def _openvino_gpu() -> SpeechGpu | None:
    """The Intel GPU OpenVINO sees (a discrete Arc card before an integrated one)."""
    try:
        import openvino as ov

        core = ov.Core()
        gpus = [d for d in core.available_devices if d == "GPU" or d.startswith("GPU.")]
        if not gpus:
            return None

        def discrete(dev: str) -> bool:
            try:
                return "DISCRETE" in str(core.get_property(dev, "DEVICE_TYPE")).upper()
            except Exception:  # noqa: BLE001
                return False

        dev = min(gpus, key=lambda d: not discrete(d))
        name = re.sub(r"\((?:R|TM)\)", "", str(core.get_property(dev, "FULL_DEVICE_NAME"))).strip()
        if not discrete(dev):
            try:
                units = int(core.get_property(dev, "GPU_EXECUTION_UNITS_COUNT"))
            except Exception:  # noqa: BLE001 - unknown size: give it the benefit of the doubt
                units = MIN_IGPU_EUS
            if units < MIN_IGPU_EUS:
                _basic_gpus.append(name)
                return None
        return SpeechGpu("openvino", dev, name)
    except Exception:  # noqa: BLE001
        return None


_gpus: list[list[SpeechGpu]] = []  # one entry once detected (a list, to cache without a global)
_detect_lock = threading.Lock()
_detector: list[threading.Thread] = []
_gave_up: list[bool] = []  # detection took too long: counts as "no card" until it finishes


def _detect() -> None:
    try:
        found = [SpeechGpu("cuda", "cuda", _nvidia_name())] if cuda_available() else []
        gpu = _openvino_gpu()
        result = found + ([gpu] if gpu else [])
    except Exception:  # noqa: BLE001 - a broken driver is "no card", not a crash
        result = []
    if not _gpus:
        _gpus.append(result)


def detect_gpus(timeout: float = 20.0) -> list[SpeechGpu]:
    """The graphics cards speech recognition can use here, best first. Starting
    the drivers takes a second or two, and a broken one can hang for good, so
    the check runs in a helper thread and is given *timeout* seconds: after
    that the computer counts as having no usable card, and nothing waits on
    the driver (if it does answer later, later calls use the answer)."""
    if not _gpus:
        with _detect_lock:
            if not _gpus and not (_detector and _detector[0].is_alive()):
                _detector[:] = [threading.Thread(target=_detect, name="gpu-detect", daemon=True)]
                _detector[0].start()
            thread = _detector[0] if _detector else None
        if thread is not None:
            thread.join(timeout)
        if not _gpus:
            _gave_up[:] = [True]
            return []
    return _gpus[0]


def gpus_checked() -> bool:
    return bool(_gpus) or bool(_gave_up)


def speech_engines(gpu: bool = True, models_dir: str | Path | None = None,
                   timeout: float = 20.0) -> list[str]:
    """The engines to try, in order; the CPU is always the last. NVIDIA comes
    first, unless it still has to download its 1.3 GB of CUDA libraries and an
    Intel GPU, which needs nothing extra, is there to use meanwhile. *timeout*
    bounds the wait for the graphics-card check (see `detect_gpus`)."""
    engines = [g.engine for g in detect_gpus(timeout)] if gpu else []
    if (len(engines) > 1 and engines[0] == "cuda" and models_dir is not None
            and not cuda_runtime.runtime_ready(models_dir)):
        engines.reverse()
    return [*engines, "cpu"]


def speech_device(gpu: bool, models_dir: str | Path | None = None) -> tuple[str, dict]:
    """The Settings status line for auto captions, as (message key, values)."""
    threads = speech_threads()
    if gpu and not gpus_checked():
        return "Checking this computer…", {}
    found = detect_gpus() if gpu else []
    if found:
        first = speech_engines(gpu, models_dir)[0]
        found = sorted(found, key=lambda g: g.engine != first)
        if first == "cuda" and models_dir is not None and not cuda_runtime.runtime_ready(models_dir):
            fetch = ("{name} found. The first time, auto captions download the NVIDIA CUDA "
                     "libraries ({size}); if that fails, they run on the CPU instead.")
            return fetch, {"name": found[0].name, "size": cuda_runtime.download_size_label()}
        ready = ("Ready: {name}. Auto captions run on it; if it ever fails, they run on "
                 "the CPU instead.")
        return ready, {"name": found[0].name}
    if gpu and _basic_gpus:
        basic = ("{name} is too basic to speed up speech recognition (the CPU is faster), so "
                 "auto captions run on the CPU ({n} threads).")
        return basic, {"name": _basic_gpus[0], "n": threads}
    if gpu:
        none = ("No supported graphics card found for speech recognition (Intel graphics, or "
                "NVIDIA with CUDA 12), so auto captions run on the CPU ({n} threads).")
        return none, {"n": threads}
    return "Auto captions run on the CPU ({n} threads).", {"n": threads}


# ── recognition ────────────────────────────────────────────────────────

# lines Whisper is known to invent over music / silence (from the subtitle
# credits and outros in its training data), matched case-insensitively
_HALLUCINATIONS = ("subscribe", "thank you for watching", "thanks for watching", "amara.org",
                   "訂閱", "订阅", "點贊", "点赞", "字幕由", "字幕提供", "感謝觀看", "感谢观看",
                   "請不吝", "请不吝", "구독", "시청해 주셔서", "ご視聴", "チャンネル登録")
SILENCE_RMS = 0.002  # quieter than this is silence: Whisper would only invent text


def is_hallucination(text: str, no_speech_prob: float = 0.0, avg_logprob: float = 0.0) -> bool:
    """Whisper's own "probably not speech" rule, plus its well-known stock lines."""
    if no_speech_prob > 0.6 and avg_logprob < -1.0:
        return True
    low = text.lower()
    return any(h in low for h in _HALLUCINATIONS)


def _rms(audio) -> float:
    return float((audio ** 2).mean() ** 0.5) if audio.size else 0.0


def audio_slices(audio, target_s: float = 60.0, search_s: float = 5.0):
    """(offset in seconds, samples) pieces of about *target_s*, each cut at the
    quietest moment within *search_s* of where it would end, so a word isn't
    split. Gives the OpenVINO engine progress to report on long recordings."""
    import numpy as np

    n, step, reach = audio.size, int(target_s * SAMPLE_RATE), int(search_s * SAMPLE_RATE)
    frame = SAMPLE_RATE // 10
    start = 0
    while start < n:
        end = start + step
        if end + reach >= n:
            end = n
        else:
            lo, hi = end - reach, end + reach
            cut = audio[lo:hi][:(hi - lo) // frame * frame].reshape(-1, frame)
            end = lo + int(np.argmin((cut ** 2).mean(axis=1))) * frame + frame // 2
        yield start / SAMPLE_RATE, audio[start:end]
        start = end


_UNIT = re.compile(r"[⺀-鿿豈-﫿　-〿＀-￯]|\s*[^\s⺀-鿿豈-﫿　-〿＀-￯]+")


def chunk_words(text: str, start: float, end: float) -> list[Word]:
    """Word timings for a segment that only has start and end times: its text
    split into characters (Chinese / Japanese) and words (the rest), the time
    spread over them by width. Punctuation takes none."""
    units = _UNIT.findall(text.strip())
    if not units:
        return []
    weights = [0.0 if all(unicodedata.category(ch).startswith(("P", "S")) or ch.isspace()
                          for ch in u) else float(text_width(u.strip()) or 1) for u in units]
    total = sum(weights)
    if total <= 0:
        return [Word(start, end, text)]
    span, t, words = max(0.0, end - start), start, []
    for unit, w in zip(units, weights):
        nxt = t + span * w / total
        words.append(Word(round(t, 3), round(nxt, 3), unit))
        t = nxt
    return words


class _FasterWhisper:
    """CTranslate2: ``cuda`` (float16) or ``cpu`` (int8, on the fast cores)."""

    def __init__(self, path: Path, device: str, language: str, on_log: LogCallback | None):
        WhisperModel = _whisper_model_class()
        if device == "cuda":
            # "auto" = the fastest precision this card supports (older ones lack float16)
            self.model = WhisperModel(str(path), device="cuda", compute_type="auto")
            if on_log:
                on_log("Speech recognition on the NVIDIA GPU (CUDA)")
        else:
            threads = speech_threads()
            self.model = WhisperModel(str(path), device="cpu", compute_type="int8",
                                      cpu_threads=threads)
            if on_log:
                on_log(f"Speech recognition on the CPU ({threads} threads)")
        self.opts = _options(language)

    def _words(self, audio, opts: dict, on_segment) -> tuple[list[Word], str]:
        segments, info = self.model.transcribe(audio, **opts)
        words: list[Word] = []
        for seg in segments:
            on_segment(seg.end)
            if is_hallucination(seg.text, seg.no_speech_prob, seg.avg_logprob):
                continue
            if seg.words:
                words += [Word(w.start, w.end, w.word) for w in seg.words]
            else:
                words.append(Word(seg.start, seg.end, seg.text))
        return words, info.language

    def words(self, audio, on_segment) -> tuple[list[Word], str]:
        words, lang = self._words(audio, self.opts, on_segment)
        if not words and self.opts.get("vad_filter") and _rms(audio) > 0.01:
            # the voice filter hears singing over loud music as no speech at all:
            # for a song, listen to everything
            words, lang = self._words(audio, {**self.opts, "vad_filter": False}, on_segment)
        return words, lang


class _OpenVino:
    """OpenVINO GenAI on an Intel GPU (or ``CPU`` in tests). The compiled GPU
    kernels are cached next to the models, so only the first run waits for them."""

    def __init__(self, path: Path, device: str, cache: Path, language: str,
                 on_log: LogCallback | None):
        import openvino_genai as ovg

        cache.mkdir(parents=True, exist_ok=True)
        self.pipe = ovg.WhisperPipeline(str(path), device, CACHE_DIR=str(cache))
        self.language = None if language == "auto" else language.split("-")[0]
        self.prompt = _PROMPTS.get(language)
        if on_log:
            on_log(f"Speech recognition on OpenVINO ({device})")

    def words(self, audio, on_segment) -> tuple[list[Word], str]:
        words: list[Word] = []
        for offset, piece in audio_slices(audio):
            on_segment(offset)
            if _rms(piece) < SILENCE_RMS:
                continue
            cfg = self.pipe.get_generation_config()
            cfg.task = "transcribe"
            cfg.return_timestamps = True
            if self.language:
                cfg.language = f"<|{self.language}|>"
            if self.prompt:
                cfg.initial_prompt = self.prompt
            result = self.pipe.generate(piece.tolist(), cfg)
            for chunk in result.chunks or []:
                if not is_hallucination(chunk.text):
                    words += chunk_words(chunk.text, offset + chunk.start_ts,
                                         offset + chunk.end_ts)
            detected = str(getattr(result, "language", "") or "").strip("<|>")
            if not self.language and detected and words:
                self.language = detected  # keep one language for the rest of the clip
            on_segment(offset + piece.size / SAMPLE_RATE)
        return words, self.language or ""


def _options(language: str) -> dict:
    opts: dict = {
        "language": None if language == "auto" else language.split("-")[0],
        "word_timestamps": True,
        "vad_filter": True,
        "condition_on_previous_text": False,  # stops repeated-line loops
        "hallucination_silence_threshold": 2.0,
        "beam_size": 5,
        "temperature": (0.0, 0.2, 0.4),  # fewer retries: music made it crawl
    }
    if language in _PROMPTS:
        opts["hotwords"] = _PROMPTS[language]  # unlike initial_prompt, every window sees it
    try:
        import onnxruntime  # noqa: F401  (the voice-activity filter needs it)
    except ImportError:
        opts["vad_filter"] = False
    return opts


def _recogniser(engine: str, models_dir: Path, size: str, language: str,
                on_progress, on_log, translate):
    """Download the model for *engine* if needed and load it."""
    tr = translate or _noop_tr
    if engine == "cuda":  # cuBLAS / cuDNN, fetched once if the computer doesn't have them
        cuda_runtime.ensure_runtime(models_dir, on_progress=on_progress, translate=translate)
    path = ensure_model(models_dir, size, engine=engine, on_progress=on_progress,
                        translate=translate)
    if on_progress:
        on_progress(tr("Loading the speech model…"), None)
    if engine == "openvino":
        gpu = next(g for g in detect_gpus() if g.engine == "openvino")
        return _OpenVino(path, gpu.device, models_dir / "openvino-cache", language, on_log)
    return _FasterWhisper(path, engine, language, on_log)


def _transcribe(engine: str, sources: list[CaptionSource], models_dir: Path, language: str,
                size: str, ffmpeg: str, on_progress, on_log, translate) -> list[SubtitleCue]:
    tr = translate or _noop_tr
    recogniser = _recogniser(engine, models_dir, size, language, on_progress, on_log, translate)
    spans = [(s.end - s.start) if s.end is not None else None for s in sources]
    total = sum(x for x in spans if x) or 1.0
    done = 0.0
    cues: list[SubtitleCue] = []
    for src, span in zip(sources, spans):
        audio = load_audio(src, ffmpeg)
        if audio.size < SAMPLE_RATE // 4:  # no sound (or a still) - nothing to hear
            done += span or 0.0
            continue
        length = audio.size / SAMPLE_RATE

        def on_segment(t: float, base=done, length=length) -> None:
            if on_progress:
                pct = (base + min(t, length)) * 100 / max(total, base + length)
                on_progress(tr("Listening for speech…"), min(99, int(pct)))

        on_segment(0.0)
        words, lang = recogniser.words(audio, on_segment)
        if on_log:
            on_log(f"Captions: {Path(src.path).name}: language {lang}, {len(words)} words")
        speed = src.speed if src.speed > 0 else 1.0
        end = src.offset + length / speed
        for cue in split_lines(words):
            start = src.offset + cue.start / speed
            if start >= end - 0.05:
                continue
            cues.append(SubtitleCue(round(start, 2),
                                    round(min(src.offset + cue.end / speed, end), 2), cue.text))
        done += span if span is not None else length
    cues.sort(key=lambda c: c.start)
    return cues


def transcribe(
    sources: list[CaptionSource],
    models_dir: str | Path,
    *,
    language: str = "auto",
    size: str = DEFAULT_MODEL,
    gpu: bool = True,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
) -> list[SubtitleCue]:
    """Subtitle lines (in montage time) for the speech in *sources*. With *gpu*
    the graphics-card engines are tried first (see the module docstring); an
    engine that can't load or fails while decoding hands over to the next."""
    ffmpeg = _require_ffmpeg(translate)
    models_dir = Path(models_dir)
    engines = speech_engines(gpu, models_dir)
    for n, engine in enumerate(engines):
        try:
            return _transcribe(engine, sources, models_dir, language, size, ffmpeg,
                               on_progress, on_log, translate)
        except DownloadCancelled:
            raise
        except Exception as exc:
            if n == len(engines) - 1:
                raise
            if on_log:
                why = next((ln.strip() for ln in str(exc).splitlines() if ln.strip()), type(exc).__name__)
                on_log(f"Speech recognition on {engine} failed ({why}); trying {engines[n + 1]}")
    raise AssertionError("unreachable")  # the CPU engine is always last
