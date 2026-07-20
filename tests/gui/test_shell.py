"""Two-view shell + global bar + log-console wiring (#67). Skips without [gui]."""
import sys

import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QCloseEvent  # noqa: E402
from deciwaves.gui.shell import MainWindow  # noqa: E402

_SLOW = "import time\nfor i in range(200):\n print(i, flush=True); time.sleep(0.02)"


def test_window_builds_with_two_views(qtbot):
    w = MainWindow(); qtbot.addWidget(w)
    assert w.bar.current_game() in ("ds", "hzd", "fw")
    assert w.views.count() == 2                       # Pipeline + Library


def test_game_change_updates_install_status(qtbot):
    w = MainWindow(); qtbot.addWidget(w)
    w.bar.select_game("hzd")
    assert w.bar._status.text() != ""                 # some found/not-configured line rendered


def test_runner_output_appends_to_log(qtbot):
    w = MainWindow(); qtbot.addWidget(w)
    w.runner.output.emit("hello-log\n")
    assert "hello-log" in w.pipeline.log_text()


def test_job_chip_reflects_running_then_idle(qtbot):
    w = MainWindow(); qtbot.addWidget(w)
    w.runner.started.emit()
    assert w.bar._chip.text() != "idle"
    w.runner.finished.emit(0)
    assert w.bar._chip.text() == "idle"


def test_pipeline_job_failure_shows_failed_chip_and_message(qtbot):
    w = MainWindow(); qtbot.addWidget(w)
    w.runner.started.emit()
    assert w.bar._chip.text() != "idle"
    w.runner.finished.emit(1)
    assert w.bar._chip.text() == "failed"
    assert "failed (rc 1)" in w.pipeline.log_text()


def test_pipeline_log_console_is_collapsible(qtbot):
    # isHidden() reflects an explicit hide, independent of whether the window is shown.
    w = MainWindow(); qtbot.addWidget(w)
    w.pipeline._toggle.setChecked(True)
    assert w.pipeline._log.isHidden() is False        # expanded -> console shown
    w.pipeline._toggle.setChecked(False)
    assert w.pipeline._log.isHidden() is True          # collapsed -> console hidden


# --- acceptance: a real subprocess streams through the shell and cancels cleanly ---

def test_real_command_streams_into_log_console(qtbot):
    w = MainWindow(); qtbot.addWidget(w)
    with qtbot.waitSignal(w.runner.finished, timeout=5000):
        assert w.runner.start([sys.executable, "-c", "print('into-console', flush=True)"]) is True
    assert "into-console" in w.pipeline.log_text()
    assert w.bar._chip.text() == "idle"                # chip reset when the job finishes


def test_cancel_from_shell_stops_the_job_and_resets_chip(qtbot):
    w = MainWindow(); qtbot.addWidget(w)
    w.runner.start([sys.executable, "-c", _SLOW])
    assert w.bar._chip.text() != "idle"                # running: chip shows the job
    with qtbot.waitSignal(w.runner.finished, timeout=5000):
        w.runner.cancel()
    assert w.runner.is_running is False
    assert w.bar._chip.text() == "idle"


# --- closeEvent (issue #116) -----------------------------------------------


def test_close_event_no_job_accepts(qtbot):
    w = MainWindow(); qtbot.addWidget(w)
    event = QCloseEvent()
    w.closeEvent(event)
    assert event.isAccepted()


def test_close_event_with_job_confirm_no_ignores(qtbot):
    from unittest.mock import patch
    from PySide6.QtWidgets import QMessageBox

    w = MainWindow(); qtbot.addWidget(w)
    w.runner.start([sys.executable, "-c", _SLOW])
    with patch("deciwaves.gui.shell.QMessageBox.question", return_value=QMessageBox.No):
        event = QCloseEvent()
        w.closeEvent(event)
        assert not event.isAccepted()
    assert w.runner.is_running
    w.runner.cancel()
    with qtbot.waitSignal(w.runner.finished, timeout=5000):
        pass


def test_close_event_with_job_confirm_yes_cancels(qtbot):
    from unittest.mock import patch
    from PySide6.QtWidgets import QMessageBox

    w = MainWindow(); qtbot.addWidget(w)
    w.runner.start([sys.executable, "-c", _SLOW])
    with patch("deciwaves.gui.shell.QMessageBox.question", return_value=QMessageBox.Yes):
        event = QCloseEvent()
        w.closeEvent(event)
        assert event.isAccepted()
    assert not w.runner.is_running
