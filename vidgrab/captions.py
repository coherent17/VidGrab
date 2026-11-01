"""Auto captions: speech in the Studio's clips -> timed subtitle lines.

Qt-free, like studio.py. Speech recognition is faster-whisper (Whisper on
CTranslate2), run locally; only the model is downloaded, once, on first use
(``<config>/models/<size>``). Audio is decoded by our own ffmpeg straight to
16 kHz mono samples, so PyAV (which faster-whisper would otherwise use) isn't
needed and isn't bundled.

``transcribe()`` takes each clip's kept part of its source (start / end /
speed / where it sits in the montage) and returns ``SubtitleCue``s in
montage time, split into readable lines by the word timings.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from vidgrab.downloader import LogCallback, ProgressCallback, TranslateFn, _noop_tr
from vidgrab.studio import SubtitleCue, _no_window, _require_ffmpeg

SAMPLE_RATE = 16000  # what Whisper expects

# accuracy key -> (Hugging Face repo with the CTranslate2 model, download size label)
MODELS: dict[str, tuple[str, str]] = {
    "fast": ("Systran/faster-whisper-base", "150 MB"),
    "balanced": ("Systran/faster-whisper-small", "490 MB"),
    "best": ("deepdml/faster-whisper-large-v3-turbo-ct2", "1.6 GB"),
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


def model_dir(models_dir: str | Path, size: str) -> Path:
    return Path(models_dir) / size


def model_ready(models_dir: str | Path, size: str) -> bool:
    return (model_dir(models_dir, size) / "COMPLETE").is_file()


def ensure_model(
    models_dir: str | Path,
    size: str = DEFAULT_MODEL,
    *,
    on_progress: ProgressCallback | None = None,
    translate: TranslateFn | None = None,
) -> Path:
    """The model folder for *size*, downloading it first if needed."""
    tr = translate or _noop_tr
    dest = model_dir(models_dir, size)
    if model_ready(models_dir, size):
        return dest
    repo = MODELS[size][0]
    with urllib.request.urlopen(f"{_HF}/api/models/{repo}/tree/main", timeout=30) as resp:
        tree = json.load(resp)
    files = [(f["path"], int(f.get("size") or 0)) for f in tree if f.get("path") in _MODEL_FILES]
    if not any(name == "model.bin" for name, _ in files):
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
        with urllib.request.urlopen(f"{_HF}/{repo}/resolve/main/{name}", timeout=60) as resp, \
                open(part, "wb") as fh:
            while chunk := resp.read(1 << 20):
                fh.write(chunk)
                done += len(chunk)
                pct = int(done * 100 / total)
                if on_progress and pct != last:
                    last = pct
                    on_progress(tr("Downloading the speech model…"), min(pct, 100))
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


# ── recognition ────────────────────────────────────────────────────────


def _whisper_model_class():
    try:
        import av  # noqa: F401  (faster-whisper imports it; we decode with ffmpeg)
    except ImportError:
        sys.modules.setdefault("av", types.ModuleType("av"))
    from faster_whisper import WhisperModel

    return WhisperModel


def engine_ok() -> bool:
    """Whether speech recognition can run here (a packaged build checks this
    in --selftest): faster-whisper and the tokenizer import, CTranslate2's
    native library runs and the voice filter's model loads in onnxruntime."""
    try:
        _whisper_model_class()
        import ctranslate2
        import tokenizers  # noqa: F401
        from faster_whisper.vad import get_vad_model

        get_vad_model()  # an onnxruntime session on the bundled voice-filter model
        return "int8" in ctranslate2.get_supported_compute_types("cpu")
    except Exception:  # noqa: BLE001
        return False


def _load_model(path: Path, on_log: LogCallback | None, *, gpu: bool = True):
    """The model on an NVIDIA GPU when CUDA works, else on the CPU."""
    WhisperModel = _whisper_model_class()
    if gpu:
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                model = WhisperModel(str(path), device="cuda", compute_type="float16")
                if on_log:
                    on_log("Speech recognition on the GPU (CUDA)")
                return model, "cuda"
        except Exception as exc:  # noqa: BLE001 - no CUDA runtime / cuDNN: use the CPU
            if on_log:
                on_log(f"GPU not usable for speech recognition ({exc}); using the CPU")
    model = WhisperModel(str(path), device="cpu", compute_type="int8",
                         cpu_threads=max(1, (os.cpu_count() or 2) - 1))
    return model, "cpu"


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


# lines Whisper is known to invent over music / silence (from the subtitle
# credits and outros in its training data), matched case-insensitively
_HALLUCINATIONS = ("subscribe", "thank you for watching", "thanks for watching", "amara.org",
                   "訂閱", "订阅", "點贊", "点赞", "字幕由", "字幕提供", "感謝觀看", "感谢观看",
                   "請不吝", "请不吝", "구독", "시청해 주셔서", "ご視聴", "チャンネル登録")


def is_hallucination(text: str, no_speech_prob: float = 0.0, avg_logprob: float = 0.0) -> bool:
    """Whisper's own "probably not speech" rule, plus its well-known stock lines."""
    if no_speech_prob > 0.6 and avg_logprob < -1.0:
        return True
    low = text.lower()
    return any(h in low for h in _HALLUCINATIONS)


def _words(model, audio, opts: dict, on_segment) -> tuple[list[Word], str]:
    segments, info = model.transcribe(audio, **opts)
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


def _recognise(model, audio, opts: dict, on_segment) -> tuple[list[Word], str]:
    words, lang = _words(model, audio, opts, on_segment)
    if not words and opts.get("vad_filter") and float((audio ** 2).mean()) > 1e-4:
        # the voice filter hears singing over loud music as no speech at all:
        # for a song, listen to everything
        words, lang = _words(model, audio, {**opts, "vad_filter": False}, on_segment)
    return words, lang


def transcribe(
    sources: list[CaptionSource],
    models_dir: str | Path,
    *,
    language: str = "auto",
    size: str = DEFAULT_MODEL,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
) -> list[SubtitleCue]:
    """Subtitle lines (in montage time) for the speech in *sources*."""
    tr = translate or _noop_tr
    ffmpeg = _require_ffmpeg(translate)
    path = ensure_model(models_dir, size, on_progress=on_progress, translate=translate)
    if on_progress:
        on_progress(tr("Loading the speech model…"), None)
    model, device = _load_model(path, on_log)
    opts = _options(language)

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

        if on_progress:
            on_segment(0.0)
        try:
            words, lang = _recognise(model, audio, opts, on_segment)
        except RuntimeError as exc:
            if device != "cuda":
                raise
            if on_log:  # e.g. cuBLAS / cuDNN missing: they only fail once decoding starts
                on_log(f"GPU speech recognition failed ({exc}); using the CPU")
            model, device = _load_model(path, on_log, gpu=False)
            words, lang = _recognise(model, audio, opts, on_segment)
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
