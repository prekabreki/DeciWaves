"""Pin `BinArchive._find_chunk` behaviour across chunk-boundary cases (issue #50,
audit item M16): the linear per-read scan is replaced by a `bisect` floor-lookup
mirroring `DsarArchive._first_chunk`, and this test locks the *exact* index the
old linear scan returned so the swap is behaviour-preserving.

Subtlety this guards: the old scan uses an inclusive upper bound
(`ct[i].off <= offset <= ct[i+1].off`), so at an offset landing *exactly* on a
chunk start it returns the EARLIER chunk. That is `bisect_left(...) - 1`
semantics, NOT `DsarArchive`'s `bisect_right(...) - 1` (which would return the
later chunk at an exact boundary). A naive copy of dsar's bisect_right would
diverge here; the sweep below would catch it.
"""
import struct

import pytest

from deciwaves.engine.pack.bin_archive import BinArchive

# Reuse the byte-exact synthetic .bin builder the fixtures module already ships
# (pytest prepend import-mode puts tests/ on sys.path, so the sibling imports).
from test_fixtures_bin_archive import _write_bin_archive


def _linear_find_chunk(ct, offset):
    """Verbatim copy of the pre-M16 linear scan, as the equivalence oracle."""
    for i in range(len(ct)):
        if i + 1 >= len(ct):
            return i
        if ct[i].uncompressed_offset <= offset <= ct[i + 1].uncompressed_offset:
            return i
    return len(ct) - 1


# chunk starts 0 / 500 / 1500 / 3000; last chunk covers [3000, 4000). Uneven
# sizes so a bug that assumes uniform chunk length can't hide.
_CHUNKS = [
    (0, b"A" * 500),
    (500, b"B" * 1000),
    (1500, b"C" * 1500),
    (3000, b"D" * 1000),
]


@pytest.fixture
def arc(tmp_path):
    p = tmp_path / "find_chunk.bin"
    _write_bin_archive(p, [], _CHUNKS)
    a = BinArchive(str(p))
    a.open_index()
    return a


# Every reachable boundary flavour named in the brief: chunk-0 start, mid-chunk,
# each exact chunk start, one byte either side of a start, last-chunk start,
# mid-last, exact logical end, and past end. Offsets are always >= 0 and the
# first chunk starts at 0, so "before the first chunk" is unreachable here.
@pytest.mark.parametrize("offset", [
    0, 1, 250, 499, 500, 501, 750, 1499, 1500, 1501,
    2000, 2999, 3000, 3001, 3500, 3999, 4000, 5000,
])
def test_find_chunk_matches_linear_scan(arc, offset):
    assert arc._find_chunk(offset) == _linear_find_chunk(arc.chunk_table, offset)


def test_exact_chunk_start_returns_earlier_chunk(arc):
    # inclusive-upper-bound semantics: an offset on chunk 1's start resolves to
    # chunk 0, matching the old scan (and NOT dsar's bisect_right, which -> 1).
    assert arc._find_chunk(500) == 0
    assert arc._find_chunk(1500) == 1
    assert arc._find_chunk(3000) == 2


def test_mid_and_last_chunk(arc):
    assert arc._find_chunk(750) == 1        # mid-chunk
    assert arc._find_chunk(3500) == 3       # inside last chunk
    assert arc._find_chunk(10_000) == 3     # past end clamps to last chunk


def test_offsets_index_precomputed(arc):
    # M16 mirrors DsarArchive: a parallel offsets list, built once, drives the
    # bisect lookup instead of scanning the dataclass list per read.
    assert arc._offsets == [c.uncompressed_offset for c in arc.chunk_table]
    assert arc._offsets == [0, 500, 1500, 3000]
