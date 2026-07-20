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


# --- QSettings persistence (#128) ------------------------------------------

def test_settings_persist_and_restore(qtbot, tmp_path):
    """Write settings, reconstruct, assert restored. Uses a temp QSettings scope
    so the test never touches the real registry/ini file."""
    from PySide6.QtCore import QSettings, QByteArray

    ini = tmp_path / "gui.ini"
    test_settings = QSettings(str(ini), QSettings.IniFormat)

    # --- first window: set state and save ---
    w1 = MainWindow(settings=test_settings)
    qtbot.addWidget(w1)

    w1.bar.set_workspace(r"C:\test\workspace")
    w1.bar.select_game("hzd")

    header1 = w1.library.horizontalHeader()
    header1.resizeSection(0, 40)
    header1.resizeSection(1, 30)
    header1.resizeSection(2, 180)

    w1.library.restore_sort("speaker", True)

    w1._save_state()

    # --- second window: should restore saved state ---
    w2 = MainWindow(settings=test_settings)
    qtbot.addWidget(w2)

    assert w2.bar.current_game() == "hzd"
    assert w2.bar.workspace() == r"C:\test\workspace"
    assert w2.library.sort_key() == "speaker"
    assert w2.library.sort_desc() is True
    # column widths (sectionCount may be 0 on an unpopulated model; skip if so)
    if w2.library.horizontalHeader().count() > 2:
        assert w2.library.horizontalHeader().sectionSize(0) == 40
        assert w2.library.horizontalHeader().sectionSize(1) == 30
        assert w2.library.horizontalHeader().sectionSize(2) == 180


def test_settings_first_run_no_crash(qtbot, tmp_path):
    """A fresh QSettings with no saved keys should not crash and should
    produce sensible defaults (DS game, empty workspace)."""
    from PySide6.QtCore import QSettings

    ini = tmp_path / "fresh.ini"
    fresh_settings = QSettings(str(ini), QSettings.IniFormat)

    w = MainWindow(settings=fresh_settings)
    qtbot.addWidget(w)

    assert w.bar.current_game() == "ds"
    assert w.bar.workspace() == ""
