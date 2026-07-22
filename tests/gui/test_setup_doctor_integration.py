"""Setup & Doctor wired into the shell (#68, spec §2/§3): the Pipeline view hosts the
setup/doctor section, and changing the game in the global bar re-grades the Doctor panel
so the promoted GPU items follow the selected game. Skips without [gui]."""
import pytest

pytest.importorskip("PySide6")
from deciwaves.gui.doctor_model import SEV_NEUTRAL, SEV_WARN  # noqa: E402
from deciwaves.gui.shell import MainWindow  # noqa: E402

_CUDA_ABSENT = {"ok": True, "checks": [
    {"name": "cuda", "ok": True, "status": "unavailable", "message": "", "fix": ""}]}


def test_pipeline_view_hosts_setup_and_doctor(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    assert w.pipeline.setup_doctor.setup is not None
    assert w.pipeline.setup_doctor.doctor is not None


def test_changing_game_regrades_the_doctor_panel(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    doctor = w.pipeline.setup_doctor.doctor
    doctor.render_payload(_CUDA_ABSENT)

    w.bar.select_game("ds")
    assert doctor.severity_of("cuda") == SEV_NEUTRAL   # DS: informational
    w.bar.select_game("fw")
    assert doctor.severity_of("cuda") == SEV_WARN       # FW: promoted readiness item


def test_log_console_still_present_after_adding_setup_doctor(qtbot):
    # the skeleton's collapsible log console (#67) must survive the new section
    w = MainWindow()
    qtbot.addWidget(w)
    w._controller.runner.output.emit("still-here\n")
    assert "still-here" in w.pipeline.log_text()


def test_setup_output_streams_into_the_log_console(qtbot):
    # setup emits no download progress; its raw stdout must still show live motion in the
    # shared log console during the ~200 MB cold fetch (spec §5.3).
    w = MainWindow()
    qtbot.addWidget(w)
    w.pipeline.setup_doctor.setup._runner.output.emit("setup-live\n")
    assert "setup-live" in w.pipeline.log_text()


# --- M6: mutual exclusion both directions -----------------------------------

def test_setup_busy_disables_pipeline_controls(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    setup = w.pipeline.setup_doctor.setup
    setup._busy = True
    setup.busy_changed.emit(True)
    assert w.pipeline.controls._scan_btn.isEnabled() is False
    assert w.pipeline.controls._bind_btn.isEnabled() is False


def test_setup_idle_re_enables_pipeline_controls(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    setup = w.pipeline.setup_doctor.setup
    setup._busy = True
    setup.busy_changed.emit(True)
    assert w.pipeline.controls._scan_btn.isEnabled() is False
    setup._busy = False
    setup.busy_changed.emit(False)
    assert w.pipeline.controls._scan_btn.isEnabled() is True
    assert w.pipeline.controls._bind_btn.isEnabled() is True


def test_pipeline_busy_disables_setup_buttons(qtbot, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    setup = w.pipeline.setup_doctor.setup
    monkeypatch.setattr(type(w._controller.runner), "is_running", property(lambda _self: True))
    w._sync_running()
    assert setup._run_btn.isEnabled() is False
    assert setup._redownload_btn.isEnabled() is False
    assert setup._recheck_btn.isEnabled() is False


def test_pipeline_idle_re_enables_setup_buttons(qtbot, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    setup = w.pipeline.setup_doctor.setup
    monkeypatch.setattr(type(w._controller.runner), "is_running", property(lambda _self: True))
    w._sync_running()
    assert setup._run_btn.isEnabled() is False
    monkeypatch.setattr(type(w._controller.runner), "is_running", property(lambda _self: False))
    w._sync_running()
    assert setup._run_btn.isEnabled() is True
    assert setup._redownload_btn.isEnabled() is True
    assert setup._recheck_btn.isEnabled() is True


def test_busy_setup_blocks_pipeline_and_strip(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    setup = w.pipeline.setup_doctor.setup
    setup._busy = True
    setup.busy_changed.emit(True)
    assert w.pipeline.strip.rerun_enabled() is False


def test_busy_pipeline_blocks_export(qtbot, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    monkeypatch.setattr(type(w._controller.runner), "is_running", property(lambda _self: True))
    w._sync_running()
    assert w.library.export._mp3_btn.isEnabled() is False
