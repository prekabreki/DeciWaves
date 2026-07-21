"""Thin guide-rail view (#112): renders a guide_model.Journey, exposes the single
live step as a button, and emits action_requested with its ActionTarget. Skips
without [gui]."""
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QPushButton  # noqa: E402

from deciwaves.cli.doctor import Availability  # noqa: E402
from deciwaves.gui.guide_model import ActionTarget, build_journey  # noqa: E402
from deciwaves.gui.views.guide_rail import GuideRail  # noqa: E402


def _journey(**kw):
    base = dict(doctor_payload=None, game="ds", game_label="Death Stranding",
                game_status=Availability.OK, workspace="")
    base.update(kw)
    return build_journey(**base)


def test_live_step_renders_as_button_and_emits_target(qtbot):
    rail = GuideRail()
    qtbot.addWidget(rail)
    rail.set_journey(_journey())  # SETUP is the live step
    buttons = rail.findChildren(QPushButton)
    assert len(buttons) == 1
    assert buttons[0].text().startswith("Setup")
    with qtbot.waitSignal(rail.action_requested) as blocker:
        buttons[0].click()
    assert blocker.args == [ActionTarget.SETUP]


def test_not_owned_game_shows_hint_no_step_buttons(qtbot):
    rail = GuideRail()
    qtbot.addWidget(rail)
    rail.set_journey(_journey(game_status=Availability.NOT_CONFIGURED))
    assert rail.findChildren(QPushButton) == []
    assert rail.current_action() is None
