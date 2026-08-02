"""DS2 dialogue-line enumeration (``games.ds2.lines``).

The install-gated tests assert the exact retail census (line count, distinct
stream files, unique ids, on-disk index count) against a real install; the
synthetic-graph tests prove the on-disk filter and the empty-set failure path
on any machine, with no DS2 install required.
"""
import numpy as np
import pytest

from deciwaves.engine.pack.fw_rtti import type_hash
from deciwaves.engine.pack.fw_streaming_graph import Group, StreamingGraph, _LocatorView
from deciwaves.games.ds2.lines import (
    VOICE_PACKAGE_NN, ds2_stream_indices, iter_ds2_lines, language_cycles,
)

# Retail DS2 census, measured 2026-08-02 (issue #391; see
# .memories/ds2-audio-binding.md). The line count rose from 8,776 to 16,953 when
# enumeration stopped requiring a group to be arithmetically clean -- 9 stream
# files now contribute, where 7 did before (`remain` and `l800_fra` were the two
# that yielded nothing).
EXPECTED_DS2_LINES = 16953
EXPECTED_DS2_STREAM_FILES = 9
EXPECTED_DS2_INDICES = 142
EXPECTED_DS2_FILES = 241

_LSSR = type_hash("LocalizedSimpleSoundResource")


class _FakeGraph:
    """Stand-in for a StreamingGraph -- only ``.files`` is needed here."""

    def __init__(self, files):
        self.files = files


def _voice_files(*regions):
    """``graph.files`` holding a full 12-package language cycle per region."""
    out = []
    for r in regions:
        prefix = f"{r}/" if r else ""
        out += [f"cache:package/{prefix}package.{nn}.00.core.stream"
                for nn in VOICE_PACKAGE_NN]
    return out


def _graph(files, *, locators, type_hashes, group_id=7, locator_start=0):
    """A StreamingGraph stand-in carrying one group, built from real types.

    *locators* is a list of ``(file_index, offset)``; *type_hashes* the group's
    slice of the type table.
    """
    g = _FakeGraph(files)
    g.locators = _LocatorView(
        np.array([fi for fi, _ in locators], dtype="<u4"),
        np.array([off for _, off in locators], dtype="<u8"),
    )
    g.type_table = np.array(type_hashes, dtype="<u8")
    g.groups = [Group(group_id=group_id, num_objects=0, group_size=0,
                      sub_group_start=0, sub_group_count=0, root_start=0,
                      root_count=0, span_start=0, span_count=0,
                      type_start=0, type_count=len(type_hashes),
                      link_start=0, link_size=0,
                      locator_start=locator_start, locator_count=len(locators))]
    return g


def _cycle(base_file=0, offset0=1000):
    """One 12-locator language block; slot 0 (English) gets *offset0*."""
    return [(base_file + s, offset0 + s) for s in range(12)]


def _plant(tmp_path, files, keep):
    """Create the *keep* subset of *files* on disk under *tmp_path*."""
    for i in keep:
        rel = files[i][len("cache:package/"):]
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")


# --- install-gated retail census -------------------------------------------

def test_ds2_lines_retail_census(ds2_streaming_graph_bytes, ds2_package_dir):
    graph = StreamingGraph(ds2_streaming_graph_bytes)
    lines = list(iter_ds2_lines(graph, ds2_package_dir))
    assert len(lines) == EXPECTED_DS2_LINES
    assert len({ln.locator.file_index for ln in lines}) == EXPECTED_DS2_STREAM_FILES
    assert len({ln.line_id for ln in lines}) == len(lines)  # unique ids


def test_ds2_stream_indices_retail_census(ds2_streaming_graph_bytes, ds2_package_dir):
    graph = StreamingGraph(ds2_streaming_graph_bytes)
    assert len(ds2_stream_indices(graph, ds2_package_dir)) == EXPECTED_DS2_INDICES
    assert len(graph.files) == EXPECTED_DS2_FILES


# --- install-free synthetic graph: on-disk filter + empty-set failure ------

def test_ds2_stream_indices_keeps_only_files_on_disk(tmp_path):
    graph = _FakeGraph([
        "cache:package/root/package.01.00.core.stream",        # present -> kept
        "cache:package/l200_aus/package.39.00.core.stream",    # present -> kept
        "cache:package/l100_mex/package.42.00.core.stream",    # absent  -> dropped
        "cache:package/streaming_graph.core",                  # absent  -> dropped
        "en/package.01.00.core.stream",                        # no prefix, absent -> dropped
    ])
    (tmp_path / "root").mkdir()
    (tmp_path / "root" / "package.01.00.core.stream").write_bytes(b"x")
    (tmp_path / "l200_aus").mkdir()
    (tmp_path / "l200_aus" / "package.39.00.core.stream").write_bytes(b"x")

    assert ds2_stream_indices(graph, tmp_path) == {0, 1}


def test_iter_ds2_lines_fails_loudly_when_no_file_on_disk(tmp_path):
    """A wrong package dir yields an empty on-disk set -> iter_english_lines
    raises instead of silently yielding zero lines."""
    graph = _FakeGraph(["cache:package/l200_aus/package.39.00.core.stream"])
    with pytest.raises(KeyError):
        list(iter_ds2_lines(graph, tmp_path))


# --- issue #391: the language cycle, and dialogue in "unclean" groups ------

def test_language_cycles_derives_one_cycle_per_region():
    """A region contributes a cycle only if all 12 voice packages are present."""
    files = _voice_files("", "l200_aus")
    files.append("cache:package/l800_fra/package.01.00.core.stream")  # 1 of 12
    files.append("cache:package/l200_aus/package.99.00.core.stream")  # not a slot
    cycles = language_cycles(_FakeGraph(files))
    assert cycles == {tuple(range(0, 12)), tuple(range(12, 24))}


def test_language_cycles_rejects_a_region_one_package_short():
    """Boundary: 11 of 12 is not a cycle. An "almost complete" region must
    contribute nothing rather than a short/renumbered window -- a cycle with a
    hole would shift every slot after it and resolve English to another
    language's stream."""
    files = [f for f in _voice_files("l200_aus")
             if not f.endswith("package.18.00.core.stream")]
    assert len(files) == 11
    assert language_cycles(_FakeGraph(files)) == set()


def test_iter_ds2_lines_reads_dialogue_after_a_non_dialogue_prefix(tmp_path):
    """Issue #391 root cause: a group whose locator slice is NOT exactly
    ``12 * n_lssr`` still holds ordinary 12-language dialogue blocks -- here
    behind three unrelated locators. The old arith-clean rule rejected the whole
    group; every one of these lines was silently dropped."""
    files = _voice_files("") + ["cache:package/misc.core.stream"]
    _plant(tmp_path, files, keep=[0])          # only English (slot 0) on disk
    junk = [(12, 5), (12, 6), (12, 7)]         # the non-dialogue prefix
    graph = _graph(files, locators=junk + _cycle(0, 1000) + _cycle(0, 2000),
                   type_hashes=[_LSSR, _LSSR, 0xDEAD])

    lines = list(iter_ds2_lines(graph, tmp_path))

    assert [ln.line_id for ln in lines] == ["g7_0000", "g7_0001"]
    assert [ln.locator.offset for ln in lines] == [1000, 2000]
    assert {ln.locator.file_index for ln in lines} == {0}


def test_iter_ds2_lines_numbering_is_unchanged_for_a_clean_group(tmp_path):
    """Stability guard: for an arithmetically clean group the new scan must
    produce the SAME ids and locators as the old ``base + 12*k`` arithmetic --
    otherwise every already-extracted clip's line_id would shift and the retail
    manifest, its WAVs and its ASR transcripts would all be invalidated."""
    files = _voice_files("")
    _plant(tmp_path, files, keep=[0])
    graph = _graph(files, locators=_cycle(0, 1000) + _cycle(0, 2000) + _cycle(0, 3000),
                   type_hashes=[_LSSR] * 3)

    lines = list(iter_ds2_lines(graph, tmp_path))

    assert [ln.line_id for ln in lines] == ["g7_0000", "g7_0001", "g7_0002"]
    assert [ln.lssr_index for ln in lines] == [0, 1, 2]
    assert [ln.locator.offset for ln in lines] == [1000, 2000, 3000]


def test_iter_ds2_lines_ignores_cycles_in_groups_holding_no_dialogue(tmp_path):
    """False-positive guard. 244 retail groups carry a 12-window that matches a
    language cycle while holding no ``LocalizedSimpleSoundResource`` at all (486
    windows). Requiring the group to declare dialogue is what excludes them."""
    files = _voice_files("")
    _plant(tmp_path, files, keep=[0])
    graph = _graph(files, locators=_cycle(0, 1000), type_hashes=[0xDEAD, 0xBEEF])

    assert list(iter_ds2_lines(graph, tmp_path)) == []


def test_iter_ds2_lines_skips_a_block_whose_english_stream_is_absent(tmp_path):
    """Only slot 0's stream ships on an English install; a block whose slot-0
    file is missing is skipped, but it still consumes an lssr_index so the
    surviving ids keep their retail numbering."""
    files = _voice_files("", "l800_fra")
    _plant(tmp_path, files, keep=[0])          # region 2's English NOT on disk
    graph = _graph(files, locators=_cycle(12, 1000) + _cycle(0, 2000),
                   type_hashes=[_LSSR, _LSSR])

    lines = list(iter_ds2_lines(graph, tmp_path))

    assert [ln.line_id for ln in lines] == ["g7_0001"]
    assert lines[0].locator.offset == 2000
