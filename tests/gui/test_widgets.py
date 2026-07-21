"""Reusable onboarding widgets (#112): a muted ⓘ help-icon carrying a tooltip +
whats-this, and an Optional/Needed pill. Skips without [gui]."""
import pytest

pytest.importorskip("PySide6")

from deciwaves.gui.widgets import HelpIcon, Pill  # noqa: E402


def test_help_icon_carries_text_in_tooltip_and_whatsthis(qtbot):
    icon = HelpIcon("Bring Your Own — you supply your own game files.")
    qtbot.addWidget(icon)
    assert "Bring Your Own" in icon.help_text()
    assert "Bring Your Own" in icon.toolTip()
    assert "Bring Your Own" in icon.whatsThis()


def test_pill_shows_label(qtbot):
    pill = Pill("Optional")
    qtbot.addWidget(pill)
    assert pill.text() == "Optional"
