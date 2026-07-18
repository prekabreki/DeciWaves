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


def test_write_stage_coverage_rebuilds_non_utf8_file_with_warning(tmp_path, capsys):
    """Byte-level corruption (a torn write, or a tool re-saving the file as
    UTF-16 -- this is a Windows-only project) raises UnicodeDecodeError, which
    the corrupt-file handler must treat exactly like invalid JSON: rebuild with
    a warning, never crash every subsequent run until manual deletion (#81)."""
    path = str(tmp_path / "coverage.json")
    with open(path, "wb") as f:
        f.write(b"\xff\xfe{ not utf-8 \xff")

    coverage.write_stage_coverage(path, "bind", {"buckets_skipped": 3})

    data = json.loads(open(path, encoding="utf-8").read())
    assert data == {"bind": {"buckets_skipped": 3}}
    assert "coverage.json" in capsys.readouterr().out


def test_write_stage_coverage_never_raises_on_unwritable_path(tmp_path, capsys):
    """The artifact is informational: a stage whose real work succeeded must
    never be FAILED by a coverage-write problem (typo'd --coverage-out pointing
    at an existing directory, a read-only location) -- warn and move on (#81).
    Before this, the unguarded write crashed the stage with a raw traceback
    after an hours-long GPU bind had already succeeded."""
    path = str(tmp_path / "iamadir")
    (tmp_path / "iamadir").mkdir()  # os.replace onto a directory fails on Windows

    coverage.write_stage_coverage(path, "bind", {"buckets_skipped": 3})  # must not raise

    out = capsys.readouterr().out
    assert "warning" in out.lower()
    assert "iamadir" in out


def test_write_stage_coverage_never_raises_on_unserializable_stat(tmp_path, capsys):
    """The never-raise boundary must also survive a non-JSON-serializable stat
    (a set, Path, datetime, numpy scalar, circular ref) -- json.dumps raises
    TypeError/ValueError, not OSError, and that must NOT escape to fail a stage
    whose real work already succeeded (issue #87 finding 3). No current caller
    passes such a value, so this pins the contract, not a live crash."""
    path = str(tmp_path / "coverage.json")

    coverage.write_stage_coverage(path, "bind", {"weird": {1, 2, 3}})  # a set: not JSON

    out = capsys.readouterr().out
    assert "warning" in out.lower()
    assert "coverage.json" in out
    # the bad section was dropped, not half-written; the file is either absent or valid JSON
    if os.path.exists(path):
        json.loads(open(path, encoding="utf-8").read())


def test_clear_stage_coverage_on_corrupt_file_does_not_claim_rebuild(tmp_path, capsys):
    """Clearing a section from a CORRUPT file never rewrites it (clear returns
    once the section is absent from the empty load), so the warning must not
    claim it rebuilt the file -- that lie recurred on every invalidation while
    the bytes stayed corrupt (issue #87 finding 6)."""
    path = str(tmp_path / "coverage.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")

    coverage.clear_stage_coverage(path, "bind")   # no-op on the (unparseable) file

    out = capsys.readouterr().out
    assert "coverage.json" in out                 # still warns it's unreadable
    assert "rebuil" not in out.lower()            # ...but doesn't claim to have rebuilt it
    assert open(path, encoding="utf-8").read() == "{not json"  # bytes untouched


def test_clear_stage_coverage_removes_section_keeps_others(tmp_path):
    """Mirror of the done-marker contract (#81): marker absent = not done,
    section absent = coverage unknown. Clearing one stage's section must not
    touch its siblings'."""
    path = str(tmp_path / "coverage.json")
    coverage.write_stage_coverage(path, "wem-metadata", {"story_lines": 10})
    coverage.write_stage_coverage(path, "bind", {"buckets_skipped": 3})

    coverage.clear_stage_coverage(path, "bind")

    data = json.loads(open(path, encoding="utf-8").read())
    assert data == {"wem-metadata": {"story_lines": 10}}


def test_clear_stage_coverage_noops_on_missing_file_and_section(tmp_path):
    path = str(tmp_path / "coverage.json")
    coverage.clear_stage_coverage(path, "bind")          # no file: no-op, no raise
    assert not (tmp_path / "coverage.json").exists()     # and none created

    coverage.write_stage_coverage(path, "wem-metadata", {"story_lines": 10})
    coverage.clear_stage_coverage(path, "bind")          # no such section: no-op
    data = json.loads(open(path, encoding="utf-8").read())
    assert data == {"wem-metadata": {"story_lines": 10}}
