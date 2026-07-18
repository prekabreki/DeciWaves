"""Pipeline view (issue #67): the stage strip, coverage + issues panel, and the
collapsible log console arrive across #69; the skeleton wires the log console the job
runner streams into (spec §5.3)."""
from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QToolButton, QVBoxLayout, QWidget


class PipelineView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._toggle = QToolButton()
        self._toggle.setCheckable(True)
        self._toggle.setChecked(True)
        self._toggle.setText("▾ Log console")
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self._toggle)
        layout.addWidget(self._log, 1)
        self._toggle.toggled.connect(self._on_toggle)

    def _on_toggle(self, shown: bool) -> None:
        self._log.setVisible(shown)
        self._toggle.setText(("▾ " if shown else "▸ ") + "Log console")

    def append_log(self, text: str) -> None:
        """Append a raw stdout/stderr chunk without inserting extra newlines, keeping
        the view scrolled to the tail."""
        self._log.moveCursor(QTextCursor.End)
        self._log.insertPlainText(text)
        self._log.moveCursor(QTextCursor.End)

    def log_text(self) -> str:
        return self._log.toPlainText()
