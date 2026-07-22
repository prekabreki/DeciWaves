"""Small reusable onboarding widgets (#112), shared across Setup/Doctor/coverage/
issues/game-panel so the look and behaviour are defined and tested once.

- :class:`HelpIcon` -- a muted ⓘ label carrying a rich tooltip + whats-this, for
  expanding jargon at its point of use.
- :class:`Pill` -- a small "Optional"/"Needed" badge that makes the per-game
  optional-vs-required framing unmissable.
- :class:`CollapsibleSection` -- a header (▾/▸ toggle + summary) over a body that
  hides on collapse, for the first-run declutter of the long Setup/Doctor panels."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

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


class CollapsibleSection(QWidget):
    """A ▾/▸ header (title + optional one-line summary) over a *body* that hides
    when collapsed. Used to declutter the long Setup/Doctor panels on first run:
    a healthy returning user sees a compact summary; a broken/first-run user sees
    the section expanded where the problem is (#112)."""

    def __init__(self, title: str, body: QWidget, parent=None):
        super().__init__(parent)
        self._body = body
        self._toggle = QToolButton()
        self._toggle.setCheckable(True)
        self._toggle.setChecked(True)
        self._toggle.setStyleSheet("border: none;")
        self._title = title
        self._summary = QLabel("")
        self._summary.setStyleSheet(f"color: {NEUTRAL};")

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self._toggle)
        header.addWidget(self._summary, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(header)
        outer.addWidget(self._body)

        self._toggle.toggled.connect(self._on_toggled)
        self._render_header(expanded=True)

    def _on_toggled(self, expanded: bool) -> None:
        self._body.setVisible(expanded)
        self._render_header(expanded)

    def _render_header(self, expanded: bool) -> None:
        arrow = "▾" if expanded else "▸"
        self._toggle.setText(f"{arrow} {self._title}")

    def set_summary(self, text: str) -> None:
        self._summary.setText(text)

    def summary_text(self) -> str:
        return self._summary.text()

    def set_collapsed(self, collapsed: bool) -> None:
        self._toggle.setChecked(not collapsed)

    def is_collapsed(self) -> bool:
        return not self._toggle.isChecked()

    def expand(self) -> None:
        self._toggle.setChecked(True)


_HIGHLIGHT_COLOUR = "#1b6ec2"
_HIGHLIGHT_DURATION_MS = 800


def flash_highlight(widget: QWidget) -> None:
    widget.setStyleSheet(f"border: 2px solid {_HIGHLIGHT_COLOUR};")
    QTimer.singleShot(_HIGHLIGHT_DURATION_MS, lambda: widget.setStyleSheet(""))
