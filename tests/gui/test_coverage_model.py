"""Qt-free coverage-bar model (#69, spec §5.4). No importorskip. Coverage is HZD-only
(out/hzd/coverage.json); DS/FW write none, so load returns None there and the bar hides."""
import json
import os

from deciwaves.gui.coverage_model import (
    CoverageSummary,
    coverage_summary,
    format_coverage,
    load_coverage,
    needs_escalation,
)


def _write_coverage(ws, obj):
    d = os.path.join(ws, "out", "hzd")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "coverage.json"), "w", encoding="utf-8") as f:
        json.dump(obj, f)


def test_load_missing_or_corrupt_returns_none(tmp_path):
    assert load_coverage(str(tmp_path), "hzd") is None
    d = os.path.join(str(tmp_path), "out", "hzd")
    os.makedirs(d)
    with open(os.path.join(d, "coverage.json"), "w", encoding="utf-8") as f:
        f.write("not json{{")
    assert load_coverage(str(tmp_path), "hzd") is None


def test_load_and_summarize_bind_section(tmp_path):
    _write_coverage(str(tmp_path), {"bind": {"rows": 5001, "bound": 4812,
                                             "buckets_skipped": 12, "sample_cap": 300}})
    s = coverage_summary(load_coverage(str(tmp_path), "hzd"))
    assert (s.bound, s.rows, s.cap_skipped, s.sample_cap) == (4812, 5001, 12, 300)
    assert s.pct == round(4812 / 5001 * 100, 1)


def test_summary_none_without_a_bind_section():
    assert coverage_summary({"wem-metadata": {"story_lines": 10}}) is None
    assert coverage_summary({}) is None
    assert coverage_summary(None) is None


def test_format_and_escalation_when_capped():
    s = CoverageSummary(bound=4812, rows=5001, pct=96.2, cap_skipped=12, sample_cap=300)
    assert needs_escalation(s) is True
    text = format_coverage(s)
    assert "4,812 / 5,001" in text and "untranscribed" in text


def test_no_escalation_when_uncapped_and_complete():
    s = CoverageSummary(bound=5001, rows=5001, pct=100.0, cap_skipped=0, sample_cap=0)
    assert needs_escalation(s) is False
    assert "untranscribed" not in format_coverage(s)
