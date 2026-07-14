"""Read payload bytes from a Forbidden West package file at a streaming-graph
locator address.

A :class:`~engine.pack.fw_streaming_graph.Locator` gives ``(file_index, offset)``.
The file may be a DSAR container (compressed, logical offsets) or a raw payload
store (e.g. ``en/package.01.00.core.stream`` — dialogue audio, stored as
back-to-back RIFF/WAVE ATRAC9 clips). We sniff the ``DSAR`` magic per file and
pick the right reader, mirroring odradek's ``StreamingGraphStorage.mount``.

Dialogue audio clips are self-describing RIFF containers, so a clip can be read
without knowing its length up front (:meth:`read_riff_clip`); the resource's
``StreamingDataSource.Length`` is an independent cross-check.
"""
from __future__ import annotations

import os
import struct

from deciwaves.engine.pack.dsar_archive import DsarArchive


class FwStreamStore:
    """Lazily-opened readers for a package dir's ``Files`` table, DSAR-aware."""

    def __init__(self, package_dir: str, files: list[str]):
        self.package_dir = package_dir
        # strip the "cache:package/" device prefix -> path relative to package dir
        self.files = [f.replace("cache:package/", "") for f in files]
        self._dsar: dict[int, DsarArchive | None] = {}

    def _path(self, file_index: int) -> str:
        return os.path.join(self.package_dir, self.files[file_index])

    def _reader(self, file_index: int) -> DsarArchive | None:
        """Return a DsarArchive for DSAR files, or None for raw files."""
        if file_index not in self._dsar:
            path = self._path(file_index)
            with open(path, "rb") as f:
                magic = f.read(4)
            self._dsar[file_index] = DsarArchive(path) if magic == b"DSAR" else None
        return self._dsar[file_index]

    def read(self, file_index: int, offset: int, length: int) -> bytes:
        """Read *length* bytes at logical *offset* (DSAR-decompressed if needed)."""
        dsar = self._reader(file_index)
        if dsar is not None:
            return dsar.read(offset, length)
        with open(self._path(file_index), "rb") as f:
            f.seek(offset)
            return f.read(length)

    def read_riff_clip(self, file_index: int, offset: int) -> bytes:
        """Read a self-describing RIFF clip (``RIFF`` + u32 size) at *offset*
        from a raw payload store. Returns the full ``size + 8`` bytes."""
        head = self.read(file_index, offset, 8)
        if head[:4] != b"RIFF":
            raise ValueError(
                f"no RIFF at file {file_index} offset {offset}: {head[:4]!r}"
            )
        riff_size = struct.unpack_from("<I", head, 4)[0]
        return self.read(file_index, offset, riff_size + 8)
