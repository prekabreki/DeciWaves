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
    w.runner.output.emit("still-here\n")
    assert "still-here" in w.pipeline.log_text()


def test_setup_output_streams_into_the_log_console(qtbot):
    # setup emits no download progress; its raw stdout must still show live motion in the
    # shared log console during the ~200 MB cold fetch (spec §5.3).
    w = MainWindow()
    qtbot.addWidget(w)
    w.pipeline.setup_doctor.setup._runner.output.emit("setup-live\n")
    assert "setup-live" in w.pipeline.log_text()
