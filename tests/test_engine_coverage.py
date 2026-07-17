"""engine.coverage (issue #63): per-stage coverage summaries persisted to one
per-game JSON artifact, so a --sample-cap'd rip is distinguishable from a
complete one ON DISK -- these numbers used to be stdout-only, and the GUI's
coverage bar (spec §5.4) must read a file, not scrape stdout."""
import json
import os

from deciwaves.engine import coverage


def test_default_coverage_path_is_per_game_and_workspace_relative():
    """The GUI reads this exact location -- lock it."""
    assert coverage.default_coverage_path("hzd") == os.path.join("out", "hzd", "coverage.json")


def test_write_stage_coverage_creates_file_with_section(tmp_path):
    path = str(tmp_path / "out" / "hzd" / "coverage.json")  # parent dirs don't exist yet

    coverage.write_stage_coverage(path, "wem-metadata", {"story_lines": 10, "with_ab": 9})

    data = json.loads(open(path, encoding="utf-8").read())
    assert data == {"wem-metadata": {"story_lines": 10, "with_ab": 9}}


def test_write_stage_coverage_merges_sections_across_stages(tmp_path):
    """Stages run as separate processes, each merging its own section -- an
    earlier stage's section must survive a later stage's write."""
    path = str(tmp_path / "coverage.json")

    coverage.write_stage_coverage(path, "wem-metadata", {"story_lines": 10})
    coverage.write_stage_coverage(path, "bind", {"buckets_skipped": 3})

    data = json.loads(open(path, encoding="utf-8").read())
    assert data == {"wem-metadata": {"story_lines": 10}, "bind": {"buckets_skipped": 3}}


def test_write_stage_coverage_replaces_own_section_keeps_others(tmp_path):
    """A re-run stage REPLACES its section wholesale (stale keys from an older
    schema must not linger), without touching other stages' sections."""
    path = str(tmp_path / "coverage.json")
    coverage.write_stage_coverage(path, "wem-metadata", {"story_lines": 10})
    coverage.write_stage_coverage(path, "bind", {"buckets_skipped": 3, "old_key": 1})

    coverage.write_stage_coverage(path, "bind", {"buckets_skipped": 0})

    data = json.loads(open(path, encoding="utf-8").read())
    assert data == {"wem-metadata": {"story_lines": 10}, "bind": {"buckets_skipped": 0}}


def test_write_stage_coverage_rebuilds_corrupt_file_with_warning(tmp_path, capsys):
    """A corrupt artifact is derived data -- rebuild it (fresh object holding just
    this stage's section) rather than crashing the stage, but never silently."""
    path = str(tmp_path / "coverage.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")

    coverage.write_stage_coverage(path, "bind", {"buckets_skipped": 3})

    data = json.loads(open(path, encoding="utf-8").read())
    assert data == {"bind": {"buckets_skipped": 3}}
    assert "coverage.json" in capsys.readouterr().out  # warned, named the file


def test_write_stage_coverage_rebuilds_non_object_file_with_warning(tmp_path, capsys):
    """Valid JSON that isn't an object (e.g. a bare list) can't be merged into --
    same rebuild-with-warning treatment as corrupt bytes."""
    path = str(tmp_path / "coverage.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("[1, 2, 3]")

    coverage.write_stage_coverage(path, "bind", {"buckets_skipped": 3})

    data = json.loads(open(path, encoding="utf-8").read())
    assert data == {"bind": {"buckets_skipped": 3}}
    assert "coverage.json" in capsys.readouterr().out
