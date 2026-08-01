"""DS2 dialogue-line enumeration (``games.ds2.lines``).

The install-gated tests assert the exact retail census (line count, distinct
stream files, unique ids, on-disk index count) against a real install; the
synthetic-graph tests prove the on-disk filter and the empty-set failure path
on any machine, with no DS2 install required.
"""
import pytest

from deciwaves.engine.pack.fw_streaming_graph import StreamingGraph
from deciwaves.games.ds2.lines import ds2_stream_indices, iter_ds2_lines

# Retail DS2 census, measured 2026-08-01 (see .memories/ds2-audio-binding.md):
# slot-0 (on-disk) dialogue resolves to exactly these counts.
EXPECTED_DS2_LINES = 8776
EXPECTED_DS2_STREAM_FILES = 7
EXPECTED_DS2_INDICES = 142
EXPECTED_DS2_FILES = 241


class _FakeGraph:
    """Stand-in for a StreamingGraph -- only ``.files`` is needed here."""

    def __init__(self, files):
        self.files = files


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
