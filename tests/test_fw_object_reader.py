"""Generic FW RTTI group reader: resolves a dialogue line's English audio
locator by positional pairing, and parses LocalizedTextResource subtitles.
Skips when the FW install or odradek's types.json is absent."""
import os
import struct

import pytest

from deciwaves.engine.pack.fw_streaming_graph import Group, StreamingGraph
from deciwaves.engine.pack.fw_stream import FwStreamStore
from deciwaves.engine.pack.fw_rtti import TypeRegistry, type_hash
from deciwaves.engine.pack.fw_object_reader import (
    CAPTURE_ALL, GroupReader, read_group_spans, _Cur,
)

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


def _mk_group(type_count=0, span_count=0, locator_count=0, group_id=1):
    """A synthetic :class:`Group` with everything zeroed except the slice
    bounds a test cares about (all tables start at offset 0)."""
    return Group(
        group_id=group_id, num_objects=type_count, group_size=0,
        sub_group_start=0, sub_group_count=0, root_start=0, root_count=0,
        span_start=0, span_count=span_count, type_start=0, type_count=type_count,
        link_start=0, link_size=0, locator_start=0, locator_count=locator_count,
    )


class _FakeGraph:
    """Stand-in for :class:`StreamingGraph` exposing only what
    ``read_group``/``scan_group`` touch: sliceable ``type_table``/``locators``."""
    def __init__(self, type_table=(), locators=()):
        self.type_table = list(type_table)
        self.locators = list(locators)


class _ByteCompoundReg:
    """One-attr compound 'Byte' (a single ``uint8`` field): lets a test walk a
    known number of bytes per top-level group object without any
    StreamingDataSource machinery. Every type-table hash resolves to 'Byte'."""
    _TYPES = {
        "Byte": {"kind": "compound", "attrs": (("v", "uint8"),)},
        "uint8": {"kind": "atom", "base_type": "uint8"},
    }

    def name_for_hash(self, h):
        return "Byte"

    def kind(self, t):
        return self._TYPES[t]["kind"]

    def define(self, t):
        return self._TYPES[t]

    def ordered_attrs(self, t):
        return self._TYPES[t]["attrs"]


class _SdsStubReg:
    """A single 'StreamingDataSource' compound (Channel: uint8, Length:
    uint32) — enough to make ``_fill_compound`` consider it a *valid* SDS and
    try to consume a locator."""
    _TYPES = {
        "StreamingDataSource": {"kind": "compound",
                                "attrs": (("Channel", "uint8"), ("Length", "uint32"))},
        "uint8": {"kind": "atom", "base_type": "uint8"},
        "uint32": {"kind": "atom", "base_type": "uint32"},
    }

    def name_for_hash(self, h):
        return "StreamingDataSource"

    def kind(self, t):
        return self._TYPES[t]["kind"]

    def define(self, t):
        return self._TYPES[t]

    def ordered_attrs(self, t):
        return self._TYPES[t]["attrs"]


def test_read_group_span_blob_count_mismatch_raises_valueerror():
    """A caller passing the wrong number of span blobs is a programming error,
    not a walk desync — but it must surface as an actionable ValueError, not
    an ``assert`` that silently vanishes under ``-O``."""
    gr = GroupReader(graph=_FakeGraph(), registry=None)
    group = _mk_group(type_count=0, span_count=2)
    with pytest.raises(ValueError, match="span blobs"):
        gr.read_group(group, span_blobs=[b""])  # 1 given, 2 declared


def test_scan_group_span_blob_count_mismatch_raises_valueerror():
    gr = GroupReader(graph=_FakeGraph(), registry=None)
    group = _mk_group(type_count=0, span_count=2)
    with pytest.raises(ValueError, match="span blobs"):
        gr.scan_group(group, span_blobs=[b""])  # 1 given, 2 declared


def test_read_group_object_overflow_raises_valueerror():
    """Span bytes describing more objects than the type table declares is a
    walk desync. It must raise ValueError, not a bare IndexError."""
    gr = GroupReader(graph=_FakeGraph(), registry=None)
    group = _mk_group(type_count=0, span_count=1)  # no objects allocated...
    with pytest.raises(ValueError, match="walk desync"):
        gr.read_group(group, span_blobs=[b"\x00"])  # ...but a span has a byte


def test_scan_group_object_overflow_raises_valueerror():
    gr = GroupReader(graph=_FakeGraph(), registry=None)
    group = _mk_group(type_count=0, span_count=1)
    with pytest.raises(ValueError, match="walk desync"):
        gr.scan_group(group, span_blobs=[b"\x00"])


def test_read_group_locator_exhausted_raises_valueerror():
    """A valid StreamingDataSource (Channel != 0xFF, Length > 0) must consume
    a locator; if the locator table is exhausted that's a walk desync and
    must raise ValueError, not a bare StopIteration (a PEP 479 hazard through
    any generator caller)."""
    graph = _FakeGraph(type_table=[0], locators=[])  # zero locators available
    gr = GroupReader(graph=graph, registry=_SdsStubReg())
    group = _mk_group(type_count=1, span_count=1, locator_count=0)
    blob = struct.pack("<B", 1) + struct.pack("<I", 5)  # Channel=1, Length=5: valid
    with pytest.raises(ValueError, match="locator"):
        gr.read_group(group, span_blobs=[blob])


def test_scan_group_surfaces_incomplete_walk():
    """The production bug: scan_group silently accepted a truncated walk that
    read_group already rejects. Two objects are declared but the second span
    is empty (never fills object 1) -- must raise like read_group does."""
    graph = _FakeGraph(type_table=[0, 0], locators=[])
    gr = GroupReader(graph=graph, registry=_ByteCompoundReg())
    group = _mk_group(type_count=2, span_count=2, locator_count=0)
    blobs = [b"\x00", b""]  # second span is empty: object 1 never gets filled

    with pytest.raises(ValueError, match="filled 1 of 2"):
        gr.scan_group(group, blobs)

    # read_group already rejects the identical short walk (parity check).
    with pytest.raises(ValueError, match="filled 1 of 2"):
        gr.read_group(group, blobs)


def test_scan_group_capture_all_materialises_every_object():
    """CAPTURE_ALL is additive: the default/explicit-tuple call keeps behaving
    exactly as before (only named types captured); CAPTURE_ALL opts a caller
    into getting every walked object back, fully materialised."""
    graph = _FakeGraph(type_table=[0, 0], locators=[])
    gr = GroupReader(graph=graph, registry=_ByteCompoundReg())
    group = _mk_group(type_count=2, span_count=1, locator_count=0)
    blob = b"\x01\x02"  # one byte per 'Byte' object

    default = gr.scan_group(group, [blob])
    assert default == []  # 'Byte' isn't in the default capture set

    everything = gr.scan_group(group, [blob], capture=CAPTURE_ALL)
    assert [(o.type_name, o.fields) for o in everything] == [
        ("Byte", {"v": 1}), ("Byte", {"v": 2}),
    ]


def test_resolve_atom_cycle_guard_terminates():
    """A (pathological) 2-hop atom cycle must terminate via the cycle guard
    instead of looping forever -- the fold's whole point is that all 4
    call sites now share this guard, not just _read_atom."""
    class _CyclicReg:
        def kind(self, t):
            return "atom"

        def define(self, t):
            return {"A": {"base_type": "B"}, "B": {"base_type": "A"}}[t]

    gr = GroupReader(graph=_FakeGraph(), registry=_CyclicReg())
    resolved = gr._resolve_atom("A")
    assert resolved in ("A", "B")  # terminates; exact stop point is incidental

    # cached: a second call for the same name must return the same result.
    assert gr._resolve_atom("A") == resolved


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
