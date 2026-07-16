"""Read one DSAR container (HZD Remastered package.NN.NN.core[.stream]).

DSAR is the Decima Forbidden-West streaming archive: a 32-byte header, a table of
32-byte chunk descriptors, then LZ4-block-compressed chunk data. A logical (uncompressed)
offset is mapped to the chunk whose uncompressed range covers it; chunks are decompressed
and sliced. Format confirmed against the retail install; see .memories/hzd-pack-format.md. Little-endian.
"""
from __future__ import annotations
import struct
import threading
from bisect import bisect_right
from collections import OrderedDict
from dataclasses import dataclass

import lz4.block


@dataclass(frozen=True)
class _Chunk:
    offset: int            # uncompressed/logical
    compressed_offset: int # physical
    size: int              # uncompressed
    compressed_size: int
    ctype: int             # 3 = LZ4


class DsarArchive:
    MAGIC = b"DSAR"

    # Decompressed-chunk LRU cap (issue #50 / M17). Keys are chunk indices, values
    # are the whole decompressed chunk bytes. 16 comfortably covers the working set
    # of the #41 decode pool: default_jobs() <= 8 concurrent readers, each touching
    # its current chunk plus (for a boundary-spanning clip) the next one, with a few
    # slots of headroom for the pool's in-order dispatch reordering (up to jobs*2 in
    # flight). Bounded memory: <= 16 chunks resident (~4 MiB at 256 KiB chunks).
    _CACHE_MAX = 16

    def __init__(self, path: str):
        self.path = path
        # Per-archive decompressed-chunk LRU, shared across the pool's threads.
        # Stores BYTES only (never file handles), keyed by chunk index, so a cached
        # entry is immutable and safe to hand to any thread. The lock guards only
        # the OrderedDict ops -- never the file read / LZ4 decompress -- so a
        # cold-cache race at most does redundant, identical-bytes work.
        self._chunk_cache: "OrderedDict[int, bytes]" = OrderedDict()
        self._cache_lock = threading.Lock()
        with open(path, "rb") as f:
            header = f.read(32)
            magic, ver_major, ver_minor, chunk_count, _first_chunk_off, total = \
                struct.unpack("<4sHHIIQ8x", header)
            if magic != self.MAGIC:
                raise ValueError(f"not a DSAR archive (magic={magic!r}) in {path}")
            self.total_size = total
            table = f.read(chunk_count * 32)
        self._chunks: list[_Chunk] = []
        for i in range(chunk_count):
            off, coff, size, csize, ctype = struct.unpack_from("<QQIIB7x", table, i * 32)
            self._chunks.append(_Chunk(off, coff, size, csize, ctype))
        # parallel list of uncompressed offsets for floor-lookup
        self._offsets = [c.offset for c in self._chunks]

    def _first_chunk(self, offset: int) -> int:
        # greatest chunk offset <= offset
        return bisect_right(self._offsets, offset) - 1

    def _cached_chunk(self, i: int) -> bytes | None:
        """Return chunk *i*'s decompressed bytes if resident, else None (LRU touch)."""
        with self._cache_lock:
            raw = self._chunk_cache.get(i)
            if raw is not None:
                self._chunk_cache.move_to_end(i)
        return raw

    def _load_chunk(self, f, i: int) -> bytes:
        """Read + decompress chunk *i* from open handle *f*, then cache it.

        The lock is dropped across the file read and LZ4 decompress: two threads
        racing on a cold chunk both do the work and both store identical bytes
        (last write wins) -- redundant but never wrong.
        """
        c = self._chunks[i]
        f.seek(c.compressed_offset)
        comp = f.read(c.compressed_size)
        if c.compressed_size == c.size:
            raw = comp                     # stored uncompressed
        elif c.ctype == 3:
            raw = lz4.block.decompress(comp, uncompressed_size=c.size)
        else:
            raise ValueError(f"unsupported DSAR chunk type {c.ctype} in {self.path}")
        with self._cache_lock:
            self._chunk_cache[i] = raw
            self._chunk_cache.move_to_end(i)
            while len(self._chunk_cache) > self._CACHE_MAX:
                self._chunk_cache.popitem(last=False)
        return raw

    def read(self, offset: int, length: int) -> bytes:
        first = self._first_chunk(offset)
        if first < 0:
            raise ValueError(
                f"no chunk contains offset {offset} (length {length}) in {self.path}"
            )
        buf = bytearray()
        i = first
        f = None
        try:
            while len(buf) < (offset - self._chunks[first].offset) + length:
                raw = self._cached_chunk(i)
                if raw is None:
                    if f is None:              # open lazily: skipped when all chunks hit
                        f = open(self.path, "rb")
                    raw = self._load_chunk(f, i)
                buf += raw
                i += 1
                if i >= len(self._chunks):
                    break
        finally:
            if f is not None:
                f.close()
        start = offset - self._chunks[first].offset
        result = bytes(buf[start:start + length])
        if len(result) != length:
            raise ValueError(
                f"short read at offset {offset} length {length} in {self.path} "
                f"(got {len(result)} bytes, likely past EOF)"
            )
        return result
