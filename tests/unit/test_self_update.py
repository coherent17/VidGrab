from __future__ import annotations

import hashlib

import pytest
from conftest import patch_ui

from vidgrab.core import self_update as su

BODY = b"x" * (su.MIN_BYTES + 5)


def _news(**assets):
    return {"assets": {"VidGrab-linux-x64": "u/bin", "SHA256SUMS.txt": "u/sums", **assets}}


def test_plan_only_for_a_writable_frozen_single_file(tmp_path):
    exe = tmp_path / "VidGrab"
    exe.write_bytes(b"old")
    assert su.plan(_news(), frozen=True, exe=str(exe), platform="linux").asset == "VidGrab-linux-x64"
    assert su.plan(_news(), frozen=False, exe=str(exe), platform="linux") is None  # a checkout / pip install
    assert su.plan(_news(), frozen=True, exe=str(exe), platform="darwin") is None  # the macOS app
    assert su.plan({"assets": {}}, frozen=True, exe=str(exe), platform="linux") is None


def test_expected_hash_reads_sha256sum_lines():
    text = "aa11  other\nBB22 *VidGrab-linux-x64\n"
    assert su.expected_hash(text, "VidGrab-linux-x64") == "bb22"
    assert su.expected_hash(text, "missing") is None


def _fetcher(body, sums_for=None):
    good = hashlib.sha256(BODY).hexdigest()

    def fetch(url, dest, on_progress, cancelled, proxy=""):
        if url == "u/sums":
            dest.write_text(f"{sums_for or good}  VidGrab-linux-x64\n")
        else:
            dest.write_bytes(body)
            if on_progress:
                on_progress(100)
    return fetch


def test_download_install_and_cleanup(tmp_path):
    exe = tmp_path / "VidGrab"
    exe.write_bytes(b"old")
    how = su.Plan("VidGrab-linux-x64", exe)
    new = su.download(_news(), how, fetch=_fetcher(BODY))
    assert new.read_bytes() == BODY
    su.install(new, exe)
    assert exe.read_bytes() == BODY and (tmp_path / "VidGrab.old").read_bytes() == b"old"
    assert not new.exists()
    su.cleanup(str(exe))
    assert not (tmp_path / "VidGrab.old").exists()


def test_a_wrong_checksum_or_tiny_file_installs_nothing(tmp_path):
    exe = tmp_path / "VidGrab"
    exe.write_bytes(b"old")
    how = su.Plan("VidGrab-linux-x64", exe)
    with pytest.raises(su.UpdateError, match="checksum"):
        su.download(_news(), how, fetch=_fetcher(BODY, sums_for="0" * 64))
    with pytest.raises(su.UpdateError, match="too small"):
        su.download(_news(), how, fetch=_fetcher(b"<html>"))
    assert exe.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["VidGrab"]  # no leftovers


def test_no_checksum_list_means_no_install(tmp_path):
    how = su.Plan("VidGrab-linux-x64", tmp_path / "VidGrab")
    with pytest.raises(su.UpdateError):
        su.download({"assets": {"VidGrab-linux-x64": "u"}}, how, fetch=_fetcher(BODY))


def test_a_failed_swap_restores_the_old_file(tmp_path, monkeypatch):
    exe = tmp_path / "VidGrab"
    exe.write_bytes(b"old")
    new = tmp_path / "VidGrab.new"
    new.write_bytes(BODY)
    real = su.os.replace
    calls = []

    def flaky(a, b):
        calls.append((a, b))
        if len(calls) == 2:
            raise PermissionError("locked")
        return real(a, b)

    monkeypatch.setattr(su.os, "replace", flaky)
    with pytest.raises(su.UpdateError):
        su.install(new, exe)
    assert exe.read_bytes() == b"old"


def test_the_window_offers_update_now_only_when_it_can_install(tmp_path, monkeypatch):
    import os
    if os.environ.get("SMOKE_GUI") != "1":
        pytest.skip("set SMOKE_GUI=1 to enable")
    from PySide6.QtWidgets import QApplication

    from vidgrab.ui import app as m

    QApplication.instance() or QApplication([])
    patch_ui(monkeypatch, "_config_dir", lambda: tmp_path / "cfg")
    w = m.VidGrabWindow()
    try:
        news = {"version": "9.0.0", "url": "u", "notes": "", "assets": {}}
        monkeypatch.setattr(m.self_update, "plan", lambda n: None)
        w._on_release(news)
        assert "see what is new" in w._release_note.text()
        monkeypatch.setattr(m.self_update, "plan", lambda n: su.Plan("x", tmp_path / "VidGrab"))
        w._on_release(news)
        assert "update now" in w._release_note.text()
    finally:
        w._studio.clear_autosave()
        w._studio.shutdown()
        for page in (w._library, w._tools, w._subs):
            page.shutdown()
        w.close()
