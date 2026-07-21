"""The onboarding guide rail (#112): a slim, always-present strip that renders a
:class:`guide_model.Journey`. Exactly one step -- the live one -- is a button; the
rest are inert done/todo labels. All decision logic is Qt-free in
:mod:`guide_model`; this is the thin renderer + the single ``action_requested``
signal the shell turns into a tab-switch + focus."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from deciwaves.gui.guide_model import ActionTarget, Journey, Step
from deciwaves.gui.theme import NEUTRAL, OK


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()


class GuideRail(QWidget):
    action_requested = Signal(object)  # emits an ActionTarget

    def __init__(self, parent=None):
        super().__init__(parent)
        self._action: ActionTarget | None = None

        self._steps_row = QHBoxLayout()
        self._steps_row.setContentsMargins(0, 0, 0, 0)
        steps_host = QWidget()
        steps_host.setLayout(self._steps_row)

        self._hint = QLabel("")
        self._hint.setWordWrap(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 2, 6, 2)
        outer.addWidget(steps_host)
        outer.addWidget(self._hint)

    def set_journey(self, journey: Journey) -> None:
        _clear(self._steps_row)
        self._action = journey.next_action
        self._hint.setText(journey.next_hint)
        if not journey.steps:  # game not owned -> hint only
            return
        for i, step in enumerate(journey.steps):
            if i:
                self._steps_row.addWidget(self._separator())
            self._steps_row.addWidget(self._step_widget(step, journey.next_action))
        self._steps_row.addStretch(1)

    def current_action(self) -> ActionTarget | None:
        return self._action

    def _step_widget(self, step: Step, action: ActionTarget | None) -> QWidget:
        if step.current and action is not None:
            btn = QPushButton(f"{step.label} →")
            btn.setToolTip("Take me to the next step")
            btn.clicked.connect(lambda: self.action_requested.emit(action))
            return btn
        mark = "✓" if step.done else "○"
        label = QLabel(f"{mark} {step.label}")
        label.setStyleSheet(f"color: {OK if step.done else NEUTRAL};")
        return label

    def _separator(self) -> QLabel:
        sep = QLabel("›")
        sep.setStyleSheet(f"color: {NEUTRAL};")
        return sep
