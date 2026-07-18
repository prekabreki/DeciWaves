"""Pipeline view: Setup & Doctor section (#68), the per-game stage strip + Scan/Bind
controls + coverage bar + issues panel (#69), and the collapsible log console the job
runner streams into (#67, spec §5.3). The shell owns the single JobRunner and turns this
view's intent signals (scan/process/rerun/escalate) into pipeline jobs."""
from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QToolButton, QVBoxLayout, QWidget

from deciwaves.gui.pipeline_model import has_gpu_stage
from deciwaves.gui.views.pipeline_panels import (
    CoverageBar,
    IssuesPanel,
    PipelineControls,
    StageStrip,
)
from deciwaves.gui.views.setup import SetupDoctorView


class PipelineView(QWidget):
    def __init__(self, base: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setup_doctor = SetupDoctorView(base)
        # setup emits no progress; stream its raw stdout into the shared log console so the
        # ~200 MB cold fetch shows live motion (spec §5.3). Doctor's JSON stays out of it.
        self.setup_doctor.setup.output.connect(self.append_log)

        self.strip = StageStrip()
        self.controls = PipelineControls()
        self.coverage = CoverageBar()
        self.issues = IssuesPanel()

        self._toggle = QToolButton()
        self._toggle.setCheckable(True)
        self._toggle.setChecked(True)
        self._toggle.setText("▾ Log console")
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self.setup_doctor)
        layout.addWidget(_hline())
        layout.addWidget(self.strip)
        layout.addWidget(self.controls)
        layout.addWidget(self.coverage)
        layout.addWidget(self.issues)
        layout.addWidget(self._toggle)
        layout.addWidget(self._log, 1)
        self._toggle.toggled.connect(self._on_toggle)

    def refresh_panels(self, game: str, workspace: str, running_stage: str | None = None) -> None:
        """Re-read markers/coverage/issues for ``game`` and update the strip, controls,
        coverage bar, and issues panel. Cheap enough to poll during a running job."""
        self.strip.refresh(game, workspace, running_stage)
        self.controls.set_game_has_gpu(has_gpu_stage(game))
        self.coverage.refresh(game, workspace)
        self.issues.refresh(game, workspace)

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


def _hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    return line
