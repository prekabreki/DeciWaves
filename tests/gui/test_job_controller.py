"""JobController: window-free orchestration tests (#146)."""
import os
import sys

import pytest

pytest.importorskip("PySide6")
from deciwaves.gui.job_controller import JobController  # noqa: E402

SLOW = "import time\nfor i in range(200):\n print(i, flush=True); time.sleep(0.02)"


# ---- mutual exclusion ----------------------------------------------------

def test_scan_rejected_when_runner_busy(qtbot):
    c = JobController()
    c.runner.start([sys.executable, "-c", SLOW])
    assert c.scan(["base"], "ds", ".") is False
    c.runner.cancel()
    with qtbot.waitSignal(c.runner.finished, timeout=5000):
        pass


def test_process_rejected_when_runner_busy(qtbot):
    c = JobController()
    c.runner.start([sys.executable, "-c", SLOW])
    assert c.process(["base"], "hzd", ".") is False
    c.runner.cancel()
    with qtbot.waitSignal(c.runner.finished, timeout=5000):
        pass


def test_rerun_rejected_when_runner_busy(qtbot):
    c = JobController()
    c.runner.start([sys.executable, "-c", SLOW])
    assert c.rerun(["base"], "ds", ".", "order") is False
    c.runner.cancel()
    with qtbot.waitSignal(c.runner.finished, timeout=5000):
        pass


def test_escalate_rejected_when_runner_busy(qtbot):
    c = JobController()
    c.runner.start([sys.executable, "-c", SLOW])
    assert c.escalate(["base"], "hzd", ".") is False
    c.runner.cancel()
    with qtbot.waitSignal(c.runner.finished, timeout=5000):
        pass


def test_export_mp3_rejected_when_runner_busy_and_logs(qtbot):
    c = JobController()
    c.runner.start([sys.executable, "-c", SLOW])
    logs = []
    c.log_message.connect(logs.append)
    assert c.export_mp3(["base"], "ds", ".", set(), 128, {}) is False
    assert any("export: a job is already running" in m for m in logs)
    c.runner.cancel()
    with qtbot.waitSignal(c.runner.finished, timeout=5000):
        pass


def test_transcript_order_rejected_when_runner_busy_and_logs(qtbot):
    c = JobController()
    c.runner.start([sys.executable, "-c", SLOW])
    logs = []
    c.log_message.connect(logs.append)
    assert c.transcript_order(["base"], ".", "/some/path") is False
    assert any("re-order: a job is already running" in m for m in logs)
    c.runner.cancel()
    with qtbot.waitSignal(c.runner.finished, timeout=5000):
        pass


def test_dump_wav_rejected_when_runner_busy_and_logs(qtbot):
    c = JobController()
    c.runner.start([sys.executable, "-c", SLOW])
    logs = []
    c.log_message.connect(logs.append)
    assert c.dump_wav(None, [("id1", "a.wav")], "/tmp") is False
    assert any("dump: a job is already running" in m for m in logs)
    c.runner.cancel()
    with qtbot.waitSignal(c.runner.finished, timeout=5000):
        pass


# ---- confirm callbacks ---------------------------------------------------

def test_process_aborts_when_gpu_declined(qtbot):
    c = JobController()
    c._confirm_gpu = lambda game: False
    assert c.process(["base"], "hzd", ".") is False


def test_escalate_aborts_when_escalate_declined(qtbot):
    c = JobController()
    c._confirm_escalate = lambda: False
    assert c.escalate(["base"], "hzd", ".") is False


def test_escalate_aborts_when_gpu_declined(qtbot):
    c = JobController()
    c._confirm_escalate = lambda: True
    c._confirm_gpu = lambda game: False
    assert c.escalate(["base"], "hzd", ".") is False


def test_rerun_aborts_when_rerun_declined_and_invalidates(qtbot, tmp_path):
    out = os.path.join(str(tmp_path), "out", "hzd")
    os.makedirs(out, exist_ok=True)
    for stage in ["bind", "render"]:
        open(os.path.join(out, f".done-{stage}"), "w").close()
    c = JobController()
    c._confirm_rerun = lambda stage: False
    assert c.rerun(["base"], "hzd", str(tmp_path), "catalog") is False


def test_rerun_proceeds_when_rerun_accepted(qtbot, tmp_path):
    out = os.path.join(str(tmp_path), "out", "ds")
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, ".done-render"), "w").close()
    c = JobController()
    started = []
    c.runner.start = lambda argv, cwd=None: started.append(argv) or True
    c._confirm_rerun = lambda stage: True
    assert c.rerun(["base"], "ds", str(tmp_path), "catalog") is True
    assert started and started[0][-2:] == ["--from", "catalog"]


def test_process_proceeds_with_default_gpu_confirm(qtbot):
    c = JobController()
    started = []
    c.runner.start = lambda argv, cwd=None: started.append(argv) or True
    assert c.process(["deciwaves"], "hzd", ".") is True
    assert started


def test_scan_proceeds_without_gpu_confirm(qtbot):
    c = JobController()
    started = []
    c.runner.start = lambda argv, cwd=None: started.append(argv) or True
    assert c.scan(["deciwaves"], "hzd", ".") is True
    assert started


# ---- lifecycle signals ---------------------------------------------------

def test_on_job_started_emits_busy_and_chip(qtbot):
    c = JobController()
    busy_signals = []
    chip_texts = []
    c.busy_changed.connect(lambda: busy_signals.append(1))
    c.chip_text.connect(chip_texts.append)
    c._job_game = "hzd"
    c._on_job_started()
    assert len(busy_signals) == 1
    assert chip_texts == ["hzd · running"]


def test_on_job_finished_pipeline_success_emits_idle_chip(qtbot):
    c = JobController()
    busy_signals = []
    chip_texts = []
    c.busy_changed.connect(lambda: busy_signals.append(1))
    c.chip_text.connect(chip_texts.append)
    c._on_job_finished(0)
    assert len(busy_signals) == 1
    assert chip_texts == ["idle"]


def test_on_job_finished_pipeline_failure_emits_failed_chip_and_log(qtbot):
    c = JobController()
    chip_texts = []
    logs = []
    c.chip_text.connect(chip_texts.append)
    c.log_message.connect(logs.append)
    c._on_job_finished(1)
    assert chip_texts == ["failed"]
    assert any("pipeline job failed (rc 1)" in m for m in logs)


def test_on_job_finished_cancelled_emits_idle_chip_no_log(qtbot):
    c = JobController()
    chip_texts = []
    logs = []
    c.chip_text.connect(chip_texts.append)
    c.log_message.connect(logs.append)
    c.runner._was_cancelled = True
    c._on_job_finished(0)
    assert chip_texts == ["idle"]
    assert not any("pipeline job failed" in m for m in logs)


def test_on_job_finished_export_success_logs_and_emits_idle(qtbot):
    c = JobController()
    chip_texts = []
    logs = []
    c.chip_text.connect(chip_texts.append)
    c.log_message.connect(logs.append)
    c._job_kind = "export"
    c._job_game = "ds"
    c._on_job_finished(0)
    assert chip_texts == ["idle"]
    assert any("export: done" in m for m in logs)


def test_on_job_finished_export_failure_logs_and_emits_idle(qtbot):
    c = JobController()
    chip_texts = []
    logs = []
    c.chip_text.connect(chip_texts.append)
    c.log_message.connect(logs.append)
    c._job_kind = "export"
    c._on_job_finished(1)
    assert chip_texts == ["idle"]
    assert any("export: render failed (rc 1)" in m for m in logs)


def test_on_job_finished_resets_job_state(qtbot):
    c = JobController()
    c._job_game = "hzd"
    c._job_kind = "export"
    c._on_job_finished(0)
    assert c._job_game is None
    assert c._job_kind is None


# ---- dump lifecycle ------------------------------------------------------

def test_on_dump_finished_emits_signals_and_logs(qtbot):
    c = JobController()
    chip_texts = []
    logs = []
    batch_results = []
    c.chip_text.connect(chip_texts.append)
    c.log_message.connect(logs.append)
    c.dump_batch_finished.connect(lambda ok, failed: batch_results.append((ok, failed)))
    c._on_dump_finished(5, 1)
    assert chip_texts == ["idle"]
    assert any("dump: done — 5 ok, 1 failed" in m for m in logs)
    assert batch_results == [(5, 1)]


def test_dump_progress_forwarded(qtbot):
    c = JobController()
    progresses = []
    c.dump_progress.connect(lambda done, total: progresses.append((done, total)))
    c.dump.progress.emit(3, 10)
    assert progresses == [(3, 10)]


def test_dump_row_failed_logged(qtbot):
    c = JobController()
    logs = []
    c.log_message.connect(logs.append)
    c.dump.row_failed.emit("line-1", "decode error")
    assert any("dump: line-1: decode error" in m for m in logs)


# ---- properties ----------------------------------------------------------

def test_busy_false_initially(qtbot):
    c = JobController()
    assert c.busy is False
    assert c.dumping is False


def test_busy_true_when_dump_running(qtbot):
    c = JobController()
    c.dump._running = True
    assert c.busy is True
    assert c.dumping is True
    c.dump._running = False


# ---- dump cancel ---------------------------------------------------------

def test_dump_cancel_calls_dump_cancel(qtbot):
    c = JobController()
    cancelled = []
    c.dump.cancel = lambda: cancelled.append(1)
    c.dump_cancel()
    assert cancelled == [1]


# ---- rerun invalidation --------------------------------------------------

def test_rerun_invalidates_bind_when_render_done(qtbot, tmp_path):
    out = os.path.join(str(tmp_path), "out", "hzd")
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, ".done-bind"), "w").close()
    open(os.path.join(out, ".done-render"), "w").close()
    c = JobController()
    c._confirm_rerun = lambda stage: False
    assert c.rerun(["base"], "hzd", str(tmp_path), "catalog") is False


def test_rerun_no_invalidation_when_nothing_done_after(qtbot, tmp_path):
    out = os.path.join(str(tmp_path), "out", "hzd")
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, ".done-catalog"), "w").close()
    c = JobController()
    started = []
    c.runner.start = lambda argv, cwd=None: started.append(argv) or True
    assert c.rerun(["base"], "hzd", str(tmp_path), "bind") is True
    assert started


def test_rerun_unknown_stage_proceeds(qtbot):
    c = JobController()
    started = []
    c.runner.start = lambda argv, cwd=None: started.append(argv) or True
    assert c.rerun(["base"], "ds", ".", "nonexistent") is True
    assert started


# ---- dump_wav logs on start ----------------------------------------------

def test_dump_wav_logs_start_message(qtbot):
    c = JobController()
    logs = []
    c.log_message.connect(logs.append)
    started = []
    c.dump.start = lambda resolver, rows, dest: started.append((rows, dest)) or True
    assert c.dump_wav(None, [("id1", "a.wav")], "/tmp") is True
    assert any("dump: decoding 1 line(s) to /tmp" in m for m in logs)
    assert len(started) == 1


def test_dump_wav_emits_busy_changed_on_start(qtbot):
    c = JobController()
    busy_signals = []
    c.busy_changed.connect(lambda: busy_signals.append(1))
    c.dump.start = lambda resolver, rows, dest: True
    c.dump_wav(None, [("id1", "a.wav")], "/tmp")
    assert len(busy_signals) == 1
