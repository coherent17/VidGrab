"""Hardware acceleration (Qt-free): the GPU video encoder ffmpeg can use on
this computer, and how many CPU threads speech recognition should use.

The GPU only *encodes*: scaling, subtitles, overlays and transitions stay on
the CPU in the same ffmpeg graph, so the gain depends on the quality preset
(none at Fast, about 1.5x at Balanced, 1.8x at High on a fast CPU; 3x and
more on a laptop CPU with few cores). ``detect_encoder()`` really encodes a
test clip with each candidate, so a card without a working driver is skipped
instead of failing in the middle of a render.
"""

from __future__ import annotations

import functools
import os
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HwEncoder:
    key: str  # "nvenc" | "qsv" | "amf"
    codec: str  # ffmpeg's encoder name
    label: str  # shown to the user


# in order of preference when a computer has more than one
CANDIDATES = (
    HwEncoder("nvenc", "h264_nvenc", "NVIDIA NVENC"),
    HwEncoder("qsv", "h264_qsv", "Intel Quick Sync"),
    HwEncoder("amf", "h264_amf", "AMD AMF"),
)

# libx264 preset -> speed tier of the hardware encoders
_TIER = {"veryfast": 0, "medium": 1, "slow": 2}


def video_args(encoder: HwEncoder | None, preset: str, crf: int) -> list[str]:
    """ffmpeg arguments for the video codec: libx264 (*preset*, *crf*), or the
    hardware encoder with the matching speed tier and quality."""
    if encoder is None:
        return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]
    tier = _TIER.get(preset, 1)
    if encoder.key == "nvenc":
        return ["-c:v", encoder.codec, "-preset", ("p3", "p5", "p7")[tier],
                "-rc", "vbr", "-cq", str(crf), "-b:v", "0"]
    if encoder.key == "qsv":
        return ["-c:v", encoder.codec, "-preset", ("veryfast", "medium", "veryslow")[tier],
                "-global_quality", str(crf)]
    return ["-c:v", encoder.codec, "-quality", ("speed", "balanced", "quality")[tier],
            "-rc", "cqp", "-qp_i", str(crf), "-qp_p", str(crf)]  # amf


def _no_window() -> dict:
    from vidgrab.studio import _no_window as no_window  # studio imports this module

    return no_window()


def _works(ffmpeg: str, encoder: HwEncoder) -> bool:
    """Encode a short test clip: true only if the driver and the card respond."""
    cmd = [ffmpeg, "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
           "color=c=black:s=320x180:r=30:d=0.5", "-vf", "format=yuv420p",
           *video_args(encoder, "veryfast", 23), "-f", "null", "-"]
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=30, check=False, **_no_window())
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


@functools.lru_cache(maxsize=4)
def detect_encoder(ffmpeg: str) -> HwEncoder | None:
    """The first hardware H.264 encoder of *ffmpeg* that works here, or None."""
    try:
        listing = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                                 text=True, timeout=20, check=False, **_no_window()).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for encoder in CANDIDATES:
        if encoder.codec in listing and _works(ffmpeg, encoder):
            return encoder
    return None


# ── CPU threads for speech recognition ─────────────────────────────────

MAX_SPEECH_THREADS = 8


def parse_core_classes(raw: bytes) -> list[int]:
    """Efficiency class of each core in a GetLogicalProcessorInformationEx
    (RelationProcessorCore) buffer: records of ``Relationship, Size`` followed
    by ``Flags, EfficiencyClass, …``."""
    classes, pos = [], 0
    while pos + 10 <= len(raw):
        relation, length = struct.unpack_from("<II", raw, pos)
        if not length:
            break
        if relation == 0:
            classes.append(raw[pos + 9])
        pos += length
    return classes


def _windows_core_classes() -> list[int]:
    """The efficiency class of every physical core (higher = faster core)."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    size = wintypes.DWORD(0)
    kernel.GetLogicalProcessorInformationEx(0, None, ctypes.byref(size))  # 0 = per core
    if not size.value:
        return []
    buf = ctypes.create_string_buffer(size.value)
    if not kernel.GetLogicalProcessorInformationEx(0, buf, ctypes.byref(size)):
        return []
    return parse_core_classes(buf.raw[:size.value])


def _cpu_list(text: str) -> set[int]:
    out: set[int] = set()
    for part in text.strip().split(","):
        if "-" in part:
            lo, hi = part.split("-", 1)
            out |= set(range(int(lo), int(hi) + 1))
        elif part.strip():
            out.add(int(part))
    return out


def _linux_cores() -> tuple[int, int]:
    """(physical cores, fast physical cores) from sysfs; (0, 0) when unreadable."""
    base = Path("/sys/devices/system/cpu")
    cores: dict[tuple[str, str], int] = {}
    try:
        for cpu in base.glob("cpu[0-9]*"):
            topo = cpu / "topology"
            key = ((topo / "physical_package_id").read_text().strip(),
                   (topo / "core_id").read_text().strip())
            cores[key] = int(cpu.name[3:])
        if not cores:
            return 0, 0
        try:  # Intel hybrid: the performance cores' logical CPUs
            fast_cpus = _cpu_list(Path("/sys/devices/cpu_core/cpus").read_text())
            fast = len({k for k, cpu in cores.items() if cpu in fast_cpus})
        except (OSError, ValueError):
            fast = len(cores)
        return len(cores), fast or len(cores)
    except (OSError, ValueError):
        return 0, 0


def fast_cores() -> int:
    """Physical performance cores (all cores on a CPU without slow ones)."""
    count = 0
    try:
        if sys.platform == "win32":
            classes = _windows_core_classes()
            count = classes.count(max(classes)) if classes else 0
        elif sys.platform.startswith("linux"):
            count = _linux_cores()[1]
    except Exception:  # noqa: BLE001 - topology is a hint, never a reason to fail
        count = 0
    return count or max(1, (os.cpu_count() or 2) // 2)


def speech_threads() -> int:
    """CPU threads for speech recognition. Spreading it over efficiency cores
    is several times *slower* (the fast cores wait for the slow ones at every
    step: 30 s against 6 s for a minute of speech on a 16-core Core Ultra 9),
    and it stops scaling past about 8 threads anyway."""
    return max(1, min(MAX_SPEECH_THREADS, fast_cores()))
