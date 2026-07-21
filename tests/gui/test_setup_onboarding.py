"""Onboarding annotations on the Setup/Doctor panels (#112): the Optional pill on
CUDA for DS, and the BYO help-icon in the Setup header. Skips without [gui]."""
import pytest

pytest.importorskip("PySide6")

from deciwaves.gui.views.setup import DoctorPanel, SetupDoctorView, SetupScreen  # noqa: E402
from deciwaves.gui.widgets import HelpIcon, Pill  # noqa: E402

_CUDA_ABSENT = {"ok": True, "checks": [
    {"name": "cuda", "ok": True, "status": "unavailable", "message": "", "fix": ""}]}


def test_doctor_renders_optional_pill_for_cuda_on_ds(qtbot):
    panel = DoctorPanel()
    qtbot.addWidget(panel)
    panel.set_game("ds")
    panel.render_payload(_CUDA_ABSENT)
    pills = [p.text() for p in panel.findChildren(Pill)]
    assert "Optional" in pills


def test_doctor_no_optional_pill_for_cuda_on_hzd(qtbot):
    panel = DoctorPanel()
    qtbot.addWidget(panel)
    panel.set_game("hzd")
    panel.render_payload(_CUDA_ABSENT)
    pills = [p.text() for p in panel.findChildren(Pill)]
    assert "Optional" not in pills


def test_setup_header_has_byo_help_icon(qtbot):
    screen = SetupScreen()
    qtbot.addWidget(screen)
    texts = [h.help_text() for h in screen.findChildren(HelpIcon)]
    assert any("Bring Your Own" in t for t in texts)


_ALL_READY = {"ok": True, "checks": [
    {"name": "vgmstream", "ok": True, "status": "ok", "message": "", "fix": ""},
    {"name": "VGAudio", "ok": True, "status": "ok", "message": "", "fix": ""},
    {"name": "ffmpeg", "ok": True, "status": "ok", "message": "", "fix": ""},
    {"name": "cuda", "ok": True, "status": "unavailable", "message": "", "fix": ""},
]}
_TOOL_MISSING = {"ok": False, "checks": [
    {"name": "vgmstream", "ok": False, "status": "broken", "message": "", "fix": "run setup"},
]}


def test_sections_collapse_when_ready(qtbot):
    view = SetupDoctorView()
    qtbot.addWidget(view)
    view.doctor.set_game("ds")
    view.doctor.render_payload(_ALL_READY)
    view.apply_readiness_summary()
    assert view.setup_section.is_collapsed() is True
    assert "Tools ready" in view.setup_section.summary_text()


def test_setup_section_expands_when_tool_missing(qtbot):
    view = SetupDoctorView()
    qtbot.addWidget(view)
    view.doctor.set_game("ds")
    view.doctor.render_payload(_TOOL_MISSING)
    view.apply_readiness_summary()
    assert view.setup_section.is_collapsed() is False
    assert "200 MB" in view.setup_section.summary_text()
