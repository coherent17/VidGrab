"""Real-network integration tests for the download and processing pipeline.

These tests actually hit YouTube and invoke ffmpeg on a real video, so they
are only run when ``VIDGRAB_INTEGRATION=1`` is in the environment (enabled
on main pushes in CI but skipped for PRs and normal local development).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from vidgrab import downloader

# Short, long-lived videos; try in order so the suite survives a single
# video becoming unavailable.
YT_CANDIDATES = [
    "https://www.youtube.com/watch?v=jNQXAC9IVRw",  # Me at the zoo (19s, 2005)
    "https://www.youtube.com/watch?v=aqz-KE-bpKQ",  # Big Buck Bunny
    "https://www.youtube.com/watch?v=BaW_jenozKc",  # youtube-dl test clip
]


def _integration_enabled() -> bool:
    import os
    return os.environ.get("VIDGRAB_INTEGRATION") == "1"


pytestmark = pytest.mark.skipif(
    not _integration_enabled(),
    reason="Set VIDGRAB_INTEGRATION=1 to run real download/processing tests",
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _duration(path: Path) -> float:
    """Return media duration in seconds via ffprobe."""
    ff = shutil.which("ffprobe")
    if ff is None:
        pytest.skip("ffprobe not found")
    out = subprocess.check_output(
        [
            ff,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(path),
        ],
        text=True,
        timeout=30,
    )
    return float(out.strip())


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def src_mp4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Download a small YouTube clip once per test session as MP4."""
    d = tmp_path_factory.mktemp("yt-integration")
    errors: list[str] = []
    for url in YT_CANDIDATES:
        try:
            mp4 = downloader.download(url, d, "mp4")
            if mp4.exists() and mp4.stat().st_size > 10_000:
                return mp4
        except Exception as exc:  # noqa: BLE001 - try the next candidate
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    raise AssertionError(f"All YT candidates failed: {'; '.join(errors)}")


# ── tests ────────────────────────────────────────────────────────────────────


def test_flip_and_speed_up(src_mp4: Path, tmp_path: Path) -> None:
    out = downloader.process_local_file(
        src_mp4,
        tmp_path,
        video_filter="hflip",
        speed=2.0,
    )
    assert out.exists() and out.stat().st_size > 0
    dur = _duration(out)
    src_dur = _duration(src_mp4)
    # 2× speed should cut duration to ~half (±30% tolerance)
    assert dur < src_dur * 0.7, f"Expected speed-up: {dur:.2f}s vs source {src_dur:.2f}s"


def test_trim_section(src_mp4: Path, tmp_path: Path) -> None:
    out = downloader.process_local_file(
        src_mp4,
        tmp_path,
        section_start="00:00:00:50",
        section_end="00:00:01:50",
    )
    dur = _duration(out)
    # trimmed to ~1 second (±400 ms tolerance)
    assert 0.5 <= dur <= 1.5, f"Unexpected trim duration: {dur:.2f}s"


def test_download_mp3(tmp_path: Path) -> None:
    mp3 = downloader.download(YT_CANDIDATES[0], tmp_path, "mp3")
    assert mp3.exists() and mp3.suffix == ".mp3" and mp3.stat().st_size > 5_000
