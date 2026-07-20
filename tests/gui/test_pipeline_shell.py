"""Pipeline wired into the shell (#69, spec §5): the Scan/Bind/Re-run/Transcribe-all
controls start `deciwaves <game> run …` jobs on the single runner, GPU actions go through
the CUDA probe, and the panels refresh on game change. Skips without [gui]."""
import os

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from deciwaves.gui.shell import MainWindow  # noqa: E402

_CUDA_ABSENT = {"ok": True, "checks": [
    {"name": "cuda", "ok": True, "status": "unavailable", "message": "", "fix": ""}]}
_CUDA_OK = {"ok": True, "checks": [
    {"name": "cuda", "ok": True, "status": "ok", "message": "", "fix": ""}]}


def _capture_jobs(w):
    calls = []
    w.runner.start = lambda argv, cwd=None: calls.append(argv) or True
    return calls


def test_scan_button_starts_run_until(qtbot, tmp_path):
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.set_workspace(str(tmp_path))
    w.bar.select_game("hzd")
    calls = _capture_jobs(w)
    w.pipeline.controls._scan_btn.click()
    assert calls and calls[0][-3:] == ["run", "--until", "wem-metadata"]


def test_bind_confirms_gpu_then_runs(qtbot, tmp_path, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.set_workspace(str(tmp_path))
    w.bar.select_game("hzd")
    w.pipeline.setup_doctor.doctor.render_payload(_CUDA_ABSENT)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Yes)
    calls = _capture_jobs(w)
    w.pipeline.controls._bind_btn.click()
    # `hzd run`, resuming into bind; the per-game panel now threads its first-bind cap (#73),
    # so `run` is followed by the panel's default --sample-cap 300 (never a --until slice).
    assert calls and "run" in calls[0] and "--until" not in calls[0]
    assert calls[0][calls[0].index("--sample-cap") + 1] == "300"


def test_bind_aborts_when_gpu_declined(qtbot, tmp_path, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.set_workspace(str(tmp_path))
    w.bar.select_game("fw")
    w.pipeline.setup_doctor.doctor.render_payload(_CUDA_ABSENT)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.No)
    calls = _capture_jobs(w)
    w.pipeline.controls._bind_btn.click()
    assert calls == []          # declined -> no job started


def test_rerun_from_strip_starts_run_from(qtbot, tmp_path):
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.set_workspace(str(tmp_path))
    w.bar.select_game("ds")     # DS has no GPU stage -> no confirm dialog
    calls = _capture_jobs(w)
    w.pipeline.strip.request_rerun("order")
    assert calls and calls[0][-2:] == ["--from", "order"]


def test_rerun_crossing_gpu_declined_starts_nothing(qtbot, tmp_path, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.set_workspace(str(tmp_path))
    w.bar.select_game("hzd")
    w.pipeline.setup_doctor.doctor.render_payload(_CUDA_ABSENT)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.No)
    calls = _capture_jobs(w)
    w.pipeline.strip.request_rerun("catalog")   # ...cascades into GPU bind
    assert calls == []


def test_escalate_uncaps_without_gpu_dialog_when_gpu_present(qtbot, tmp_path, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.set_workspace(str(tmp_path))
    w.bar.select_game("hzd")
    w.pipeline.setup_doctor.doctor.render_payload(_CUDA_OK)
    monkeypatch.setattr("deciwaves.gui.shell.MainWindow._confirm_escalate",
                        lambda self: True)   # accept destructive confirm
    calls = _capture_jobs(w)
    w.pipeline.coverage.escalate_requested.emit()
    argv = calls[0]
    assert argv[argv.index("--sample-cap") + 1] == "0" and "--from" in argv


def test_escalate_rejected_does_not_start_job(qtbot, tmp_path, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.set_workspace(str(tmp_path))
    w.bar.select_game("hzd")
    monkeypatch.setattr("deciwaves.gui.shell.MainWindow._confirm_escalate",
                        lambda self: False)
    calls = _capture_jobs(w)
    w.pipeline.coverage.escalate_requested.emit()
    assert calls == []


def test_rerun_invalidates_completed_rejected_does_nothing(qtbot, tmp_path, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.set_workspace(str(tmp_path))
    w.bar.select_game("hzd")
    hzd_out = os.path.join(str(tmp_path), "out", "hzd")
    os.makedirs(hzd_out, exist_ok=True)
    for stage in ["bind", "render"]:
        open(os.path.join(hzd_out, f".done-{stage}"), "w").close()
    monkeypatch.setattr("deciwaves.gui.shell.MainWindow._confirm_rerun",
                        lambda self, stage: False)
    calls = _capture_jobs(w)
    w.pipeline.strip.request_rerun("catalog")
    assert calls == []


def test_rerun_invalidates_completed_accepted_starts_job(qtbot, tmp_path, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.set_workspace(str(tmp_path))
    w.bar.select_game("ds")
    ds_out = os.path.join(str(tmp_path), "out", "ds")
    os.makedirs(ds_out, exist_ok=True)
    open(os.path.join(ds_out, ".done-render"), "w").close()
    monkeypatch.setattr("deciwaves.gui.shell.MainWindow._confirm_rerun",
                        lambda self, stage: True)
    calls = _capture_jobs(w)
    w.pipeline.strip.request_rerun("catalog")
    assert calls and calls[0][-2:] == ["--from", "catalog"]


def test_panels_refresh_on_game_change(qtbot, tmp_path):
    d = os.path.join(str(tmp_path), "out", "hzd")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, ".done-catalog"), "w").close()
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.set_workspace(str(tmp_path))
    w.bar.select_game("hzd")
    states = {s.name: s for s in w.pipeline.strip.states()}
    assert states["catalog"].done


def test_ds_hides_bind_hzd_shows_it(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.select_game("ds")
    assert w.pipeline.controls.bind_shown() is False
    w.bar.select_game("hzd")
    assert w.pipeline.controls.bind_shown() is True
