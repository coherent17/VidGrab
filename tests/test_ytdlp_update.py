"""The in-app yt-dlp update: unpacking, choosing, falling back."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yt_dlp

from vidgrab import ytdlp_update as up
from vidgrab._version import __version__


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDGRAB_YTDLP_DIR", str(tmp_path / "upd"))
    return tmp_path / "upd"


def make_wheel(version: str, extra: dict[str, str] | None = None, *, bad_init: bool = False) -> bytes:
    """A wheel made from the installed yt-dlp with its version changed."""
    pkg = Path(yt_dlp.__file__).parent
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in pkg.rglob("*.py"):
            rel = "yt_dlp/" + f.relative_to(pkg).as_posix()
            text = f.read_text(encoding="utf-8")
            if rel == "yt_dlp/version.py":
                text = f'__version__ = "{version}"\nRELEASE_GIT_HEAD = ""\nVARIANT = None\n' \
                       'UPDATE_HINT = None\nCHANNEL = "stable"\nORIGIN = "x"\n_pkg_version = __version__\n'
            if rel == "yt_dlp/__init__.py" and bad_init:
                text = "raise ImportError('broken update')\n"
            z.writestr(rel, text)
        for name, text in (extra or {}).items():
            z.writestr(name, text)
    return buf.getvalue()


def test_version_key_orders_releases():
    assert up.version_key("2026.07.04") < up.version_key("2026.07.05") < up.version_key("2026.7.5.1")
    assert up.version_key("2026.10.01") > up.version_key("2026.9.30")


def test_install_rejects_a_wheel_that_does_not_match_its_checksum(root):
    data = make_wheel("2099.01.01")
    with pytest.raises(RuntimeError, match="checksum"):
        up.install_wheel(data, "2099.01.01", "0" * 64)
    assert not root.exists() or not any(root.iterdir())


def test_install_only_unpacks_the_yt_dlp_package(root):
    data = make_wheel("2099.01.01", {"evil.py": "x=1", "yt_dlp-2099.dist-info/METADATA": "m"})
    up.install_wheel(data, "2099.01.01", hashlib.sha256(data).hexdigest())
    found = up.installed()
    assert found and found["version"] == "2099.01.01"
    assert (Path(found["path"]) / "yt_dlp" / "__init__.py").is_file()
    assert not list(Path(found["path"]).glob("evil.py"))
    assert not list(Path(found["path"]).glob("*.dist-info"))


def test_install_refuses_paths_that_climb_out(root):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("yt_dlp/__init__.py", "")
        z.writestr("yt_dlp/../../outside.py", "x")
    data = buf.getvalue()
    with pytest.raises(RuntimeError, match="unsafe"):
        up.install_wheel(data, "2099.01.01", hashlib.sha256(data).hexdigest())
    assert up.installed() is None
    assert not (root.parent / "outside.py").exists()


def test_only_the_newest_update_is_kept(root):
    for v in ("2098.01.01", "2099.01.01"):
        data = make_wheel(v)
        up.install_wheel(data, v, hashlib.sha256(data).hexdigest())
    assert [p.name for p in root.iterdir() if p.is_dir()] == ["2099.01.01"]


def test_an_update_from_another_app_version_is_ignored(root):
    data = make_wheel("2099.01.01")
    up.install_wheel(data, "2099.01.01", hashlib.sha256(data).hexdigest())
    assert up.installed()
    (root / "current.json").write_text(json.dumps({"version": "2099.01.01", "app": "0.0.1"}))
    assert up.installed() is None  # a newer VidGrab brings its own newer yt-dlp


def _run(root: Path, code: str) -> str:
    env = {"VIDGRAB_YTDLP_DIR": str(root), "PATH": ""}
    repo = str(Path(__file__).parent.parent)
    code = f"import sys; sys.path.insert(0, {repo!r}); " + code
    return subprocess.run([sys.executable, "-I", "-c", code], env=env, capture_output=True,
                          text=True, check=True, cwd=str(root.parent)).stdout.strip()


SHOW = "import vidgrab, yt_dlp, yt_dlp.version as v; print(v.__version__, yt_dlp.__file__)"


@pytest.mark.skipif(sys.platform == "win32", reason="-I drops site-packages path handling on CI Windows")
def test_a_downloaded_yt_dlp_is_used_first(root):
    data = make_wheel("2099.01.01")
    up.install_wheel(data, "2099.01.01", hashlib.sha256(data).hexdigest())
    pkgs = str(Path(yt_dlp.__file__).parent.parent)
    out = _run(root, f"import sys; sys.path.append({pkgs!r}); {SHOW}")
    assert out.startswith("2099.01.01 ") and str(root) in out


@pytest.mark.skipif(sys.platform == "win32", reason="-I drops site-packages path handling on CI Windows")
def test_an_update_that_does_not_load_is_switched_off(root):
    data = make_wheel("2099.01.01", bad_init=True)
    up.install_wheel(data, "2099.01.01", hashlib.sha256(data).hexdigest())
    pkgs = str(Path(yt_dlp.__file__).parent.parent)
    out = _run(root, f"import sys; sys.path.append({pkgs!r}); {SHOW}")
    assert not out.startswith("2099.01.01") and str(root) not in out
    assert up.installed() is None  # deleted: the next start doesn't try again


def test_check_compares_with_pypi_metadata(monkeypatch, root):
    monkeypatch.setattr(up, "current_version", lambda: "2026.07.04")
    monkeypatch.setattr(up, "latest", lambda: {"version": "2026.08.01", "url": "u",
                                               "sha256": "s", "size": 1})
    assert up.check()["newer"] is True
    monkeypatch.setattr(up, "latest", lambda: {"version": "2026.07.04", "url": "u",
                                               "sha256": "s", "size": 1})
    assert up.check()["newer"] is False
    assert __version__  # the pointer is tied to this app version
