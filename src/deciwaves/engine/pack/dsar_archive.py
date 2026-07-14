"""Read one DSAR container (HZD Remastered package.NN.NN.core[.stream]).

DSAR is the Decima Forbidden-West streaming archive: a 32-byte header, a table of
32-byte chunk descriptors, then LZ4-block-compressed chunk data. A logical (uncompressed)
offset is mapped to the chunk whose uncompressed range covers it; chunks are decompressed
and sliced. Format confirmed against the retail install; see .memories/hzd-pack-format.md. Little-endian.
"""
from __future__ import annotations
import struct
from bisect import bisect_right
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

    def __init__(self, path: str):
        self.path = path
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

    def read(self, offset: int, length: int) -> bytes:
        first = self._first_chunk(offset)
        buf = bytearray()
        i = first
        with open(self.path, "rb") as f:
            while len(buf) < (offset - self._chunks[first].offset) + length:
                c = self._chunks[i]
                f.seek(c.compressed_offset)
                comp = f.read(c.compressed_size)
                if c.compressed_size == c.size:
                    raw = comp                     # stored uncompressed
                elif c.ctype == 3:
                    raw = lz4.block.decompress(comp, uncompressed_size=c.size)
                else:
                    raise ValueError(f"unsupported DSAR chunk type {c.ctype} in {self.path}")
                buf += raw
                i += 1
                if i >= len(self._chunks):
                    break
        start = offset - self._chunks[first].offset
        return bytes(buf[start:start + length])
