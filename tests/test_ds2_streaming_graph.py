"""StreamingGraphResource parser on DS2's retail streaming_graph.core --
the same resource type as FW but with a 68-byte group stride and a trailing
GGUUID array. Skips when the DS2 install is absent."""
from deciwaves.engine.pack.fw_streaming_graph import StreamingGraph


def test_parses_retail_shape_and_ds2_invariants(ds2_streaming_graph_bytes):
    g = StreamingGraph(ds2_streaming_graph_bytes)

    # The whole body deserialised cleanly (size-exact assert is inside __init__),
    # and the DS2 layout, not the FW one, was the one that landed.
    assert g.variant == "ds2"

    # Headline counts established empirically (see .memories/ds2-streaming-graph.md).
    assert len(g.locators) == 369_397
    assert len(g.spans) == 79_317
    assert len(g.groups) == 79_317
    assert len(g.sub_groups) == 553_802
    assert len(g.root_uuids) == 50_513
    assert len(g.root_indices) == 50_513
    assert len(g.files) == 241
    assert len(g.object_locators) == 45_345
    assert len(g.trailing_uuids) == 444

    # DS2-specific layout deltas: the appended u32 is reserved (zero in every
    # retail record) and the link_size column sums to the exact on-disk size of
    # streaming_links.stream.
    assert all(grp.reserved_ds2 == 0 for grp in g.groups)
    assert sum(grp.link_size for grp in g.groups) == 30_226_923
