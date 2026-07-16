# tests/test_build_catalog.py
from deciwaves.games.ds.catalog import select_core_paths, classify
from deciwaves.engine.catalog_io import (
    done_core_paths, processed_core_paths, CSV_COLUMNS,
    write_core_paths_sidecar, read_core_paths_sidecar,
)
import csv
import pytest

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
# write_core_paths_sidecar / read_core_paths_sidecar (issue #31): lets a downstream
# stage (HZD's wem-metadata) reuse the core-path list a catalog stage's harvest
# already produced, instead of repeating a full-pack content scan.
# ---------------------------------------------------------------------------

def test_write_and_read_core_paths_sidecar_roundtrip(tmp_path):
    sidecar = tmp_path / "catalog-cores.txt"
    write_core_paths_sidecar(str(sidecar), ["a/b/sentences", "c/d/sentences"])
    assert read_core_paths_sidecar(str(sidecar)) == ["a/b/sentences", "c/d/sentences"]


def test_read_core_paths_sidecar_missing_returns_none(tmp_path):
    assert read_core_paths_sidecar(str(tmp_path / "missing.txt")) is None


def test_read_core_paths_sidecar_empty_file_returns_empty_list(tmp_path):
    """An existing-but-empty sidecar means 'ran, found zero cores' -- distinct from
    'never ran' (None), which callers use to decide rescan-vs-trust-empty."""
    sidecar = tmp_path / "catalog-cores.txt"
    write_core_paths_sidecar(str(sidecar), [])
    assert read_core_paths_sidecar(str(sidecar)) == []


def test_write_core_paths_sidecar_is_atomic_no_partial_file_on_failure(tmp_path):
    """A failure partway through producing the path list (e.g. the iterable itself
    raising) must not leave a torn file at the sidecar's final path, and must not leak
    a temp file either -- readers only ever see the last complete write, or nothing."""
    sidecar = tmp_path / "catalog-cores.txt"

    def _boom():
        yield "a/b/sentences"
        raise RuntimeError("simulated write failure")

    with pytest.raises(RuntimeError):
        write_core_paths_sidecar(str(sidecar), _boom())

    assert not sidecar.exists()
    assert list(tmp_path.iterdir()) == []


def test_write_core_paths_sidecar_overwrites_existing_atomically(tmp_path):
    """A pre-existing sidecar is replaced wholesale (not appended to); a reader never
    sees a mix of old and new content."""
    sidecar = tmp_path / "catalog-cores.txt"
    write_core_paths_sidecar(str(sidecar), ["old/path/sentences"])
    write_core_paths_sidecar(str(sidecar), ["new/path/sentences"])
    assert read_core_paths_sidecar(str(sidecar)) == ["new/path/sentences"]
