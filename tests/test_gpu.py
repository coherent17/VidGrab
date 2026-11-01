"""Hardware acceleration: encoder choice and arguments, detection with
fallbacks, and the CPU thread count (no GPU needed: ffmpeg is faked)."""

from __future__ import annotations

import struct
import subprocess
from types import SimpleNamespace

from vidgrab import gpu
from vidgrab.gpu import HwEncoder

NVENC, QSV, AMF = gpu.CANDIDATES


def test_video_args_per_encoder_and_tier() -> None:
    assert gpu.video_args(None, "medium", 20) == ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
    assert gpu.video_args(QSV, "veryfast", 23) == [
        "-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "23"]
    assert gpu.video_args(QSV, "slow", 17)[3] == "veryslow"
    nv = gpu.video_args(NVENC, "medium", 20)
    assert nv[:4] == ["-c:v", "h264_nvenc", "-preset", "p5"] and "-cq" in nv and "20" in nv
    amf = gpu.video_args(AMF, "slow", 17)
    assert amf[:4] == ["-c:v", "h264_amf", "-quality", "quality"] and amf[-1] == "17"


def _fake_ffmpeg(monkeypatch, listed: str, working: set[str]) -> list[str]:
    tried: list[str] = []

    def run(cmd, **_kw):
        if "-encoders" in cmd:
            return SimpleNamespace(stdout=listed, returncode=0)
        codec = cmd[cmd.index("-c:v") + 1]
        tried.append(codec)
        return SimpleNamespace(returncode=0 if codec in working else 1)

    monkeypatch.setattr(subprocess, "run", run)
    gpu.detect_encoder.cache_clear()
    return tried


def test_detect_encoder_prefers_order_and_skips_broken_ones(monkeypatch) -> None:
    tried = _fake_ffmpeg(monkeypatch, "h264_nvenc h264_qsv h264_amf", {"h264_qsv", "h264_amf"})
    assert gpu.detect_encoder("ffmpeg") == QSV  # NVENC is listed but its driver is missing
    assert tried == ["h264_nvenc", "h264_qsv"]
    assert gpu.detect_encoder("ffmpeg") == QSV and len(tried) == 2  # cached


def test_detect_encoder_none_when_unlisted_or_nothing_works(monkeypatch) -> None:
    tried = _fake_ffmpeg(monkeypatch, "libx264 aac", {"h264_qsv"})
    assert gpu.detect_encoder("ffmpeg") is None and tried == []  # not even tried
    _fake_ffmpeg(monkeypatch, "h264_nvenc h264_qsv", set())
    assert gpu.detect_encoder("ffmpeg") is None

    def boom(*_a, **_k):
        raise OSError("no ffmpeg")

    monkeypatch.setattr(subprocess, "run", boom)
    gpu.detect_encoder.cache_clear()
    assert gpu.detect_encoder("ffmpeg") is None


def _core_record(eff: int) -> bytes:
    body = bytes([1, eff]) + bytes(20) + struct.pack("<HH", 1, 0) + bytes(8)  # flags, class, …
    return struct.pack("<II", 0, 8 + len(body)) + body


def test_parse_core_classes_and_fast_cores(monkeypatch) -> None:
    # Core Ultra 9 285H as Windows reports it: 6 performance (class 1), 10 slower (class 0)
    raw = b"".join(_core_record(1) for _ in range(6)) + b"".join(_core_record(0) for _ in range(10))
    classes = gpu.parse_core_classes(raw)
    assert classes.count(1) == 6 and classes.count(0) == 10
    monkeypatch.setattr(gpu.sys, "platform", "win32")
    monkeypatch.setattr(gpu, "_windows_core_classes", lambda: classes)
    assert gpu.fast_cores() == 6 and gpu.speech_threads() == 6
    monkeypatch.setattr(gpu, "_windows_core_classes", lambda: [0] * 4)  # all alike: all are fast
    assert gpu.fast_cores() == 4


def test_speech_threads_is_capped_and_has_a_fallback(monkeypatch) -> None:
    monkeypatch.setattr(gpu, "fast_cores", lambda: 24)
    assert gpu.speech_threads() == gpu.MAX_SPEECH_THREADS
    monkeypatch.setattr(gpu, "fast_cores", lambda: 0)
    assert gpu.speech_threads() == 1
    monkeypatch.undo()
    monkeypatch.setattr(gpu.sys, "platform", "darwin")  # no topology source: half the CPUs
    monkeypatch.setattr(gpu.os, "cpu_count", lambda: 12)
    assert gpu.fast_cores() == 6


def test_cpu_list() -> None:
    assert gpu._cpu_list("0-3,8,10-11\n") == {0, 1, 2, 3, 8, 10, 11}
    assert HwEncoder("x", "h264_x", "X").key == "x"
