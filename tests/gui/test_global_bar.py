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


# --- workspace picker (monkeypatched QFileDialog, no real dialog) ------------
# workspace_changed signal assertion gated until #123 lands.


def test_workspace_picker_updates_field(qtbot, monkeypatch, tmp_path):
    bar = GlobalBar()
    qtbot.addWidget(bar)
    picked = str(tmp_path / "output")
    monkeypatch.setattr("deciwaves.gui.global_bar.QFileDialog.getExistingDirectory",
                        staticmethod(lambda *a, **k: picked))
    bar._browse.click()
    assert bar.workspace() == picked
    # TODO: once #123 lands, also assert workspace_changed emitted(picked)


def test_workspace_picker_cancel_keeps_original_field(qtbot, monkeypatch):
    bar = GlobalBar()
    qtbot.addWidget(bar)
    original = r"C:\original\workspace"
    bar.set_workspace(original)
    monkeypatch.setattr("deciwaves.gui.global_bar.QFileDialog.getExistingDirectory",
                        staticmethod(lambda *a, **k: ""))
    bar._browse.click()
    assert bar.workspace() == original


# --- set_install_status ------------------------------------------------------
# Three-state + glyph mapping pending #122; test the current two-state contract.


def test_set_install_status_two_state(qtbot):
    bar = GlobalBar()
    qtbot.addWidget(bar)
    bar.set_install_status("Ready", ok=True)
    assert bar._status.text() == "Ready"
    assert "color: #167f3b" in bar._status.styleSheet()
    assert "color: #b00020" not in bar._status.styleSheet()

    bar.set_install_status("Missing", ok=False)
    assert bar._status.text() == "Missing"
    assert "color: #b00020" in bar._status.styleSheet()
    assert "color: #167f3b" not in bar._status.styleSheet()
