"""The shell wires the guide rail (#112): it computes the journey from the current
game/workspace/doctor state, and the rail's action navigates (tab-switch/focus)
without running a job. Skips without [gui]."""
import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from deciwaves.gui.guide_model import ActionTarget  # noqa: E402
from deciwaves.gui.shell import MainWindow  # noqa: E402


def _win(qtbot, tmp_path):
    settings = QSettings("DeciWavesTest", "gui_guide")
    settings.clear()
    w = MainWindow(settings=settings)
    qtbot.addWidget(w)
    w.bar.set_workspace(str(tmp_path))
    return w


def test_curate_action_switches_to_library_tab(qtbot, tmp_path):
    w = _win(qtbot, tmp_path)
    w._on_guide_action(ActionTarget.CURATE)
    assert w.views.currentIndex() == 1  # Library


def test_workspace_action_focuses_workspace_field(qtbot, tmp_path):
    w = _win(qtbot, tmp_path)
    w.show()
    w._on_guide_action(ActionTarget.WORKSPACE)
    QApplication.processEvents()
    assert w.views.currentIndex() == 0  # Pipeline
    assert w.bar._workspace.hasFocus()


def test_refresh_guide_sets_a_journey_hint(qtbot, tmp_path):
    w = _win(qtbot, tmp_path)
    w._refresh_guide()
    assert w.guide._hint.text() != ""
