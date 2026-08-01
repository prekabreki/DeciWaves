"""Two-view shell + global bar + log-console wiring (#67). Skips without [gui]."""
import sys

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from deciwaves.gui.export import DumpRunner  # noqa: E402
from deciwaves.gui.jobs import JobRunner  # noqa: E402
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
    assert not w.library._job_running_banner.isHidden()

    w._controller.busy_changed.emit(False)
    assert w.bar._busy_bar.isHidden()
    assert w.library._job_running_banner.isHidden()


def test_busy_clear_keeps_failed_chip_colour(qtbot):
    """#296: busy_changed must not overwrite the chip colour set by set_job_chip."""
    w = MainWindow()
    qtbot.addWidget(w)
    w._controller.job_chip_changed.emit("failed")
    w._controller.busy_changed.emit(True)
    w._controller.busy_changed.emit(False)
    assert w.bar._chip.text() == "failed"
    assert "color: #b00020" in w.bar._chip.styleSheet()


# --- closeEvent confirm dialog with running job (#295) ----------------------


@pytest.mark.allow_dialogs
def test_close_with_running_pipeline_decline_ignores_event(qtbot, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    monkeypatch.setattr(JobRunner, "is_running", property(lambda self: True))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: QMessageBox.No)
    cancelled = []
    monkeypatch.setattr(w._controller.runner, "cancel", lambda: cancelled.append(True))
    monkeypatch.setattr(w._controller.dump, "cancel", lambda: cancelled.append(True))

    w.close()

    assert cancelled == []


@pytest.mark.allow_dialogs
def test_close_with_running_pipeline_accept_cancels_before_persist(qtbot, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    monkeypatch.setattr(JobRunner, "is_running", property(lambda self: True))
    events = []
    monkeypatch.setattr(w._controller.runner, "cancel",
                        lambda: events.append("cancel_runner"))
    monkeypatch.setattr(w._controller.dump, "cancel",
                        lambda: events.append("cancel_dump"))
    original_setValue = w._settings.setValue
    def _setValue(key, val):
        events.append(f"setValue:{key}")
        return original_setValue(key, val)
    monkeypatch.setattr(w._settings, "setValue", _setValue)

    w.close()

    assert events.count("cancel_runner") == 1
    cancel_idx = events.index("cancel_runner")
    setvalue_indices = [i for i, e in enumerate(events) if e.startswith("setValue:")]
    assert setvalue_indices
    assert all(cancel_idx < si for si in setvalue_indices), \
        f"cancel_runner must come before all setValue calls, got {events}"


@pytest.mark.allow_dialogs
def test_close_with_running_dump_accept_cancels_before_persist(qtbot, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    monkeypatch.setattr(DumpRunner, "is_running", property(lambda self: True))
    events = []
    monkeypatch.setattr(w._controller.runner, "cancel",
                        lambda: events.append("cancel_runner"))
    monkeypatch.setattr(w._controller.dump, "cancel",
                        lambda: events.append("cancel_dump"))
    original_setValue = w._settings.setValue
    def _setValue(key, val):
        events.append(f"setValue:{key}")
        return original_setValue(key, val)
    monkeypatch.setattr(w._settings, "setValue", _setValue)

    w.close()

    assert events.count("cancel_dump") == 1
    cancel_idx = events.index("cancel_dump")
    setvalue_indices = [i for i, e in enumerate(events) if e.startswith("setValue:")]
    assert setvalue_indices
    assert all(cancel_idx < si for si in setvalue_indices), \
        f"cancel_dump must come before all setValue calls, got {events}"


@pytest.mark.allow_dialogs
def test_close_with_both_running_accept_cancels_runner_then_dump_before_persist(qtbot, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    monkeypatch.setattr(JobRunner, "is_running", property(lambda self: True))
    monkeypatch.setattr(DumpRunner, "is_running", property(lambda self: True))
    events = []
    monkeypatch.setattr(w._controller.runner, "cancel",
                        lambda: events.append("cancel_runner"))
    monkeypatch.setattr(w._controller.dump, "cancel",
                        lambda: events.append("cancel_dump"))
    original_setValue = w._settings.setValue
    def _setValue(key, val):
        events.append(f"setValue:{key}")
        return original_setValue(key, val)
    monkeypatch.setattr(w._settings, "setValue", _setValue)

    w.close()

    assert events.count("cancel_runner") == 1
    assert events.count("cancel_dump") == 1
    runner_idx = events.index("cancel_runner")
    dump_idx = events.index("cancel_dump")
    assert runner_idx < dump_idx, f"runner cancel must come before dump cancel, got {events}"
    setvalue_indices = [i for i, e in enumerate(events) if e.startswith("setValue:")]
    assert setvalue_indices
    assert all(dump_idx < si for si in setvalue_indices), \
        f"dump cancel must come before all setValue calls, got {events}"
