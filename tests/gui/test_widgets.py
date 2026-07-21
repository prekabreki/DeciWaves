"""Reusable onboarding widgets (#112): a muted ⓘ help-icon carrying a tooltip +
whats-this, and an Optional/Needed pill. Skips without [gui]."""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel  # noqa: E402

from deciwaves.gui.widgets import CollapsibleSection, HelpIcon, Pill  # noqa: E402


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


def test_collapsible_hides_body_when_collapsed(qtbot):
    body = QLabel("detail")
    section = CollapsibleSection("Setup", body)
    qtbot.addWidget(section)
    section.show()
    section.set_collapsed(True)
    assert section.is_collapsed() is True
    assert body.isVisibleTo(section) is False
    section.set_collapsed(False)
    assert body.isVisibleTo(section) is True


def test_collapsible_shows_summary_text(qtbot):
    section = CollapsibleSection("Doctor", QLabel("rows"))
    qtbot.addWidget(section)
    section.set_summary("3 checks OK · 2 optional")
    assert "3 checks OK" in section.summary_text()
