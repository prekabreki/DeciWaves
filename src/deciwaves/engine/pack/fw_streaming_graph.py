"""Parse Horizon Forbidden West's ``streaming_graph.core`` (StreamingGraphResource).

FW (and Burning Shores) index every package archive through this single ~55 MB
resource instead of HZD-Remastered's ``PackFileLocators.bin`` (which FW does not
ship). It carries the archive name table (``Files``), the per-line audio stream
``LocatorTable`` (consumed positionally — see :mod:`fw_object_reader`), the object
storage ``SpanTable``, and the ``Groups`` that slice into all of them.

Layout reverse-engineered from ShadelessFox/odradek
(``odradek-game-hfw`` ``StreamingGraphImpl`` + generated ``types.json``) and
verified byte-exact against the retail install. See
``.memories/fw-streaming-graph.md``.

On-disk framing is a standard Decima ``.core`` object::

    u64 type_hash   # murmur3_x64_128(seed=42, "00000001_StreamingGraphResource").low64
                    #   = 0x929d7af6a30cd1c5  (note the "00000001_" type-db version prefix)
    u32 size        # body byte count
    ... body ...
    u32 num_links   # == 0 for this object

The body is the StreamingGraphResource compound, fields serialised in ascending
C++ offset order (non-serialised ``property`` fields omitted):

    ObjectUUID   GGUUID(16)                 @8   (from base RTTIRefObject)
    IsPacked     bool(1)                     @32
    TypeHashes   Array<u64>                  @40
    TypeTableData Array<u8>                  @72
    LinkTableID  u64                         @144
    LinkTableSize i32                        @152
    LocatorTable Array<StreamingDataSourceLocator{u64}>  @160
    ArrayTable   Array<u32>                  @176
    SpanTable    Array<StreamingSourceSpan{u32,i32,i32}> @192
    Groups       Array<StreamingGroupData(64B)>          @208
    SubGroups    Array<u32>                  @224
    RootUUIDs    Array<GGUUID(16)>           @240
    RootIndices  Array<u32>                  @256
    Files        Array<Filename>            @336
    PackFileOffsets Array<Array<i32>>        @352
    PackFileLengths Array<Array<i32>>        @368
    ObjectLocators  Array<StreamingObjectLocator(32B)> @384
    PackFileUncompressedBlockSize  u32       @400
    PackFileMaxCompressedBlockSize u32       @404

A ``Filename``/``String`` is ``u32 length, u32 crc32, byte[length]`` (UTF-8, not
NUL-terminated). All multi-byte values are little-endian.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

# murmur3_x64_128(seed=42, "00000001_StreamingGraphResource").low64
STREAMING_GRAPH_RESOURCE = 0x929D7AF6A30CD1C5


@dataclass(frozen=True)
class Locator:
    """One ``LocatorTable`` entry: a streamed audio payload address.

    Decoded from the raw u64 exactly as odradek's ``computeLocators``:
    ``file_index = data & 0xFFFFFF`` (index into :attr:`StreamingGraph.files`),
    ``offset = data >> 24`` (byte offset within that file, logical space).
    """
    file_index: int
    offset: int


@dataclass(frozen=True)
class Span:
    """One ``SpanTable`` entry: a byte range holding serialised object(s)."""
    file_index: int
    offset: int
    length: int


@dataclass(frozen=True)
class ObjectLocator:
    """One ``ObjectLocators`` entry: UUID -> object storage location."""
    uuid: bytes        # raw 16 bytes (on-disk order)
    type_index: int
    file_index: int
    offset: int
    length: int


@dataclass(frozen=True)
class Group:
    """One ``StreamingGroupData`` record (64 bytes). Fields are slice bounds
    into the graph-global tables (see :class:`StreamingGraph`)."""
    group_id: int
    num_objects: int
    group_size: int
    sub_group_start: int
    sub_group_count: int
    root_start: int
    root_count: int
    span_start: int
    span_count: int
    type_start: int
    type_count: int
    link_start: int
    link_size: int
    locator_start: int
    locator_count: int


class _Cursor:
    """Sequential little-endian reader with a position, for size-exact parsing."""

    __slots__ = ("data", "pos")

    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    def u8(self) -> int:
        v = self.data[self.pos]
        self.pos += 1
        return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return v

    def u64(self) -> int:
        v = struct.unpack_from("<Q", self.data, self.pos)[0]
        self.pos += 8
        return v

    def raw(self, n: int) -> bytes:
        v = self.data[self.pos:self.pos + n]
        self.pos += n
        return v

    def bulk(self, dtype: np.dtype, count: int) -> np.ndarray:
        """Read *count* records of *dtype* as a numpy array (zero-copy view)."""
        a = np.frombuffer(self.data, dtype=dtype, count=count, offset=self.pos)
        self.pos += count * dtype.itemsize
        return a

    def string(self) -> str:
        """Decima Filename/String: u32 len, u32 crc32, byte[len] UTF-8."""
        length = self.u32()
        if length == 0:
            return ""
        self.u32()  # crc32 (path hash) — unused for resolution
        return self.raw(length).decode("utf-8", "replace")


_GROUP_DTYPE = np.dtype([
    ("group_id", "<i4"), ("num_objects", "<i4"), ("group_size", "<i8"),
    ("sub_group_start", "<u4"), ("sub_group_count", "<u4"),
    ("root_start", "<u4"), ("root_count", "<u4"),
    ("span_start", "<u4"), ("span_count", "<u4"),
    ("type_start", "<u4"), ("type_count", "<u4"),
    ("link_start", "<u4"), ("link_size", "<u4"),
    ("locator_start", "<u4"), ("locator_count", "<u4"),
])
_SPAN_DTYPE = np.dtype([("file_and_patch", "<u4"), ("length", "<i4"), ("offset", "<i4")])
_OBJLOC_DTYPE = np.dtype([
    ("uuid", "S16"), ("type_index", "<u2"), ("reserved", "<u2"),
    ("file_index", "<i4"), ("offset", "<i4"), ("length", "<i4"),
])


class _LocatorView:
    """List-like view over the locator table, materialising :class:`Locator`
    only for the (small) slices callers actually request."""

    __slots__ = ("_fi", "_off")

    def __init__(self, file_index: np.ndarray, offset: np.ndarray):
        self._fi = file_index
        self._off = offset

    def __len__(self) -> int:
        return len(self._fi)

    @property
    def file_index(self) -> np.ndarray:
        return self._fi

    def __getitem__(self, i):
        if isinstance(i, slice):
            fi = self._fi[i].tolist()
            off = self._off[i].tolist()
            return [Locator(a, b) for a, b in zip(fi, off)]
        return Locator(int(self._fi[i]), int(self._off[i]))


class _SpanView:
    __slots__ = ("_fi", "_off", "_len")

    def __init__(self, file_index, offset, length):
        self._fi, self._off, self._len = file_index, offset, length

    def __len__(self) -> int:
        return len(self._fi)

    @property
    def file_index(self) -> np.ndarray:
        return self._fi

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [Span(a, b, c) for a, b, c in
                    zip(self._fi[i].tolist(), self._off[i].tolist(), self._len[i].tolist())]
        return Span(int(self._fi[i]), int(self._off[i]), int(self._len[i]))


class _ObjectLocatorView:
    __slots__ = ("_a",)

    def __init__(self, arr: np.ndarray):
        self._a = arr

    def __len__(self) -> int:
        return len(self._a)

    @property
    def file_index(self) -> np.ndarray:
        return self._a["file_index"]

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self._one(r) for r in self._a[i]]
        return self._one(self._a[i])

    @staticmethod
    def _one(r) -> ObjectLocator:
        return ObjectLocator(bytes(r["uuid"]), int(r["type_index"]),
                             int(r["file_index"]), int(r["offset"]), int(r["length"]))


class StreamingGraph:
    """Parsed StreamingGraphResource. Global tables + group lookup."""

    def __init__(self, core_bytes: bytes):
        c = _Cursor(core_bytes)
        type_hash = c.u64()
        if type_hash != STREAMING_GRAPH_RESOURCE:
            raise ValueError(
                f"not a StreamingGraphResource (type_hash=0x{type_hash:016x})"
            )
        size = c.u32()
        body_start = c.pos
        body_end = body_start + size

        c.raw(16)                      # ObjectUUID
        self.is_packed = c.u8() != 0   # IsPacked

        self._type_hashes: np.ndarray = c.bulk(np.dtype("<u8"), c.u32())
        self.type_table_data: bytes = c.raw(c.u32())
        self.link_table_id: int = c.u64()
        self.link_table_size: int = c.i32()

        loc = c.bulk(np.dtype("<u8"), c.u32())
        self.locators = _LocatorView(
            (loc & 0xFFFFFF).astype(np.int64), (loc >> 24).astype(np.int64)
        )
        self.array_table: np.ndarray = c.bulk(np.dtype("<u4"), c.u32())

        spans = c.bulk(_SPAN_DTYPE, c.u32())
        self.spans = _SpanView(
            (spans["file_and_patch"] & 0x7FFFFFFF).astype(np.int64),
            spans["offset"].astype(np.int64), spans["length"].astype(np.int64),
        )

        group_arr = c.bulk(_GROUP_DTYPE, c.u32())
        self.groups: list[Group] = [Group(*rec) for rec in group_arr.tolist()]

        self.sub_groups: np.ndarray = c.bulk(np.dtype("<u4"), c.u32())
        self.root_uuids = c.bulk(np.dtype("S16"), c.u32())
        self.root_indices: np.ndarray = c.bulk(np.dtype("<u4"), c.u32())
        self.files: list[str] = [c.string() for _ in range(c.u32())]

        self.pack_file_offsets: list[np.ndarray] = self._read_array_of_int_arrays(c)
        self.pack_file_lengths: list[np.ndarray] = self._read_array_of_int_arrays(c)

        self.object_locators = _ObjectLocatorView(c.bulk(_OBJLOC_DTYPE, c.u32()))

        self.pack_file_uncompressed_block_size = c.u32()
        self.pack_file_max_compressed_block_size = c.u32()

        if c.pos != body_end:
            raise ValueError(
                f"body not size-exact: consumed {c.pos - body_start} of {size} bytes"
            )

        # group id -> group (ids are NOT necessarily array indices)
        self._by_id: dict[int, Group] = {g.group_id: g for g in self.groups}

        self.type_table: np.ndarray = self._read_type_table()

    def _read_type_table(self) -> np.ndarray:
        """Resolve ``TypeTableData`` to a flat array of type hashes (one per
        object slot). Header: u32 compression(0), stride(2), count, count2
        (==count), unk10(1); then count x u16 indices into ``type_hashes``
        (odradek ``StreamingGraphImpl.readTypeTable``)."""
        c = _Cursor(self.type_table_data)
        compression = c.u32()
        stride = c.u32()
        count = c.u32()
        count2 = c.u32()
        unk10 = c.u32()
        if compression != 0 or stride != 2 or count != count2 or unk10 != 1:
            raise ValueError(
                f"unexpected type-table header "
                f"(compression={compression} stride={stride} "
                f"count={count}/{count2} unk10={unk10})"
            )
        indices = c.bulk(np.dtype("<u2"), count)
        return self._type_hashes[indices]

    @staticmethod
    def _read_array_of_int_arrays(c: _Cursor) -> list[np.ndarray]:
        outer = c.u32()
        return [c.bulk(np.dtype("<i4"), c.u32()) for _ in range(outer)]

    # --- accessors ---------------------------------------------------------
    def group(self, group_id: int) -> Group:
        return self._by_id[group_id]

    def file_index(self, name_suffix: str) -> int:
        """Index of the first ``Files`` entry ending with *name_suffix*."""
        for i, f in enumerate(self.files):
            if f.endswith(name_suffix):
                return i
        raise KeyError(name_suffix)

    @classmethod
    def from_file(cls, path: str) -> "StreamingGraph":
        with open(path, "rb") as f:
            return cls(f.read())
