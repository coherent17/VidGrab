"""Compress PyInstaller's one-file archive on every CPU core.

PyInstaller packs each file of the one-file binary with zlib level 9, one file
after another on one thread: about three quarters of a 2-minute build. zlib
lets go of the GIL while it compresses, so the files can be compressed in a
thread pool and still written in the original order. The archive is the same
byte for byte (same level, same order), only sooner.

``install()`` swaps the writer PyInstaller's ``PKG`` step uses; call it from the
spec file. Anything unexpected falls back to the normal one-file-at-a-time path.
"""

from __future__ import annotations

import os
import zlib
from concurrent.futures import ThreadPoolExecutor

# typecodes that are not "a file to copy" (see CArchiveWriter._write_entry)
_NOT_FILES = {"o", "d", "s", "s1", "s2", "m", "M", "n"}


def make_writer(base: type) -> type:
    """A subclass of PyInstaller's CArchiveWriter that deflates files ahead, in threads."""

    class ParallelCArchiveWriter(base):  # type: ignore[misc, valid-type]
        def __init__(self, filename, entries, pylib_name):
            entries = list(entries)
            self._ahead: dict = {}
            usable = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
            workers = max(1, min(usable or 1, 8))
            pool = ThreadPoolExecutor(workers) if workers > 1 else None
            try:
                if pool is not None:
                    for _dest, src, compress, typecode in entries:
                        if (compress and typecode not in _NOT_FILES and src not in self._ahead
                                and os.path.isfile(src)):
                            self._ahead[src] = pool.submit(self._deflate, src)
                super().__init__(filename, entries, pylib_name)
            finally:
                if pool is not None:
                    pool.shutdown(wait=True, cancel_futures=True)
                self._ahead.clear()

        @classmethod
        def _deflate(cls, src_name: str) -> tuple[bytes, int]:
            with open(src_name, "rb") as fp:
                data = fp.read()
            return zlib.compress(data, cls._COMPRESSION_LEVEL), len(data)

        def _write_file(self, out_fp, src_name, dest_name, typecode, compress=False):
            future = self._ahead.pop(src_name, None) if compress else None
            if future is not None:
                try:
                    blob, length = future.result()
                except Exception:  # noqa: BLE001 - do it the slow, normal way
                    return super()._write_file(out_fp, src_name, dest_name, typecode, compress)
                offset = out_fp.tell()
                out_fp.write(blob)
                return (offset, len(blob), length, 1, typecode, dest_name)
            return super()._write_file(out_fp, src_name, dest_name, typecode, compress)

    return ParallelCArchiveWriter


def install() -> None:
    """Make PyInstaller's PKG step use the parallel writer."""
    from PyInstaller.archive import writers
    from PyInstaller.building import api

    api.CArchiveWriter = make_writer(writers.CArchiveWriter)
