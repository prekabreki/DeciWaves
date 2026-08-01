"""Synthetic-bytes fixture for Death Stranding 2's ``streaming_graph.core``
(`engine.pack.fw_streaming_graph.StreamingGraph`).

``test_fw_streaming_graph.py`` only runs against a real, install-gated
``streaming_graph.core`` -- so the DS2 variant of this parser has ~0% CI
coverage. The on-disk layout is a plain, fully-specified struct (documented
in the module's own docstring and in ``.memories/ds2-streaming-graph.md``),
with no encryption and no external decoder dependency, so it is directly
synthesizable -- same technique as ``test_fixtures_fw_streaming_graph.py``.

Builds one minimal-but-non-trivial DS2-variant StreamingGraphResource body
(two archive files, two locators, two spans, one group with reserved_ds2,
one object locator, one trailing UUID) entirely by hand and runs the REAL,
un-modified ``StreamingGraph`` parser over it.
"""
import struct

import numpy as np
import pytest

from deciwaves.engine.pack.fw_streaming_graph import (
    STREAMING_GRAPH_RESOURCE,
    StreamingGraph,
    _GROUP_DTYPE_DS2,
    _OBJLOC_DTYPE,
    _SPAN_DTYPE,
)


def _array(u32_count, payload_bytes):
    return struct.pack("<I", u32_count) + payload_bytes


def _filename(name: str) -> bytes:
    b = name.encode("utf-8")
    return struct.pack("<II", len(b), 0) + b


def _build_ds2_streaming_graph_bytes(trailing_uuids_count=1, groups_count=1):
    object_uuid = bytes(range(16))
    is_packed = 1

    type_hashes = np.array([0x1111111111111111, 0x2222222222222222], dtype="<u8")
    type_table_data = (
        struct.pack("<IIIII", 0, 2, 2, 2, 1) + struct.pack("<HH", 0, 0)
    )

    link_table_id = 0
    link_table_size = 0

    locators_raw = np.array(
        [(1000 << 24) | 0, (2000 << 24) | 1], dtype="<u8"
    )

    array_table = np.array([], dtype="<u4")

    spans = np.array(
        [(0, 10, 0), (1, 20, 100)], dtype=_SPAN_DTYPE
    )

    # 16 DS2 fields: group_id, num_objects, group_size, sub_group_start,
    # sub_group_count, root_start, root_count, span_start, span_count,
    # type_start, type_count, link_start, link_size, locator_start,
    # locator_count, reserved_ds2
    if groups_count:
        groups = np.array(
            [(1, 2, 0, 0, 0, 0, 0, 0, 2, 0, 2, 0, 0, 0, 2, 0xDEAD)],
            dtype=_GROUP_DTYPE_DS2,
        )
    else:
        groups = np.array([], dtype=_GROUP_DTYPE_DS2)

    sub_groups = np.array([], dtype="<u4")
    root_uuids = np.array([], dtype="S16")
    root_indices = np.array([], dtype="<u4")

    files = _filename("cache:package/streaming_graph.core") + _filename("cache:package/prefabs.core")

    object_locators = np.array(
        [(bytes(range(16, 32)), 0, 0, 0, 500, 50)], dtype=_OBJLOC_DTYPE
    )

    pack_file_uncompressed_block_size = 0
    pack_file_max_compressed_block_size = 0

    trailing_bytes = b""
    if trailing_uuids_count > 0:
        tu_arr = np.array([bytes(range(32, 48))], dtype="S16")
        trailing_bytes = _array(trailing_uuids_count, tu_arr.tobytes())
    else:
        trailing_bytes = struct.pack("<I", 0)

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
        struct.pack("<I", 2) + files,
        struct.pack("<I", 0),
        struct.pack("<I", 0),
        _array(len(object_locators), object_locators.tobytes()),
        struct.pack("<II", pack_file_uncompressed_block_size, pack_file_max_compressed_block_size),
        trailing_bytes,
    ])

    header = struct.pack("<QI", STREAMING_GRAPH_RESOURCE, len(body))
    trailing_num_links = struct.pack("<I", 0)
    return header + body + trailing_num_links


def test_parses_ds2_variant():
    g = StreamingGraph(_build_ds2_streaming_graph_bytes())

    assert g.variant == "ds2"

    assert g.is_packed is True
    assert len(g.files) == 2
    assert g.files[0] == "cache:package/streaming_graph.core"
    assert g.file_index("cache:package/prefabs.core") == 1
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
    assert grp.reserved_ds2 == 0xDEAD
    assert g.group(grp.group_id) is grp

    assert len(g.object_locators) == 1
    ol = g.object_locators[0]
    assert ol.uuid == bytes(range(16, 32))
    assert ol.file_index == 0 and ol.offset == 500 and ol.length == 50

    assert list(g.type_table) == [0x1111111111111111, 0x1111111111111111]

    assert g.pack_file_uncompressed_block_size == 0
    assert g.pack_file_max_compressed_block_size == 0

    assert len(g.trailing_uuids) == 1
    assert bytes(g.trailing_uuids[0]) == bytes(range(32, 48))


def test_ds2_empty_trailing_uuids():
    g = StreamingGraph(_build_ds2_streaming_graph_bytes(trailing_uuids_count=0))
    assert g.variant == "ds2"
    assert len(g.trailing_uuids) == 0


def test_ds2_fw_bytes_detect_fw_variant():
    """FW-format bytes must parse as fw variant (the try-FW-first path succeeds)."""
    from tests.test_fixtures_fw_streaming_graph import _build_streaming_graph_bytes as _build_fw
    g = StreamingGraph(_build_fw())
    assert g.variant == "fw"


def test_ds2_wrong_type_hash_raises():
    bad = struct.pack("<QI", 0xDEADBEEFDEADBEEF, 0)
    with pytest.raises(ValueError, match="StreamingGraphResource"):
        StreamingGraph(bad)


def test_ds2_inflated_size_raises_size_mismatch():
    good = _build_ds2_streaming_graph_bytes()
    type_hash, size = struct.unpack_from("<QI", good, 0)
    inflated = struct.pack("<QI", type_hash, size + 4) + good[12:]
    with pytest.raises(ValueError, match="not size-exact"):
        StreamingGraph(inflated)


def test_ds2_zero_groups_still_parses_as_ds2():
    """Zero-group DS2 graph must select ds2 variant — the FW attempt is not
    size-exact (it skips the trailing UUIDs), so the loop must fall through."""
    g = StreamingGraph(_build_ds2_streaming_graph_bytes(groups_count=0, trailing_uuids_count=1))
    assert g.variant == "ds2"
    assert len(g.groups) == 0
    assert len(g.trailing_uuids) == 1
    assert bytes(g.trailing_uuids[0]) == bytes(range(32, 48))


def test_ds2_all_variants_fail_message():
    """Genuinely corrupt bytes still raise, and the message names both variants."""
    corrupt = struct.pack("<QI", STREAMING_GRAPH_RESOURCE, 0)
    with pytest.raises(ValueError, match="FW and DS2") as excinfo:
        StreamingGraph(corrupt)
    msg = str(excinfo.value)
    assert "fw" in msg
    assert "ds2" in msg
