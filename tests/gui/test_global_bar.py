"""Global bar widget tests: tooltips, placeholder, and basic accessors."""
import pytest

pytest.importorskip("PySide6")
from deciwaves.gui.global_bar import GlobalBar  # noqa: E402


def test_workspace_has_tooltip_and_placeholder(qtbot):
    bar = GlobalBar()
    qtbot.addWidget(bar)
    assert bar._workspace.toolTip(), "Workspace field should have a non-empty tooltip"
    assert bar._workspace.placeholderText(), "Workspace field should have a non-empty placeholder"


def test_game_combo_has_tooltip(qtbot):
    bar = GlobalBar()
    qtbot.addWidget(bar)
    assert bar._combo.toolTip(), "Game combo should have a non-empty tooltip"


def test_browse_button_has_tooltip(qtbot):
    bar = GlobalBar()
    qtbot.addWidget(bar)
    assert bar._browse.toolTip(), "Browse button should have a non-empty tooltip"
