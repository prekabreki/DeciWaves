"""Qt-free issues-panel model (#69, spec §5.4). No importorskip. Gathers per-stage
`*-errors.log` lines and DS's render-dupes.csv from the workspace."""
import os

from deciwaves.gui.issues_model import gather_issues


def _write(ws, rel, text):
    p = os.path.join(ws, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def test_no_issues_when_nothing_written(tmp_path):
    assert gather_issues(str(tmp_path), "hzd") == []


def test_gathers_error_log_lines(tmp_path):
    _write(str(tmp_path), "out/hzd/catalog-errors.log",
           "id1\tValueError: boom\nharvest:0x0000000000000001\tOSError: bad core\n")
    groups = {g.source: g for g in gather_issues(str(tmp_path), "hzd")}
    assert groups["catalog-errors.log"].count == 2
    assert any("boom" in ln for ln in groups["catalog-errors.log"].sample)


def test_hzd_bind_errors_use_asr_manifest_name(tmp_path):
    # HZD bind's log is asr-manifest-errors.log, NOT bind-errors.log (contract quirk)
    _write(str(tmp_path), "out/hzd/asr-manifest-errors.log", "42\tRuntimeError: decode\n")
    sources = {g.source for g in gather_issues(str(tmp_path), "hzd")}
    assert "asr-manifest-errors.log" in sources


def test_ds_render_dupes_counts_data_rows(tmp_path):
    _write(str(tmp_path), "out/render-dupes.csv", "line_id,scene\na,s1\nb,s2\n")
    groups = {g.source: g for g in gather_issues(str(tmp_path), "ds")}
    assert groups["render-dupes.csv"].count == 2   # header excluded


def test_empty_error_log_is_not_a_group(tmp_path):
    _write(str(tmp_path), "out/fw/extract-errors.log", "")
    assert gather_issues(str(tmp_path), "fw") == []
