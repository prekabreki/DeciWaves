"""StreamingGraphResource parser — verified byte-exact against the retail
Forbidden West install. Skips when the install is absent."""
from engine.pack.fw_streaming_graph import StreamingGraph, STREAMING_GRAPH_RESOURCE


def test_parses_size_exact_and_known_tables(fw_streaming_graph_bytes):
    g = StreamingGraph(fw_streaming_graph_bytes)

    # The whole body deserialised cleanly (size-exact assert is inside __init__).
    # Cross-check the headline facts established empirically.
    assert g.is_packed is True

    # 127 archive files; the two English dialogue stores we extract from.
    assert len(g.files) == 127
    assert g.files[g.file_index("en/package.01.00.core.stream")].endswith(
        "en/package.01.00.core.stream"
    )
    # Burning Shores DLC English dialogue is also indexed.
    assert any(f.endswith("dlc/en/package.01.00.core.stream") for f in g.files)

    # Every locator/span points at a real file slot (vectorised check).
    assert len(g.locators) and len(g.spans)
    nfiles = len(g.files)
    assert g.locators.file_index.min() >= 0 and g.locators.file_index.max() < nfiles
    assert g.spans.file_index.min() >= 0 and g.spans.file_index.max() < nfiles

    # Groups slice into the global tables without going out of bounds.
    assert g.groups
    for grp in g.groups:
        assert grp.locator_start + grp.locator_count <= len(g.locators)
        assert grp.span_start + grp.span_count <= len(g.spans)
        assert grp.type_count == grp.num_objects  # one type slot per object
        assert g.group(grp.group_id) is grp

    # Object locators (UUID -> storage) parsed with valid file slots.
    assert len(g.object_locators)
    assert g.object_locators.file_index.min() >= 0
    assert g.object_locators.file_index.max() < nfiles
    assert len(g.object_locators[0].uuid) == 16


def test_type_hash_constant():
    # murmur3_x64_128(seed=42, "00000001_StreamingGraphResource").low64
    assert STREAMING_GRAPH_RESOURCE == 0x929D7AF6A30CD1C5
