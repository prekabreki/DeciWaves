# tests/test_build_catalog.py
from deciwaves.games.ds.catalog import select_core_paths, classify
from deciwaves.engine.catalog_io import done_core_paths, processed_core_paths, CSV_COLUMNS
import csv

# ---------------------------------------------------------------------------
# Task 2.3: profile-driven prefix tests
# ---------------------------------------------------------------------------

_SAMPLE_FILE_LIST = [
    "localized/sentences/ds_lines_cutscene/sq_cs04_s01650/sentences",
    "localized/sentences/ds_lines_terminal/lines_pr201/sentences",
    "localized/sentences/ds_ui/ds_common/simpletext",        # excluded (ui)
    "localized/sentences/voices/vr0010_sam/simpletext",       # excluded (voices)
    "localized/sentences/ds_lines_npc/lines_npc01/sentences",
    "levels/worlds/_l100_area01/tiles/x/lodlowres",           # excluded
]

_EXPECTED_PATHS = [
    "localized/sentences/ds_lines_cutscene/sq_cs04_s01650/sentences",
    "localized/sentences/ds_lines_terminal/lines_pr201/sentences",
    "localized/sentences/ds_lines_npc/lines_npc01/sentences",
]


def test_select_core_paths_uses_profile_prefixes():
    """select_core_paths driven by DS profile.core_prefixes produces identical results."""
    from deciwaves.games.ds.profile import build_profile
    profile = build_profile(data_dir=None, oodle=None)
    result = select_core_paths(_SAMPLE_FILE_LIST, profile.core_prefixes)
    assert result == _EXPECTED_PATHS


def test_classify_uses_profile_prefixes():
    """classify driven by DS profile.core_prefixes produces identical results."""
    from deciwaves.games.ds.profile import build_profile
    profile = build_profile(data_dir=None, oodle=None)
    assert classify(
        "localized/sentences/ds_lines_cutscene/sq_cs04_s01650/sentences",
        profile.core_prefixes
    ) == ("cutscene", "sq_cs04_s01650")
    assert classify(
        "localized/sentences/ds_lines_terminal/lines_pr201/sentences",
        profile.core_prefixes
    ) == ("terminal", "lines_pr201")


def test_select_filters_to_dialogue_sentences():
    lines = [
        "localized/sentences/ds_lines_cutscene/sq_cs04_s01650/sentences",
        "localized/sentences/ds_lines_terminal/lines_pr201/sentences",
        "localized/sentences/ds_ui/ds_common/simpletext",        # excluded (ui)
        "localized/sentences/voices/vr0010_sam/simpletext",       # excluded (voices)
        "localized/sentences/ds_lines_npc/lines_npc01/sentences",
        "levels/worlds/_l100_area01/tiles/x/lodlowres",           # excluded
    ]
    out = select_core_paths(lines)
    assert out == [
        "localized/sentences/ds_lines_cutscene/sq_cs04_s01650/sentences",
        "localized/sentences/ds_lines_terminal/lines_pr201/sentences",
        "localized/sentences/ds_lines_npc/lines_npc01/sentences",
    ]


def test_classify():
    assert classify("localized/sentences/ds_lines_cutscene/sq_cs04_s01650/sentences") == ("cutscene", "sq_cs04_s01650")
    assert classify("localized/sentences/ds_lines_terminal/lines_pr201/sentences") == ("terminal", "lines_pr201")


def test_done_core_paths(tmp_path):
    p = tmp_path / "catalog.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerow({c: "" for c in CSV_COLUMNS} | {"core_path": "a/b/sentences"})
    assert done_core_paths(str(p)) == {"a/b/sentences"}
    assert done_core_paths(str(tmp_path / "missing.csv")) == set()


def test_processed_core_paths(tmp_path):
    p = tmp_path / "catalog-processed.txt"
    p.write_text("a/b/sentences\nc/d/sentences\n\n", encoding="utf-8")
    assert processed_core_paths(str(p)) == {"a/b/sentences", "c/d/sentences"}
    assert processed_core_paths(str(tmp_path / "missing.txt")) == set()


def test_resume_covers_zero_row_and_failed_cores(tmp_path):
    # A core that parsed to zero rows (or hard-failed) writes no CSV row, so the
    # CSV alone re-runs it forever. The sidecar records it; the union marks it done.
    csv_path = tmp_path / "catalog.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerow({c: "" for c in CSV_COLUMNS} | {"core_path": "has/rows/sentences"})
    proc_path = tmp_path / "catalog-processed.txt"
    proc_path.write_text("has/rows/sentences\nzero/row/sentences\nfailed/core/sentences\n",
                         encoding="utf-8")
    done = done_core_paths(str(csv_path)) | processed_core_paths(str(proc_path))
    assert done == {"has/rows/sentences", "zero/row/sentences", "failed/core/sentences"}
