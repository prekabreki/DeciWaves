"""Fast-path English-audio resolver: arithmetic locator pairing for
"arithmetically clean" groups (locator_count == 12*lssr_count), sidestepping the
object walk. Validated against the walk-based GroupReader oracle and against the
exact retail line count. Skips when the FW install / odradek types.json is absent.
"""
import os

import pytest

from deciwaves.engine.pack.fw_streaming_graph import StreamingGraph
from deciwaves.engine.pack.fw_stream import FwStreamStore
from deciwaves.engine.pack.fw_rtti import TypeRegistry
from deciwaves.engine.pack.fw_object_reader import GroupReader, read_group_spans
from deciwaves.engine.pack.fw_fast_extract import (
    iter_english_lines, english_file_indices, FastLine)

TYPES_JSON = os.path.join("vendor", "odradek", "odradek-game-hfw",
                          "src", "main", "resources", "types.json")

# Retail Horizon Forbidden West CE, validated 2026-06-27 (scratchpad analysis):
# the fast path resolves exactly this many English clips arithmetically, across
# all three English streams -- base part-0 (54,435) + base part-1 (2,834) +
# Burning Shores DLC (3,948).
EXPECTED_EN_LINES = 61217
EXPECTED_EN_FILES = {15, 16, 101}  # en/01.00, en/01.01, dlc/en/01.00


@pytest.fixture
def fw_graph(fw_package_dir):
    return StreamingGraph.from_file(
        os.path.join(str(fw_package_dir), "streaming_graph.core"))


def test_english_file_indices_include_base_parts_and_dlc(fw_graph):
    assert english_file_indices(fw_graph) == EXPECTED_EN_FILES


def test_fast_path_resolves_expected_line_count(fw_graph):
    lines = list(iter_english_lines(fw_graph))
    assert len(lines) == EXPECTED_EN_LINES
    en = english_file_indices(fw_graph)
    assert all(ln.locator.file_index in en for ln in lines)
    # all three streams are represented (DLC + base overflow not dropped)
    assert {ln.locator.file_index for ln in lines} == EXPECTED_EN_FILES
    assert len({ln.line_id for ln in lines}) == len(lines)  # unique ids


def test_fast_path_matches_walk_oracle(fw_package_dir, fw_graph):
    """For a sample of small arith-clean groups, the fast path's English locator
    for each LSSR must equal the one the authoritative object walk resolves."""
    if not os.path.isfile(TYPES_JSON):
        pytest.skip("odradek types.json not present")
    g = fw_graph
    gr = GroupReader(g, TypeRegistry(TYPES_JSON))
    store = FwStreamStore(str(fw_package_dir), g.files)

    by_group: dict[int, list[FastLine]] = {}
    for ln in iter_english_lines(g):
        by_group.setdefault(ln.group_id, []).append(ln)

    checked = 0
    for grp in g.groups:
        if checked >= 5:
            break
        if grp.group_id not in by_group or grp.num_objects > 64:
            continue
        try:
            objs = gr.read_group(grp, read_group_spans(g, store, grp))
        except Exception:
            continue  # group hits an unported extra-binary layout; skip sample
        walk_locs = [
            o.fields["LocalizedDataSources"][0]["StreamingDataSource"].get("_locator")
            for o in objs if o.type_name == "LocalizedSimpleSoundResource"
        ]
        for ln in by_group[grp.group_id]:
            assert walk_locs[ln.lssr_index] == ln.locator, (
                f"group {grp.group_id} k={ln.lssr_index}: "
                f"walk={walk_locs[ln.lssr_index]} fast={ln.locator}")
        checked += 1
    assert checked > 0, "no arith-clean sample group walked cleanly"
