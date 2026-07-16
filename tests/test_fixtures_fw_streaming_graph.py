"""Synthetic-bytes fixture for Forbidden West's ``streaming_graph.core`` header
(`engine.pack.fw_streaming_graph.StreamingGraph`).

`test_fw_streaming_graph.py` only runs against a real, install-gated
``streaming_graph.core`` (via the `fw_streaming_graph_bytes` fixture, which
skips without `DECIWAVES_FW_INSTALL`) -- so this parser has ~0% CI coverage.
The on-disk layout is a plain, fully-specified struct (documented in the
module's own docstring and mirrored exactly by the dataclass field order
below), with no encryption and no external decoder dependency, so it is
directly synthesizable -- same technique as `tests/test_dsar_archive.py`.

Builds one minimal-but-non-trivial StreamingGraphResource body (two archive
files, two locators, two spans, one group, one object locator) entirely by
hand and runs the REAL, un-modified `StreamingGraph` parser over it.
"""
import struct

import numpy as np
import pytest

from deciwaves.engine.pack.fw_streaming_graph import (
    STREAMING_GRAPH_RESOURCE,
    StreamingGraph,
    _GROUP_DTYPE,
    _OBJLOC_DTYPE,
    _SPAN_DTYPE,
)


def _array(u32_count, payload_bytes):
    return struct.pack("<I", u32_count) + payload_bytes


def _filename(name: str) -> bytes:
    b = name.encode("utf-8")
    return struct.pack("<II", len(b), 0) + b  # len, crc32(unused, dummy 0), bytes


def _build_streaming_graph_bytes():
    object_uuid = bytes(range(16))
    is_packed = 1

    type_hashes = np.array([0x1111111111111111, 0x2222222222222222], dtype="<u8")
    # TypeTableData header: compression(0), stride(2), count, count2(==count), unk10(1),
    # then `count` u16 indices into type_hashes -- one slot per object (2 objects, both type 0).
    type_table_data = (
        struct.pack("<IIIII", 0, 2, 2, 2, 1) + struct.pack("<HH", 0, 0)
    )

    link_table_id = 0
    link_table_size = 0

    # LocatorTable: raw u64 = (offset << 24) | file_index.
    locators_raw = np.array(
        [(1000 << 24) | 0, (2000 << 24) | 1], dtype="<u8"
    )

    array_table = np.array([], dtype="<u4")

    spans = np.array(
        [(0, 10, 0), (1, 20, 100)], dtype=_SPAN_DTYPE
    )  # (file_and_patch, length, offset)

    groups = np.array(
        [(1, 2, 0, 0, 0, 0, 0, 0, 2, 0, 2, 0, 0, 0, 2)], dtype=_GROUP_DTYPE
    )
    # fields: group_id, num_objects, group_size, sub_group_start, sub_group_count,
    #         root_start, root_count, span_start, span_count, type_start, type_count,
    #         link_start, link_size, locator_start, locator_count

    sub_groups = np.array([], dtype="<u4")
    root_uuids = np.array([], dtype="S16")
    root_indices = np.array([], dtype="<u4")

    files = _filename("en/package.01.00.core.stream") + _filename("dlc/en/package.01.00.core.stream")

    object_locators = np.array(
        [(bytes(range(16, 32)), 0, 0, 0, 500, 50)], dtype=_OBJLOC_DTYPE
    )  # uuid, type_index, reserved, file_index, offset, length

    pack_file_uncompressed_block_size = 0x10000
    pack_file_max_compressed_block_size = 0x20000

    body = b"".join([
        object_uuid,
        struct.pack("<B", is_packed),
        _array(len(type_hashes), type_hashes.tobytes()),
        _array(len(type_table_data), type_table_data),
        struct.pack("<Qi", link_table_id, link_table_size),
        _array(len(locators_raw), locators_raw.tobytes()),
        _array(len(array_table), array_table.tobytes()),
        _array(len(spans), spans.tobytes()),
        _array(len(groups), groups.tobytes()),
        _array(len(sub_groups), sub_groups.tobytes()),
        _array(len(root_uuids), root_uuids.tobytes()),
        _array(len(root_indices), root_indices.tobytes()),
        struct.pack("<I", 2) + files,             # Files array: count=2
        struct.pack("<I", 0),                      # PackFileOffsets: outer count=0
        struct.pack("<I", 0),                      # PackFileLengths: outer count=0
        _array(len(object_locators), object_locators.tobytes()),
        struct.pack("<II", pack_file_uncompressed_block_size, pack_file_max_compressed_block_size),
    ])

    header = struct.pack("<QI", STREAMING_GRAPH_RESOURCE, len(body))
    trailing_num_links = struct.pack("<I", 0)  # matches real .core framing; unused by StreamingGraph
    return header + body + trailing_num_links


def test_parses_synthetic_streaming_graph():
    g = StreamingGraph(_build_streaming_graph_bytes())

    assert g.is_packed is True
    assert len(g.files) == 2
    assert g.files[0] == "en/package.01.00.core.stream"
    assert g.file_index("dlc/en/package.01.00.core.stream") == 1
    with pytest.raises(KeyError):
        g.file_index("no/such/file")

    assert len(g.locators) == 2
    assert g.locators[0].file_index == 0
    assert g.locators[0].offset == 1000
    assert g.locators[1].file_index == 1
    assert g.locators[1].offset == 2000

    assert len(g.spans) == 2
    assert g.spans[0].file_index == 0 and g.spans[0].length == 10 and g.spans[0].offset == 0
    assert g.spans[1].file_index == 1 and g.spans[1].length == 20 and g.spans[1].offset == 100

    assert len(g.groups) == 1
    grp = g.group(1)
    assert grp.locator_start == 0 and grp.locator_count == 2
    assert grp.span_start == 0 and grp.span_count == 2
    assert grp.type_count == grp.num_objects == 2
    assert g.group(grp.group_id) is grp

    assert len(g.object_locators) == 1
    ol = g.object_locators[0]
    assert ol.uuid == bytes(range(16, 32))
    assert ol.file_index == 0 and ol.offset == 500 and ol.length == 50

    # TypeTableData resolved against TypeHashes -- both object slots point at hash index 0.
    assert list(g.type_table) == [0x1111111111111111, 0x1111111111111111]

    assert g.pack_file_uncompressed_block_size == 0x10000
    assert g.pack_file_max_compressed_block_size == 0x20000


def test_wrong_type_hash_raises():
    bad = struct.pack("<QI", 0xDEADBEEFDEADBEEF, 0)
    with pytest.raises(ValueError, match="StreamingGraphResource"):
        StreamingGraph(bad)


def test_inflated_size_raises_size_mismatch():
    good = _build_streaming_graph_bytes()
    # Inflate the declared body `size` by 4 without touching any field content. The
    # buffer still has >=4 physically-present bytes past the true body end (the
    # trailing num_links word), so every real field parses fine and the cursor ends
    # up 4 bytes short of the (inflated) body_end -- a pure under-consumption
    # mismatch, not a buffer underrun, so it must raise "not size-exact" cleanly.
    type_hash, size = struct.unpack_from("<QI", good, 0)
    inflated = struct.pack("<QI", type_hash, size + 4) + good[12:]
    with pytest.raises(ValueError, match="not size-exact"):
        StreamingGraph(inflated)


def test_type_hash_constant():
    assert STREAMING_GRAPH_RESOURCE == 0x929D7AF6A30CD1C5
