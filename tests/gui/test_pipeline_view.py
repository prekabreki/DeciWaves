"""Pipeline-view widgets (#69, spec §5): stage strip, Scan/Bind controls, coverage bar,
issues panel. Parsing/argv logic is covered Qt-free elsewhere; here we cover the widgets.
Skips without [gui]."""
import json
import os

import pytest

pytest.importorskip("PySide6")
from deciwaves.gui.views.pipeline_panels import (  # noqa: E402
    CoverageBar,
    IssuesPanel,
    PipelineControls,
    StageStrip,
)


def _touch_marker(ws, game, stage):
    d = os.path.join(ws, "out", game)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, f".done-{stage}"), "w").close()


# --- StageStrip ------------------------------------------------------------

def test_stage_strip_reflects_chain_and_markers(qtbot, tmp_path):
    _touch_marker(str(tmp_path), "hzd", "catalog")
    s = StageStrip()
    qtbot.addWidget(s)
    s.refresh("hzd", str(tmp_path))
    states = {x.name: x for x in s.states()}
    assert [x.name for x in s.states()] == [
        "catalog", "clip-index", "wem-metadata", "bind", "render"]
    assert states["catalog"].done and not states["bind"].done
    assert states["bind"].gpu is True


def test_stage_strip_rerun_requested_signal(qtbot):
    s = StageStrip()
    qtbot.addWidget(s)
    s.refresh("ds", ".")
    with qtbot.waitSignal(s.rerun_requested) as blocker:
        s.request_rerun("order")
    assert blocker.args == ["order"]


def test_stage_strip_marks_running_stage(qtbot, tmp_path):
    s = StageStrip()
    qtbot.addWidget(s)
    s.refresh("hzd", str(tmp_path), running_stage="catalog")
    assert s.running_stage() == "catalog"


# --- PipelineControls ------------------------------------------------------

def test_controls_hide_bind_for_ds_show_for_gpu_games(qtbot):
    c = PipelineControls()
    qtbot.addWidget(c)
    c.set_game_has_gpu(False)
    assert c.bind_shown() is False       # DS: no GPU stage -> no Bind button (spec §7)
    c.set_game_has_gpu(True)
    assert c.bind_shown() is True


def test_controls_emit_scan_and_process(qtbot):
    c = PipelineControls()
    qtbot.addWidget(c)
    with qtbot.waitSignal(c.scan_requested):
        c._scan_btn.click()
    c.set_game_has_gpu(True)
    with qtbot.waitSignal(c.process_requested):
        c._bind_btn.click()


def test_controls_disable_while_running(qtbot):
    c = PipelineControls()
    qtbot.addWidget(c)
    c.set_running(True)
    assert not c._scan_btn.isEnabled()
    c.set_running(False)
    assert c._scan_btn.isEnabled()


# --- CoverageBar -----------------------------------------------------------

def _write_coverage(ws, obj):
    d = os.path.join(ws, "out", "hzd")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "coverage.json"), "w", encoding="utf-8") as f:
        json.dump(obj, f)


def test_coverage_bar_shows_capped_text_and_escalates(qtbot, tmp_path):
    _write_coverage(str(tmp_path), {"bind": {"rows": 5001, "bound": 4812,
                                             "buckets_skipped": 12, "sample_cap": 300}})
    b = CoverageBar()
    qtbot.addWidget(b)
    b.refresh("hzd", str(tmp_path))
    assert b.has_coverage() is True
    assert "4,812 / 5,001" in b.text()
    assert b.escalate_shown() is True
    with qtbot.waitSignal(b.escalate_requested):
        b._escalate_btn.click()


def test_coverage_bar_hidden_when_no_artifact(qtbot, tmp_path):
    b = CoverageBar()
    qtbot.addWidget(b)
    b.refresh("ds", str(tmp_path))   # DS writes no coverage.json
    assert b.has_coverage() is False


# --- IssuesPanel -----------------------------------------------------------

def test_issues_panel_lists_error_groups(qtbot, tmp_path):
    d = os.path.join(str(tmp_path), "out", "hzd")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "catalog-errors.log"), "w", encoding="utf-8") as f:
        f.write("id1\tValueError: boom\n")
    p = IssuesPanel()
    qtbot.addWidget(p)
    p.refresh("hzd", str(tmp_path))
    assert any(g.source == "catalog-errors.log" for g in p.groups())


def test_issues_panel_empty_when_clean(qtbot, tmp_path):
    p = IssuesPanel()
    qtbot.addWidget(p)
    p.refresh("hzd", str(tmp_path))
    assert p.groups() == []
