# tests/test_build_catalog.py
from deciwaves.games.ds.catalog import select_core_paths, classify
from deciwaves.engine.catalog_io import (
    done_core_paths, processed_core_paths, prune_incomplete_rows, CSV_COLUMNS,
)
import csv


def _write_csv_rows(path, core_paths):
    """Write one minimal CSV row per entry in *core_paths* (duplicates allowed, to
    simulate a multi-line core)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for i, cp in enumerate(core_paths):
            w.writerow({c: "" for c in CSV_COLUMNS} | {"core_path": cp, "line_index": i})


def _write_processed(path, core_paths):
    path.write_text("".join(cp + "\n" for cp in core_paths), encoding="utf-8")

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


# ---------------------------------------------------------------------------
# Issue #21: sidecar must be the SOLE resume authority.
#
# Rows are written per-line but the CSV is only flush()-ed once a core finishes
# (see games/ds/catalog.py, games/hzd/catalog.py); the processed sidecar is written
# strictly *after* all of a core's rows. A crash mid-core -- after some rows made it
# into the CSV's buffer but before the core's sidecar line is written -- leaves
# partial rows in the CSV for a core the sidecar never recorded as done. Under the
# old "CSV union sidecar" authority (see test_resume_covers_zero_row_and_failed_cores
# above), those partial rows alone were enough to mark the core done, silently
# dropping the rest of its lines forever. prune_incomplete_rows() is the fix: it
# drops any CSV row whose core is absent from the sidecar, so the sidecar is the
# only thing that decides "done" and a crashed core reruns from a clean slate.
# ---------------------------------------------------------------------------

def test_prune_incomplete_rows_drops_rows_for_cores_missing_from_sidecar(tmp_path):
    csv_path = tmp_path / "catalog.csv"
    proc_path = tmp_path / "catalog-processed.txt"
    # "done/core/sentences" finished normally: 2 rows, sidecar written.
    # "crashed/core/sentences" flushed 1 partial row (of what would've been more)
    # right before the crash; its sidecar line never got written.
    _write_csv_rows(csv_path, [
        "done/core/sentences", "done/core/sentences", "crashed/core/sentences",
    ])
    _write_processed(proc_path, ["done/core/sentences"])

    dropped = prune_incomplete_rows(str(csv_path), str(proc_path))

    assert dropped == 1
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["core_path"] for r in rows] == ["done/core/sentences", "done/core/sentences"]


def test_prune_incomplete_rows_keeps_processed_core_rows_intact(tmp_path):
    """Rows for cores the sidecar confirms are done must survive pruning unchanged."""
    csv_path = tmp_path / "catalog.csv"
    proc_path = tmp_path / "catalog-processed.txt"
    _write_csv_rows(csv_path, ["a/sentences", "b/sentences", "b/sentences"])
    _write_processed(proc_path, ["a/sentences", "b/sentences"])

    dropped = prune_incomplete_rows(str(csv_path), str(proc_path))

    assert dropped == 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["core_path"] for r in rows] == ["a/sentences", "b/sentences", "b/sentences"]


def test_prune_incomplete_rows_noop_on_clean_resume(tmp_path):
    """A clean resume (no crashed cores) must not rewrite the CSV at all -- pruning
    should not introduce a new partial-write window on the common, non-buggy path."""
    csv_path = tmp_path / "catalog.csv"
    proc_path = tmp_path / "catalog-processed.txt"
    _write_csv_rows(csv_path, ["a/sentences"])
    # sidecar also covers a zero-row core, which has no CSV row at all -- still clean.
    _write_processed(proc_path, ["a/sentences", "zero/row/sentences"])
    before = csv_path.read_bytes()

    dropped = prune_incomplete_rows(str(csv_path), str(proc_path))

    assert dropped == 0
    assert csv_path.read_bytes() == before


def test_prune_incomplete_rows_missing_csv_is_noop(tmp_path):
    proc_path = tmp_path / "catalog-processed.txt"
    _write_processed(proc_path, ["a/sentences"])
    assert prune_incomplete_rows(str(tmp_path / "missing.csv"), str(proc_path)) == 0


def test_sidecar_is_sole_resume_authority_after_prune(tmp_path):
    """End-to-end regression for the silent-row-loss bug: before the fix, resume used
    done_core_paths(csv) | processed_core_paths(processed) -- a union where the crashed
    core's partial CSV rows alone marked it done. After prune_incomplete_rows() runs,
    the sidecar alone must decide "done", and the crashed core must come back as
    "todo" so its lines get re-parsed instead of silently staying incomplete forever."""
    csv_path = tmp_path / "catalog.csv"
    proc_path = tmp_path / "catalog-processed.txt"
    _write_csv_rows(csv_path, ["done/core/sentences", "crashed/core/sentences"])
    _write_processed(proc_path, ["done/core/sentences"])

    # The old union authority wrongly considered the crashed core done:
    old_done = done_core_paths(str(csv_path)) | processed_core_paths(str(proc_path))
    assert "crashed/core/sentences" in old_done

    prune_incomplete_rows(str(csv_path), str(proc_path))
    done = processed_core_paths(str(proc_path))  # sole authority, post-fix

    assert done == {"done/core/sentences"}
    paths = ["done/core/sentences", "crashed/core/sentences", "new/core/sentences"]
    todo = [p for p in paths if p not in done]
    assert todo == ["crashed/core/sentences", "new/core/sentences"]
