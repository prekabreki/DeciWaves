"""Generic FW RTTI group reader: resolves a dialogue line's English audio
locator by positional pairing, and parses LocalizedTextResource subtitles.
Skips when the FW install or odradek's types.json is absent."""
import os
import struct

import pytest

from deciwaves.engine.pack.fw_streaming_graph import StreamingGraph
from deciwaves.engine.pack.fw_stream import FwStreamStore
from deciwaves.engine.pack.fw_rtti import TypeRegistry, type_hash
from deciwaves.engine.pack.fw_object_reader import GroupReader, read_group_spans, _Cur

TYPES_JSON = os.path.join("vendor", "odradek", "odradek-game-hfw",
                          "src", "main", "resources", "types.json")
LSSR = type_hash("LocalizedSimpleSoundResource")


class _StubReg:
    """Minimal registry: a container 'Vec' of an empty compound 'Foo'."""
    def define(self, t):
        return {"Vec": {"type": "Array", "item_type": "Foo"}}[t]

    def kind(self, t):
        return {"Vec": "container", "Foo": "compound"}[t]

    def ordered_attrs(self, t):
        return []  # Foo is a zero-byte compound


def test_bogus_container_count_raises_not_hangs():
    """A walk desync reads an implausible container count (more items than there
    are bytes left). It must raise immediately (caught fail-soft) — never loop."""
    gr = GroupReader(graph=None, registry=_StubReg())
    cur = _Cur(struct.pack("<I", 1_000_000_000), 0, 4)  # count=1e9, 0 bytes left
    with pytest.raises(ValueError):
        gr._advance_container("Vec", cur)


def test_bogus_container_count_raises_in_read_path():
    gr = GroupReader(graph=None, registry=_StubReg())
    cur = _Cur(struct.pack("<I", 1_000_000_000), 0, 4)
    with pytest.raises(ValueError):
        gr._read_container("Vec", cur)


@pytest.fixture
def fw_reader(fw_package_dir):
    if not os.path.isfile(TYPES_JSON):
        pytest.skip("odradek types.json not present")
    g = StreamingGraph.from_file(os.path.join(str(fw_package_dir), "streaming_graph.core"))
    reg = TypeRegistry(TYPES_JSON)
    return g, GroupReader(g, reg), FwStreamStore(str(fw_package_dir), g.files)


def _clean_group(g):
    """First group with exactly one English locator and a sound resource."""
    en = g.file_index("en/package.01.00.core.stream")
    for grp in g.groups:
        locs = g.locators[grp.locator_start:grp.locator_start + grp.locator_count]
        if sum(1 for l in locs if l.file_index == en) != 1:
            continue
        slc = g.type_table[grp.type_start:grp.type_start + grp.type_count]
        if (slc == LSSR).any():
            return grp
    return None


def test_reader_resolves_english_locator(fw_reader):
    g, gr, store = fw_reader
    en = g.file_index("en/package.01.00.core.stream")
    grp = _clean_group(g)
    assert grp is not None
    blobs = read_group_spans(g, store, grp)

    objs = gr.read_group(grp, blobs)  # full read is size-exact (asserted inside)
    lssr = [o for o in objs if o.type_name == "LocalizedSimpleSoundResource"]
    assert lssr
    sds = lssr[0].fields["LocalizedDataSources"][0]["StreamingDataSource"]
    loc = sds.get("_locator")
    assert loc is not None and loc.file_index == en
    # the resolved clip is a real RIFF/WAVE at that offset
    clip = store.read_riff_clip(en, loc.offset)
    assert clip[:4] == b"RIFF" and clip[8:12] == b"WAVE"
    assert sds["Length"] == len(clip)  # inline A == clip bytes


def test_scan_matches_full_read(fw_reader):
    g, gr, store = fw_reader
    grp = _clean_group(g)
    blobs = read_group_spans(g, store, grp)
    full = gr.read_group(grp, blobs)
    scan = gr.scan_group(grp, blobs)
    full_lssr = [o for o in full if o.type_name == "LocalizedSimpleSoundResource"]
    scan_lssr = [o for o in scan if o.type_name == "LocalizedSimpleSoundResource"]
    assert len(full_lssr) == len(scan_lssr)

    def en_loc(o):
        return o.fields["LocalizedDataSources"][0]["StreamingDataSource"].get("_locator")
    assert en_loc(full_lssr[0]) == en_loc(scan_lssr[0])


def test_localized_text_subtitle_parses(fw_reader):
    g, gr, store = fw_reader
    LTR = type_hash("LocalizedTextResource")
    # find a small group that has both a text resource and parses cleanly
    for grp in g.groups:
        slc = g.type_table[grp.type_start:grp.type_start + grp.type_count]
        if grp.num_objects > 200 or not (slc == LTR).any() or not (slc == LSSR).any():
            continue
        try:
            caps = gr.scan_group(grp, read_group_spans(g, store, grp))
        except Exception:
            continue
        texts = [o for o in caps if o.type_name == "LocalizedTextResource"]
        if texts and texts[0].fields.get("_texts"):
            t = texts[0].fields["_texts"]
            assert len(t) == 26  # 26 written languages
            assert isinstance(t[0], str)  # English at index 0
            return
    pytest.skip("no suitable text-bearing group found")
