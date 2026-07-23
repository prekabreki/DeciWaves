"""Unit tests for JobController dispatch + mutual-exclusion (issue #146).

Tests the controller headless (no MainWindow), exercising busy-check gating, confirm
dialogs, and export flows."""
import csv
import os

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QProcess  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from deciwaves.gui.job_controller import JobController  # noqa: E402

_CUDA_OK = {"ok": True, "checks": [
    {"name": "cuda", "ok": True, "status": "ok", "message": "", "fix": ""}]}
_CUDA_ABSENT = {"ok": True, "checks": [
    {"name": "cuda", "ok": True, "status": "unavailable", "message": "", "fix": ""}]}


class _FakeRunningProcess:
    """A mock that makes ``QProcess.state()`` return ``Running``."""

    def state(self, *a, **k):
        return QProcess.Running


def _capture_jobs(ctrl):
    calls = []
    ctrl.runner.start = lambda argv, cwd=None: calls.append(argv) or True
    return calls


def _make_busy(ctrl):
    """Fake a running runner so the mutual-exclusion guard triggers."""
    ctrl.runner._proc = _FakeRunningProcess()


# -- dispatch: basic argv construction -------------------------------------

def test_start_scan_starts_runner_with_correct_game(qtbot, tmp_path):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    ctrl.start_scan("hzd", str(tmp_path))
    assert calls
    assert calls[0][-3:] == ["run", "--until", "wem-metadata"]


def test_start_process_includes_sample_cap(qtbot, tmp_path):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    ctrl.start_process("hzd", str(tmp_path), 50, _CUDA_OK)
    argv = calls[0]
    assert "run" in argv and "--sample-cap" in argv
    assert argv[argv.index("--sample-cap") + 1] == "50"


def test_start_process_runs_with_none_sample_cap(qtbot, tmp_path):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    ctrl.start_process("ds", str(tmp_path), None, _CUDA_OK)
    assert calls and "run" in calls[0]


def test_start_rerun_builds_from_flag(qtbot, tmp_path):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    ctrl.start_rerun("ds", str(tmp_path), "order", _CUDA_OK)
    assert calls and calls[0][-2:] == ["--from", "order"]


def test_start_escalate_uncaps(qtbot, tmp_path, monkeypatch):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    monkeypatch.setattr(JobController, "_confirm_escalate", lambda self: True)
    ctrl.start_escalate("hzd", str(tmp_path), _CUDA_OK)
    argv = calls[0]
    assert argv[argv.index("--sample-cap") + 1] == "0" and "--from" in argv


def test_start_transcript_order_runs_standalone_order(qtbot, tmp_path):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    transcript = os.path.join(str(tmp_path), "story.md")
    with open(transcript, "w", encoding="utf-8") as f:
        f.write("...")
    ok = ctrl.start_transcript_order("ds", str(tmp_path), transcript)
    assert ok
    argv = calls[0]
    assert "order" in argv and "run" not in argv
    assert argv[argv.index("--transcript") + 1] == os.path.abspath(transcript)


def test_start_transcript_order_refuses_non_ds(qtbot, tmp_path):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    ok = ctrl.start_transcript_order("hzd", str(tmp_path), "/tmp/story.md")
    assert not ok
    assert not calls


# -- mutual exclusion ------------------------------------------------------

def test_busy_runner_blocks_scan(qtbot):
    ctrl = JobController()
    _make_busy(ctrl)
    calls = _capture_jobs(ctrl)
    ctrl.start_scan("ds", ".")
    assert not calls


def test_busy_runner_blocks_process(qtbot):
    ctrl = JobController()
    _make_busy(ctrl)
    calls = _capture_jobs(ctrl)
    ctrl.start_process("hzd", ".", None, _CUDA_OK)
    assert not calls


def test_busy_runner_blocks_rerun(qtbot):
    ctrl = JobController()
    _make_busy(ctrl)
    calls = _capture_jobs(ctrl)
    ctrl.start_rerun("ds", ".", "order", _CUDA_OK)
    assert not calls


def test_busy_runner_blocks_escalate(qtbot):
    ctrl = JobController()
    _make_busy(ctrl)
    calls = _capture_jobs(ctrl)
    ctrl.start_escalate("hzd", ".", _CUDA_OK)
    assert not calls


def test_busy_runner_blocks_export_mp3(qtbot, tmp_path):
    ctrl = JobController()
    _make_busy(ctrl)
    calls = _capture_jobs(ctrl)
    err = ctrl.start_export_mp3("ds", str(tmp_path), 128, [])
    assert err == "export: a job is already running.\n"
    assert not calls


def test_busy_runner_blocks_dump_wav(qtbot):
    ctrl = JobController()
    _make_busy(ctrl)
    err = ctrl.start_dump_wav("ds", ".", None, [("a", None)], "/tmp/d")
    assert err == "dump: a job is already running.\n"


def test_busy_runner_blocks_transcript_order(qtbot, tmp_path):
    ctrl = JobController()
    _make_busy(ctrl)
    calls = _capture_jobs(ctrl)
    ok = ctrl.start_transcript_order("ds", str(tmp_path), str(tmp_path / "story.md"))
    assert not ok
    assert not calls


def test_busy_dump_blocks_scan(qtbot):
    ctrl = JobController()
    ctrl.dump._running = True
    calls = _capture_jobs(ctrl)
    ctrl.start_scan("ds", ".")
    assert not calls


# -- confirm-gate: GPU -----------------------------------------------------

def test_process_aborts_when_gpu_declined(qtbot, monkeypatch):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.No)
    ctrl.start_process("hzd", ".", None, _CUDA_ABSENT)
    assert not calls


def test_process_proceeds_when_gpu_accepted(qtbot, monkeypatch):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Yes)
    ctrl.start_process("hzd", ".", None, _CUDA_ABSENT)
    assert calls


def test_rerun_crossing_gpu_declined_starts_nothing(qtbot, monkeypatch):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.No)
    ctrl.start_rerun("hzd", ".", "catalog", _CUDA_ABSENT)
    assert not calls


def test_escalate_aborts_when_gpu_declined(qtbot, monkeypatch):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.No)
    monkeypatch.setattr(JobController, "_confirm_escalate", lambda self: True)
    ctrl.start_escalate("hzd", ".", _CUDA_ABSENT)
    assert not calls


# -- confirm-gate: escalate -------------------------------------------------

def test_escalate_rejected_does_not_start_job(qtbot, tmp_path, monkeypatch):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    monkeypatch.setattr(JobController, "_confirm_escalate", lambda self: False)
    ctrl.start_escalate("hzd", str(tmp_path), _CUDA_OK)
    assert not calls


def test_escalate_accepted_starts_job(qtbot, tmp_path, monkeypatch):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    monkeypatch.setattr(JobController, "_confirm_escalate", lambda self: True)
    ctrl.start_escalate("hzd", str(tmp_path), _CUDA_OK)
    assert calls


# -- confirm-gate: rerun ----------------------------------------------------

def test_rerun_invalidates_completed_rejected_does_nothing(qtbot, tmp_path, monkeypatch):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    hzd_out = os.path.join(str(tmp_path), "out", "hzd")
    os.makedirs(hzd_out, exist_ok=True)
    for stage in ["bind", "render"]:
        open(os.path.join(hzd_out, f".done-{stage}"), "w").close()
    monkeypatch.setattr(JobController, "_confirm_rerun", lambda self, stage: False)
    ctrl.start_rerun("hzd", str(tmp_path), "catalog", _CUDA_OK)
    assert not calls


def test_rerun_invalidates_completed_accepted_starts_job(qtbot, tmp_path, monkeypatch):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    ds_out = os.path.join(str(tmp_path), "out", "ds")
    os.makedirs(ds_out, exist_ok=True)
    open(os.path.join(ds_out, ".done-render"), "w").close()
    monkeypatch.setattr(JobController, "_confirm_rerun", lambda self, stage: True)
    ctrl.start_rerun("ds", str(tmp_path), "catalog", _CUDA_OK)
    assert calls and calls[0][-2:] == ["--from", "catalog"]


# -- _rerun_invalidates_completed -------------------------------------------

def test_rerun_invalidates_completed_with_no_done_stages_is_false(qtbot, tmp_path):
    ctrl = JobController()
    result = ctrl._rerun_invalidates_completed("hzd", str(tmp_path), "catalog")
    assert result is False


def test_rerun_invalidates_completed_with_completed_later_stage_is_true(qtbot, tmp_path):
    ds_out = os.path.join(str(tmp_path), "out", "ds")
    os.makedirs(ds_out, exist_ok=True)
    open(os.path.join(ds_out, ".done-render"), "w").close()
    ctrl = JobController()
    result = ctrl._rerun_invalidates_completed("ds", str(tmp_path), "catalog")
    assert result is True


# -- job lifecycle ----------------------------------------------------------

def test_on_job_started_emits_chip_and_busy(qtbot):
    ctrl = JobController()
    _make_busy(ctrl)
    chips = []
    ctrl.job_chip_changed.connect(chips.append)
    busy_states = []
    ctrl.busy_changed.connect(busy_states.append)
    ctrl._on_job_started()
    assert chips == ["running"]
    assert busy_states == [True]


def test_on_job_finished_pipeline_success_emits_idle(qtbot):
    ctrl = JobController()
    chips = []
    ctrl.job_chip_changed.connect(chips.append)
    busy_states = []
    ctrl.busy_changed.connect(busy_states.append)
    ctrl._on_job_finished(0)
    assert chips == ["idle"]
    assert busy_states[-1] is False


def test_on_job_finished_pipeline_failure_emits_failed(qtbot):
    ctrl = JobController()
    chips = []
    ctrl.job_chip_changed.connect(chips.append)
    ctrl.runner._was_cancelled = False
    ctrl._on_job_finished(1)
    assert chips == ["failed"]


def test_on_job_finished_cancelled_emits_idle(qtbot):
    ctrl = JobController()
    chips = []
    ctrl.job_chip_changed.connect(chips.append)
    ctrl.runner._was_cancelled = True
    ctrl._on_job_finished(1)
    assert chips == ["idle"]


def test_on_job_finished_export_success_logs(qtbot):
    ctrl = JobController()
    ctrl._job_kind = "export"
    ctrl._job_game = "ds"
    logs = []
    ctrl.log_message.connect(logs.append)
    ctrl._on_job_finished(0)
    assert any("export" in msg.lower() for msg in logs)


def test_on_job_finished_export_failure_logs(qtbot):
    ctrl = JobController()
    ctrl._job_kind = "export"
    ctrl._job_game = "ds"
    logs = []
    ctrl.log_message.connect(logs.append)
    ctrl._on_job_finished(1)
    failure_msgs = [m for m in logs if "fail" in m.lower()]
    assert failure_msgs


def test_on_job_finished_clears_state(qtbot):
    ctrl = JobController()
    ctrl._job_kind = "export"
    ctrl._job_game = "ds"
    ctrl._on_job_finished(0)
    assert ctrl._job_kind is None
    assert ctrl._job_game is None


# -- _sync_running ----------------------------------------------------------

def test_sync_running_emits_busy_when_runner_active(qtbot):
    ctrl = JobController()
    _make_busy(ctrl)
    busy_states = []
    ctrl.busy_changed.connect(busy_states.append)
    ctrl._sync_running()
    assert busy_states == [True]


def test_sync_running_emits_not_busy_when_both_idle(qtbot):
    ctrl = JobController()
    busy_states = []
    ctrl.busy_changed.connect(busy_states.append)
    ctrl._sync_running()
    assert busy_states == [False]


def test_sync_running_emits_busy_when_dump_active(qtbot):
    ctrl = JobController()
    ctrl.dump._running = True
    busy_states = []
    ctrl.busy_changed.connect(busy_states.append)
    ctrl._sync_running()
    assert busy_states == [True]


# -- dump lifecycle ---------------------------------------------------------

def test_on_dump_finished_emits_log_and_status(qtbot):
    ctrl = JobController()
    logs = []
    ctrl.log_message.connect(logs.append)
    statuses = []
    ctrl.dump_status.connect(lambda ok, bad: statuses.append((ok, bad)))
    ctrl._on_dump_finished(3, 1)
    assert any("3 ok" in m for m in logs)
    assert statuses == [(3, 1)]


# -- export catalog ---------------------------------------------------------

def test_start_catalog_copy_copies_file(qtbot, tmp_path):
    src = os.path.join(str(tmp_path), "out", "catalog.csv")
    os.makedirs(os.path.dirname(src), exist_ok=True)
    with open(src, "w", encoding="utf-8") as f:
        f.write("line_id\na\n")
    ctrl = JobController()
    dest = os.path.join(str(tmp_path), "exported.csv")
    with qtbot.waitSignal(ctrl.log_message, timeout=5000) as blocker:
        ctrl.start_catalog_copy("ds", str(tmp_path), dest)
    assert "copied" in blocker.args[0].lower()
    assert os.path.isfile(dest)
    assert open(dest, encoding="utf-8").read() == "line_id\na\n"


def test_start_catalog_copy_missing_source_reports_error(qtbot, tmp_path):
    ctrl = JobController()
    with qtbot.waitSignal(ctrl.log_message, timeout=5000) as blocker:
        ctrl.start_catalog_copy("fw", str(tmp_path), os.path.join(str(tmp_path), "x.csv"))
    assert "no catalog artifact" in blocker.args[0].lower()


def test_start_order_copy_copies_render_input(qtbot, tmp_path):
    ws = str(tmp_path)
    p = os.path.join(ws, "out", "playlist.csv")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["line_id"], ["a"]])
    ctrl = JobController()
    dest = os.path.join(ws, "exported-order.csv")
    with qtbot.waitSignal(ctrl.log_message, timeout=5000) as blocker:
        ctrl.start_order_copy("ds", ws, dest)
    assert "copied" in blocker.args[0].lower()
    assert os.path.isfile(dest)
    with open(dest, encoding="utf-8-sig") as f:
        assert "line_id" in f.read()


# -- _report_export_result --------------------------------------------------

def test_report_export_result_success(qtbot):
    ctrl = JobController()
    msg = ctrl._report_export_result("ds", 0)
    assert "done" in msg.lower() and "out/audio" in msg


def test_report_export_result_failure(qtbot):
    ctrl = JobController()
    msg = ctrl._report_export_result("ds", 1)
    assert "fail" in msg.lower()


# -- signal wiring ----------------------------------------------------------

def test_runner_started_triggers_internal_on_job_started(qtbot):
    ctrl = JobController()
    _make_busy(ctrl)
    chips = []
    ctrl.job_chip_changed.connect(chips.append)
    ctrl.runner.started.emit()
    assert chips == ["running"]


def test_runner_finished_cleans_state_and_emits_chip(qtbot):
    ctrl = JobController()
    ctrl._job_game = "ds"
    ctrl._job_kind = None
    chips = []
    ctrl.job_chip_changed.connect(chips.append)
    ctrl.runner.finished.emit(0)
    assert chips == ["idle"]
    assert ctrl._job_game is None
    assert ctrl._job_kind is None


# -- export MP3 empty-selection guard (M7) ----------------------------------

def test_export_mp3_empty_selection_returns_message(qtbot, tmp_path):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    err = ctrl.start_export_mp3("ds", str(tmp_path), 128, [], checked_count=0)
    assert err == "export: nothing selected — check some rows first.\n"
    assert not calls


def test_export_mp3_proceeds_with_checked_rows(qtbot, tmp_path):
    ctrl = JobController()
    calls = _capture_jobs(ctrl)
    err = ctrl.start_export_mp3("ds", str(tmp_path), 128, [], checked_count=1)
    assert err != "export: nothing selected — check some rows first.\n"
    assert err is not None
    assert not calls
