"""Decima (Death Stranding PC) packfile reader: locate & extract entries from the
encrypted .bin archives. Algorithm ported from Jayveer/Decima-Explorer (C++).

Two-stage build:
  1. Index: MurmurHash3-x64-128 path hashing + header/file-table decryption, so we can
     map a virtual path -> (archive, entry). No Oodle needed for lookup.
  2. Extract: chunk-table decrypt + per-chunk data decrypt + Oodle Kraken decompress.

Constants/seed from Decima-Explorer (util.h seed=42; DecimaArchive saltA/saltB).
"""
from __future__ import annotations
import struct
import hashlib
import ctypes
import threading
from bisect import bisect_left
from dataclasses import dataclass

MASK64 = 0xFFFFFFFFFFFFFFFF
SEED = 42
SALT_A = (0xFA3A9443, 0xF41CAB62, 0xF376811C, 0xD2A89E3E)
SALT_B = (0x6C084A37, 0x7E159D95, 0x3D5AF7E8, 0x18AA7D3F)


def _rotl(x, r):
    return ((x << r) | (x >> (64 - r))) & MASK64


def _fmix64(k):
    k ^= k >> 33
    k = (k * 0xFF51AFD7ED558CCD) & MASK64
    k ^= k >> 33
    k = (k * 0xC4CEB9FE1A85EC53) & MASK64
    k ^= k >> 33
    return k


def murmurhash3_x64_128(data: bytes, seed: int = SEED) -> bytes:
    """MurmurHash3 x64 128-bit, matching the C reference. Returns 16 bytes (h1||h2 LE)."""
    c1 = 0x87C37B91114253D5
    c2 = 0x4CF5AD432745937F
    length = len(data)
    nblocks = length // 16
    h1 = seed & MASK64
    h2 = seed & MASK64
    for i in range(nblocks):
        k1 = int.from_bytes(data[i * 16: i * 16 + 8], 'little')
        k2 = int.from_bytes(data[i * 16 + 8: i * 16 + 16], 'little')
        k1 = (k1 * c1) & MASK64; k1 = _rotl(k1, 31); k1 = (k1 * c2) & MASK64; h1 ^= k1
        h1 = _rotl(h1, 27); h1 = (h1 + h2) & MASK64; h1 = (h1 * 5 + 0x52DCE729) & MASK64
        k2 = (k2 * c2) & MASK64; k2 = _rotl(k2, 33); k2 = (k2 * c1) & MASK64; h2 ^= k2
        h2 = _rotl(h2, 31); h2 = (h2 + h1) & MASK64; h2 = (h2 * 5 + 0x38495AB5) & MASK64
    tail = data[nblocks * 16:]
    k1 = 0; k2 = 0
    tl = len(tail)
    if tl >= 9:
        for j in range(tl - 1, 7, -1):
            k2 = (k2 << 8) | tail[j]
        k2 = (k2 * c2) & MASK64; k2 = _rotl(k2, 33); k2 = (k2 * c1) & MASK64; h2 ^= k2
    if tl >= 1:
        upper = min(tl, 8)
        for j in range(upper - 1, -1, -1):
            k1 = (k1 << 8) | tail[j]
        k1 = (k1 * c1) & MASK64; k1 = _rotl(k1, 31); k1 = (k1 * c2) & MASK64; h1 ^= k1
    h1 ^= length; h2 ^= length
    h1 = (h1 + h2) & MASK64; h2 = (h2 + h1) & MASK64
    h1 = _fmix64(h1); h2 = _fmix64(h2)
    h1 = (h1 + h2) & MASK64; h2 = (h2 + h1) & MASK64
    return h1.to_bytes(8, 'little') + h2.to_bytes(8, 'little')


def file_hash(path: str) -> int:
    """Decima virtual-path hash: first 8 bytes of murmur3_x64_128(path + NUL, 42)."""
    digest = murmurhash3_x64_128(path.encode('utf-8') + b'\x00', SEED)
    return int.from_bytes(digest[:8], 'little')


def _decrypt_block(key: int, vals: list[int], off: int):
    """XOR 4 dwords at vals[off:off+4] with murmur3(key, saltA[1..3])."""
    inp = struct.pack('<IIII', key & 0xFFFFFFFF, SALT_A[1], SALT_A[2], SALT_A[3])
    iv = struct.unpack('<IIII', murmurhash3_x64_128(inp, SEED))
    for i in range(4):
        vals[off + i] ^= iv[i]


def _decrypt_chunk_data(key_block: bytes, data: bytearray):
    """Per-chunk data XOR: md5(murmur3(chunk_key_block) ^ saltB) repeating key."""
    iv = list(struct.unpack('<IIII', murmurhash3_x64_128(key_block, SEED)))
    for i in range(4):
        iv[i] ^= SALT_B[i]
    digest = hashlib.md5(struct.pack('<IIII', *iv)).digest()
    for i in range(len(data)):
        data[i] ^= digest[i % 16]


_oodle_cache: dict[str, ctypes.WinDLL] = {}
_oodle_lock = threading.Lock()

_OODLE_DECOMPRESS_ARGTYPES = [
    ctypes.c_char_p, ctypes.c_int64, ctypes.c_char_p, ctypes.c_int64,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int64,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64, ctypes.c_int,
]


def _load_oodle(dll_path: str):
    # Lock-guarded lazy init, keyed by dll_path: the DS render worker pool calls
    # oodle_decompress from several threads. Without the lock two threads could
    # both observe `dll_path not in _oodle_cache` and, worse, one could read the
    # freshly-cached lib before the other finished setting `.restype`/`.argtypes`,
    # calling OodleLZ_Decompress with the default (32-bit) return type and
    # misreading the decompressed size. The decompress call itself is a stateless
    # C function (ctypes drops the GIL around it), so only the one-time
    # per-path init needs guarding. Keyed (not a single global) so a second
    # PackIndex pointed at a different Oodle DLL doesn't silently reuse the
    # first one ever loaded.
    if dll_path not in _oodle_cache:
        with _oodle_lock:
            if dll_path not in _oodle_cache:
                lib = ctypes.WinDLL(dll_path)
                lib.OodleLZ_Decompress.restype = ctypes.c_int64
                lib.OodleLZ_Decompress.argtypes = _OODLE_DECOMPRESS_ARGTYPES
                _oodle_cache[dll_path] = lib
    return _oodle_cache[dll_path]


def oodle_decompress(dll_path: str, src: bytes, dst_size: int) -> bytes:
    lib = _load_oodle(dll_path)
    dst = ctypes.create_string_buffer(dst_size)
    n = lib.OodleLZ_Decompress(
        src, ctypes.c_int64(len(src)), dst, ctypes.c_int64(dst_size),
        0, 0, 0, None, 0, None, None, None, 0, 3)
    if n != dst_size:
        raise RuntimeError(f"Oodle decompress returned {n}, expected {dst_size}")
    return dst.raw[:dst_size]


@dataclass
class FileEntry:
    entry_num: int
    hash: int
    offset: int
    size: int


@dataclass
class ChunkEntry:
    uncompressed_offset: int
    uncompressed_size: int
    compressed_offset: int
    compressed_size: int
    key_block: bytes  # 16 bytes (decrypted offset/size + original key) for data decrypt


class BinArchive:
    def __init__(self, path: str):
        self.path = path
        self.encrypted = False
        self.file_table: list[FileEntry] = []
        self.chunk_table = []  # populated lazily for extraction
        self._offsets: list[int] = []  # parallel uncompressed offsets, for bisect lookup

    def open_index(self):
        """Parse + decrypt header and file table (enough to look up entries by hash)."""
        with open(self.path, 'rb') as f:
            head = f.read(0x28)
            magic, key = struct.unpack('<II', head[:8])
            if magic not in (0x20304050, 0x21304050):
                raise ValueError(f"bad magic 0x{magic:08X} in {self.path}")
            self.encrypted = bool(magic & 0x0F000000)
            # header dwords after magic,key: 6 dwords used (fileSize64,dataSize64,fileCount64,chunkCount32,maxChunk32)
            hv = list(struct.unpack('<IIIIIIII', head[8:0x28]))  # 8 dwords = 32 bytes
            if self.encrypted:
                _decrypt_block(key, hv, 0)
                _decrypt_block(key + 1, hv, 4)
            file_table_count = hv[4] | (hv[5] << 32)
            self.chunk_table_count = hv[6]
            # file table: count * 0x20
            tbl = f.read(file_table_count * 0x20)
            for i in range(file_table_count):
                e = list(struct.unpack('<IIIIIIII', tbl[i * 0x20:(i + 1) * 0x20]))
                ek, ek2 = e[1], e[7]
                if self.encrypted:
                    _decrypt_block(ek, e, 0)
                    _decrypt_block(ek2, e, 4)
                entry_num = e[0]
                h = e[2] | (e[3] << 32)
                offset = e[4] | (e[5] << 32)
                size = e[6]
                self.file_table.append(FileEntry(entry_num, h, offset, size))
            # chunk table follows the file table
            ctbl = f.read(self.chunk_table_count * 0x20)
            for i in range(self.chunk_table_count):
                c = list(struct.unpack('<IIIIIIII', ctbl[i * 0x20:(i + 1) * 0x20]))
                ck, ck2 = c[3], c[7]
                if self.encrypted:
                    _decrypt_block(ck, c, 0)
                    _decrypt_block(ck2, c, 4)
                self.chunk_table.append(ChunkEntry(
                    uncompressed_offset=c[0] | (c[1] << 32),
                    uncompressed_size=c[2],
                    compressed_offset=c[4] | (c[5] << 32),
                    compressed_size=c[6],
                    key_block=struct.pack('<IIII', c[0], c[1], c[2], ck)))
            # parallel offsets list for O(log n) floor-lookup (mirrors DsarArchive)
            self._offsets = [c.uncompressed_offset for c in self.chunk_table]

    def _find_chunk(self, offset: int) -> int:
        # bisect replacement for the old O(n) per-read linear scan. The old scan
        # used an *inclusive* upper bound (`ct[i].off <= offset <= ct[i+1].off`),
        # so an offset landing exactly on chunk i+1's start resolves to chunk i:
        # that is bisect_left-1 semantics, NOT DsarArchive's bisect_right-1 (the
        # inclusive upper bound is why this one differs). `max(0, ...)` clamps the
        # (unreachable, since chunk 0 starts at offset 0) below-first-chunk case
        # and matches the old scan's clamp-to-last for offsets past the end.
        return max(0, bisect_left(self._offsets, offset) - 1)

    def extract(self, entry: FileEntry, oodle_dll: str) -> bytes:
        first = self._find_chunk(entry.offset)
        last = self._find_chunk(entry.offset + entry.size)
        buf = bytearray()
        with open(self.path, 'rb') as f:
            for i in range(first, last + 1):
                c = self.chunk_table[i]
                f.seek(c.compressed_offset)
                comp = bytearray(f.read(c.compressed_size))
                if self.encrypted:
                    _decrypt_chunk_data(c.key_block, comp)
                if c.compressed_size == c.uncompressed_size:
                    buf += bytes(comp)
                else:
                    buf += oodle_decompress(oodle_dll, bytes(comp), c.uncompressed_size)
        start = entry.offset - self.chunk_table[first].uncompressed_offset
        return bytes(buf[start:start + entry.size])

    def find(self, path_or_hash) -> FileEntry | None:
        h = path_or_hash if isinstance(path_or_hash, int) else file_hash(path_or_hash)
        for e in self.file_table:
            if e.hash == h:
                return e
        return None
