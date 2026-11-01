"""CUDA 12 libraries for NVIDIA graphics cards (Qt-free).

CTranslate2 (faster-whisper) runs Whisper on an NVIDIA GPU, but loads the CUDA
libraries it needs, cuBLAS 12 and cuDNN 9, at run time, and almost nobody has
them installed. So the first time auto captions use a graphics card they are
downloaded (about 1.3 GB, once) from NVIDIA's own wheels on PyPI, pinned by
SHA-256 like the bundled ffmpeg, and unpacked to ``<models>/cuda``. Only the
driver, which comes with the graphics card, has to be on the computer.

To upgrade, change the pins below (filename, url, sha256, size from the
release pages of nvidia-cublas-cu12 and nvidia-cudnn-cu12 on PyPI).
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import platform
import sys
import urllib.request
import zipfile
from pathlib import Path

from vidgrab.downloader import ProgressCallback, TranslateFn, _noop_tr

# platform -> ((wheel file, url, sha256, size in bytes) of cuBLAS, then cuDNN)
PINS: dict[str, tuple[tuple[str, str, str, int], ...]] = {
    "linux": (
        ("nvidia_cublas_cu12-12.9.2.10-py3-none-manylinux_2_27_x86_64.whl",
         "https://files.pythonhosted.org/packages/cb/c0/0a517bfe63ccd3b92eb254d264e28fca3c7cab75d07daea315250fb1bf73/nvidia_cublas_cu12-12.9.2.10-py3-none-manylinux_2_27_x86_64.whl",
         "e4f53a8ca8c5d6e8c492d0d0a3d565ecb59a751b19cfdaa4f6da0ab2104c1702", 581240110),
        ("nvidia_cudnn_cu12-9.27.0.42-py3-none-manylinux_2_27_x86_64.whl",
         "https://files.pythonhosted.org/packages/65/e4/c5a205d48ff00ed8b27882bb45d338d8138e976c76385f328a326bbfaeda/nvidia_cudnn_cu12-9.27.0.42-py3-none-manylinux_2_27_x86_64.whl",
         "0a4aa3a7d2264256506c6857fc41fc0c499982f78d70195b1cfcc9055c1957cd", 766178381),
    ),
    "win": (
        ("nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl",
         "https://files.pythonhosted.org/packages/20/e2/fc9a0e985249d873150276d5afb02e39a66817fedbf1a385724393e505ed/nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl",
         "623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661", 553162896),
        ("nvidia_cudnn_cu12-9.27.0.42-py3-none-win_amd64.whl",
         "https://files.pythonhosted.org/packages/aa/38/f856579877f7c1c5066e61182e7de7bc27bf35a78c8d1b0fa592e6985bc4/nvidia_cudnn_cu12-9.27.0.42-py3-none-win_amd64.whl",
         "06e9b0026f3bad97d2b58666330fabec04fe1672f776661ecb0ce0029c27f142", 743068852),
    ),
}

# a library from each wheel: when both load by name, the runtime is usable
_PROBES = {"linux": ("libcublas.so.12", "libcudnn.so.9"),
           "win": ("cublas64_12.dll", "cudnn64_9.dll")}
# the wheels' library folders; everything else (headers, docs) is skipped
_MEMBER_DIRS = {"linux": ("nvidia/cublas/lib/", "nvidia/cudnn/lib/"),
                "win": ("nvidia/cublas/bin/", "nvidia/cudnn/bin/")}
_LIB_SUFFIX = {"linux": ".so", "win": ".dll"}
# loaded first, by absolute path, on Linux (the rest are found next to them)
_PRELOAD = ("libcublasLt.so.12", "libcublas.so.12", "libcudnn.so.9")


def platform_key() -> str | None:
    """"linux" / "win" on 64-bit x86 (the only builds NVIDIA publishes the
    wheels for), else None."""
    if platform.machine().lower() not in ("x86_64", "amd64"):
        return None
    if sys.platform == "win32":
        return "win"
    return "linux" if sys.platform.startswith("linux") else None


def runtime_dir(models_dir: str | Path) -> Path:
    return Path(models_dir) / "cuda"


def download_size_label() -> str:
    """How much the one-time download is, e.g. "1.3 GB"."""
    key = platform_key()
    total = sum(size for *_, size in PINS[key]) if key else 0
    return f"{total / 1e9:.1f} GB"


def libs_loadable() -> bool:
    """Whether cuBLAS 12 and cuDNN 9 can be loaded by name right now."""
    key = platform_key()
    if key is None:
        return False
    try:
        for name in _PROBES[key]:
            (ctypes.WinDLL if key == "win" else ctypes.CDLL)(name)  # type: ignore[attr-defined]
    except OSError:
        return False
    return True


def runtime_ready(models_dir: str | Path) -> bool:
    """True when nothing needs downloading: already unpacked, or installed on
    the system."""
    return (runtime_dir(models_dir) / "COMPLETE").is_file() or libs_loadable()


def register(folder: Path) -> None:
    """Make the unpacked libraries findable by CTranslate2's run-time loading."""
    key = platform_key()
    if key == "win":
        os.add_dll_directory(str(folder))  # type: ignore[attr-defined]
        os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
    elif key == "linux":
        for name in _PRELOAD:  # RTLD_GLOBAL: later loads by name reuse these
            if (folder / name).is_file():
                ctypes.CDLL(str(folder / name), mode=ctypes.RTLD_GLOBAL)


def _download(url: str, sha256: str, dest: Path, on_bytes) -> None:
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as resp, open(dest, "wb") as fh:  # pinned https URL
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
            digest.update(chunk)
            on_bytes(len(chunk))
    if digest.hexdigest() != sha256:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 mismatch for {dest.name}")


def _unpack(wheel: Path, folder: Path, key: str) -> None:
    """Copy the wheel's libraries flat into *folder* (cuDNN finds its parts
    next to itself)."""
    with zipfile.ZipFile(wheel) as zf:
        for info in zf.infolist():
            name = info.filename
            if (name.startswith(_MEMBER_DIRS[key]) and not info.is_dir()
                    and _LIB_SUFFIX[key] in name.rsplit("/", 1)[-1]):
                target = folder / name.rsplit("/", 1)[-1]
                with zf.open(info) as src, open(target, "wb") as out:
                    while chunk := src.read(1 << 20):
                        out.write(chunk)
                target.chmod(0o755)


def ensure_runtime(
    models_dir: str | Path,
    *,
    on_progress: ProgressCallback | None = None,
    translate: TranslateFn | None = None,
) -> None:
    """Make CUDA 12's cuBLAS and cuDNN loadable, downloading them first if
    they are neither installed nor already unpacked. Raises RuntimeError when
    that can't be done (the caller then uses another engine)."""
    tr = translate or _noop_tr
    key = platform_key()
    if key is None:
        raise RuntimeError(tr("NVIDIA graphics cards are only supported on 64-bit Windows and Linux."))
    if libs_loadable():
        return
    folder = runtime_dir(models_dir)
    if not (folder / "COMPLETE").is_file():
        folder.mkdir(parents=True, exist_ok=True)
        total = sum(size for *_, size in PINS[key]) or 1
        done = 0
        last = -1

        def on_bytes(n: int) -> None:
            nonlocal done, last
            done += n
            pct = min(100, int(done * 100 / total))
            if on_progress and pct != last:
                last = pct
                on_progress(tr("Downloading the NVIDIA CUDA libraries…"), pct)

        for filename, url, sha256, size in PINS[key]:
            if (folder / (filename + ".done")).is_file():  # a retry resumes after the last package
                on_bytes(size)
                continue
            wheel = folder / (filename + ".part")
            try:
                _download(url, sha256, wheel, on_bytes)
                _unpack(wheel, folder, key)
            except OSError as exc:  # no network, a dropped connection, a full disk
                raise RuntimeError(tr("The NVIDIA CUDA libraries could not be downloaded. "
                                      "Check your internet connection.") + f" ({exc})") from exc
            finally:
                wheel.unlink(missing_ok=True)
            (folder / (filename + ".done")).write_text("ok\n", encoding="utf-8")
        (folder / "COMPLETE").write_text("cuBLAS 12.9.2.10, cuDNN 9.27.0.42\n", encoding="utf-8")
    register(folder)
    if not libs_loadable():
        raise RuntimeError(tr("The NVIDIA CUDA libraries could not be loaded."))
