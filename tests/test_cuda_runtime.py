"""NVIDIA CUDA libraries on demand: download, checksum, unpack, register
(fake wheels served from disk; no GPU and no 1.3 GB download needed)."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from vidgrab import cuda_runtime as cr


def _wheel(path: Path, members: dict[str, bytes]) -> tuple[str, str, int]:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    raw = path.read_bytes()
    return path.as_uri(), hashlib.sha256(raw).hexdigest(), len(raw)


@pytest.fixture
def fake_wheels(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    blas = _wheel(src / "blas.whl", {
        "nvidia/cublas/lib/libcublas.so.12": b"blas", "nvidia/cublas/lib/libcublasLt.so.12": b"lt",
        "nvidia/cublas/include/cublas.h": b"header", "nvidia_cublas.dist-info/METADATA": b"m"})
    dnn = _wheel(src / "dnn.whl", {
        "nvidia/cudnn/lib/libcudnn.so.9": b"dnn", "nvidia/cudnn/lib/libcudnn_ops.so.9": b"ops",
        "nvidia/cudnn/include/cudnn.h": b"header"})
    pins = (("blas.whl", *blas[:2], blas[2]), ("dnn.whl", *dnn[:2], dnn[2]))
    monkeypatch.setattr(cr, "PINS", {"linux": pins})
    monkeypatch.setattr(cr, "platform_key", lambda: "linux")
    state = {"registered": False}
    monkeypatch.setattr(cr, "libs_loadable", lambda: state["registered"])
    monkeypatch.setattr(cr, "register", lambda folder: state.update(registered=True, folder=folder))
    return state, pins


def test_ensure_runtime_downloads_unpacks_and_registers(tmp_path, fake_wheels) -> None:
    state, _ = fake_wheels
    models = tmp_path / "models"
    assert not cr.runtime_ready(models)
    seen: list[float] = []
    cr.ensure_runtime(models, on_progress=lambda msg, pct: seen.append(pct))
    folder = cr.runtime_dir(models)
    # the libraries sit side by side (cuDNN finds its parts next to itself); no headers, no wheels left
    assert sorted(p.name for p in folder.iterdir()) == [
        "COMPLETE", "libcublas.so.12", "libcublasLt.so.12", "libcudnn.so.9", "libcudnn_ops.so.9"]
    assert state["registered"] and state["folder"] == folder
    assert seen == sorted(seen) and seen[-1] == 100
    assert cr.runtime_ready(models)
    # a later run needs no download at all
    state["registered"] = False
    (folder / "libcublas.so.12").unlink()
    cr.ensure_runtime(models, on_progress=lambda *_: pytest.fail("downloaded again"))
    assert state["registered"]


def test_ensure_runtime_rejects_a_corrupt_download(tmp_path, fake_wheels, monkeypatch) -> None:
    _, pins = fake_wheels
    bad = (pins[0][0], pins[0][1], "0" * 64, pins[0][3])
    monkeypatch.setattr(cr, "PINS", {"linux": (bad, pins[1])})
    models = tmp_path / "models"
    with pytest.raises(RuntimeError, match="SHA-256"):
        cr.ensure_runtime(models)
    assert not (cr.runtime_dir(models) / "COMPLETE").exists()  # retried next time
    assert not list(cr.runtime_dir(models).glob("*.part"))


def test_ensure_runtime_skips_when_installed_and_fails_cleanly(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cr, "platform_key", lambda: "linux")
    monkeypatch.setattr(cr, "libs_loadable", lambda: True)  # already on the system
    cr.ensure_runtime(tmp_path, on_progress=lambda *_: pytest.fail("no download expected"))
    assert not cr.runtime_dir(tmp_path).exists() and cr.runtime_ready(tmp_path)
    monkeypatch.setattr(cr, "platform_key", lambda: None)  # e.g. ARM
    monkeypatch.setattr(cr, "libs_loadable", lambda: False)
    with pytest.raises(RuntimeError, match="64-bit"):
        cr.ensure_runtime(tmp_path)


def test_unpacks_the_windows_layout_and_pins_cover_both_platforms() -> None:
    assert set(cr.PINS) == {"linux", "win"}
    for plat, pins in cr.PINS.items():
        assert len(pins) == 2 and all(len(p[2]) == 64 and p[1].startswith("https://") for p in pins)
        assert pins[0][0].startswith("nvidia_cublas_cu12") and pins[1][0].startswith("nvidia_cudnn_cu12")
        assert ("win_amd64" in pins[0][0]) == (plat == "win")
    assert cr._MEMBER_DIRS["win"] == ("nvidia/cublas/bin/", "nvidia/cudnn/bin/")
    assert cr.download_size_label() in ("1.3 GB", "1.2 GB")
