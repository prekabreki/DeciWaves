"""Small reusable onboarding widgets (#112), shared across Setup/Doctor/coverage/
issues/game-panel so the look and behaviour are defined and tested once.

- :class:`HelpIcon` -- a muted ⓘ label carrying a rich tooltip + whats-this, for
  expanding jargon at its point of use.
- :class:`Pill` -- a small "Optional"/"Needed" badge that makes the per-game
  optional-vs-required framing unmissable.
- :class:`CollapsibleSection` -- a header (▾/▸ toggle + summary) over a body that
  hides on collapse, for the first-run declutter of the long Setup/Doctor panels."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QToolButton, QVBoxLayout, QWidget  # noqa: F401 (widened in Issue F)

from deciwaves.gui.theme import NEUTRAL, WARN


class HelpIcon(QLabel):
    """A muted ⓘ that shows *text* on hover (tooltip) and via What's-This."""

    def __init__(self, text: str, parent=None):
        super().__init__("ⓘ", parent)
        self.setToolTip(text)
        self.setWhatsThis(text)
        self.setStyleSheet(f"color: {NEUTRAL};")
        self.setCursor(Qt.WhatsThisCursor)

    def help_text(self) -> str:
        return self.toolTip()


_PILL_TONES = {"optional": NEUTRAL, "needed": WARN}


class Pill(QLabel):
    """A small rounded badge; *tone* picks the colour (``optional``/``needed``)."""

    def __init__(self, label: str, tone: str = "optional", parent=None):
        super().__init__(label, parent)
        colour = _PILL_TONES.get(tone, NEUTRAL)
        self.setStyleSheet(
            f"color: white; background: {colour}; "
            "border-radius: 6px; padding: 0px 6px;")
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
