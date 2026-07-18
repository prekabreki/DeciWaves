"""Pipeline view (issue #67): the stage strip and coverage + issues panel arrive with
#69. The skeleton wired the collapsible log console the job runner streams into (spec
§5.3); #68 adds the Setup & Doctor section at the top (spec §2/§3)."""
from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QToolButton, QVBoxLayout, QWidget

from deciwaves.gui.views.setup import SetupDoctorView


class PipelineView(QWidget):
    def __init__(self, base: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setup_doctor = SetupDoctorView(base)
        # setup emits no progress; stream its raw stdout into the shared log console so the
        # ~200 MB cold fetch shows live motion (spec §5.3). Doctor's JSON stays out of it.
        self.setup_doctor.setup.output.connect(self.append_log)

        self._toggle = QToolButton()
        self._toggle.setCheckable(True)
        self._toggle.setChecked(True)
        self._toggle.setText("▾ Log console")
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self.setup_doctor)
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
