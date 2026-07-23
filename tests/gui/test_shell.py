"""Two-view shell + global bar + log-console wiring (#67). Skips without [gui]."""
import sys

import pytest

pytest.importorskip("PySide6")
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
    w._controller.runner.output.emit("hello-log\n")
    assert "hello-log" in w.pipeline.log_text()


def test_job_chip_reflects_running_then_idle(qtbot):
    w = MainWindow(); qtbot.addWidget(w)
    w._controller.runner.started.emit()
    assert w.bar._chip.text() != "idle"
    w._controller.runner.finished.emit(0)
    assert w.bar._chip.text() == "idle"


def test_pipeline_job_failure_shows_failed_chip_and_message(qtbot):
    w = MainWindow(); qtbot.addWidget(w)
    w._controller.runner.started.emit()
    assert w.bar._chip.text() != "idle"
    w._controller.runner.finished.emit(1)
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
    with qtbot.waitSignal(w._controller.runner.finished, timeout=5000):
        assert w._controller.runner.start([sys.executable, "-c", "print('into-console', flush=True)"]) is True
    assert "into-console" in w.pipeline.log_text()
    assert w.bar._chip.text() == "idle"                # chip reset when the job finishes


def test_cancel_from_shell_stops_the_job_and_resets_chip(qtbot):
    w = MainWindow(); qtbot.addWidget(w)
    w._controller.runner.start([sys.executable, "-c", _SLOW])
    assert w.bar._chip.text() != "idle"                # running: chip shows the job
    with qtbot.waitSignal(w._controller.runner.finished, timeout=5000):
        w._controller.runner.cancel()
    assert w._controller.runner.is_running is False
    assert w.bar._chip.text() == "idle"


def test_qsettings_round_trip_saves_and_restores_state(tmp_path, qtbot):
    """Build a MainWindow against an isolated QSettings scope, mutate state,
    close it (triggering closeEvent), then rebuild from the same settings and
    assert restored game/geometry/header state match what was saved."""
    from PySide6.QtCore import QSettings

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    w1 = MainWindow(settings=settings)
    qtbot.addWidget(w1)
    w1.setGeometry(200, 200, 1000, 800)

    w1.bar.select_game("hzd")
    w1.bar.set_workspace("/test/workspace")
    w1_header = w1.library._table.horizontalHeader().saveState()

    w1.close()

    assert settings.value("game") == "hzd"
    assert settings.value("workspace") == "/test/workspace"
    assert settings.value("window/geometry") is not None
    assert settings.value("library/header_state") == w1_header

    w2 = MainWindow(settings=settings)
    qtbot.addWidget(w2)

    assert w2.bar.current_game() == "hzd"
    assert w2.bar.workspace() == "/test/workspace"

    qtbot.wait(50)
    assert w2.library._table.horizontalHeader().saveState() == w1_header


def test_minimum_width_fits_1366(qtbot):
    """The library table must not force the window beyond 1366px (#126 follow-up, #173).
    Column widths are set explicitly so minimumSizeHint is independent of data content."""
    w = MainWindow()
    qtbot.addWidget(w)
    assert w.minimumSizeHint().width() <= 1366


# --- busy propagation to bar + library (#278) --------------------------------


def test_busy_changed_propagates_to_bar_and_library(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    assert w.bar._busy_bar.isHidden()
    assert w.library._job_running_banner.isHidden()

    w._controller.busy_changed.emit(True)
    assert not w.bar._busy_bar.isHidden()
    assert "color: #1b6ec2" in w.bar._chip.styleSheet()
    assert not w.library._job_running_banner.isHidden()

    w._controller.busy_changed.emit(False)
    assert w.bar._busy_bar.isHidden()
    assert "color: #666666" in w.bar._chip.styleSheet()
    assert w.library._job_running_banner.isHidden()
