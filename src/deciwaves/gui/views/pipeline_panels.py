"""Pipeline-view widgets (#69, spec §5): the stage strip, Scan/Bind controls, coverage
bar, and issues panel. All parsing/argv/coverage logic lives in the Qt-free models
(:mod:`pipeline_model`, :mod:`coverage_model`, :mod:`issues_model`); these are the thin
views that render them and emit intent signals the shell turns into pipeline jobs."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from deciwaves.gui.theme import NEUTRAL, OK, RUNNING, WARN
from deciwaves.gui.widgets import HelpIcon
from deciwaves.gui.coverage_model import (
    coverage_summary,
    format_coverage,
    load_coverage,
    needs_escalation,
)
from deciwaves.gui.issues_model import gather_issues, split_issues
from deciwaves.gui.pipeline_model import StageState, has_gpu_stage, stage_states

# Theme colours imported from deciwaves.gui.theme: OK, NEUTRAL, RUNNING, WARN, ERROR


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()


class StageStrip(QWidget):
    """The per-game chain as a row of chips, coloured by marker state (#69, spec §5.1)."""

    rerun_requested = Signal(str)  # stage name to `run --from`

    def __init__(self, parent=None):
        super().__init__(parent)
        self._states: list[StageState] = []
        self._running: str | None = None
        self._busy = False   # a job is active app-wide -> the re-run affordance is gated
        self._row = QHBoxLayout(self)
        self._row.setAlignment(Qt.AlignLeft)

    def refresh(self, game: str, workspace: str, running_stage: str | None = None) -> None:
        self._running = running_stage
        self._states = stage_states(game, workspace)
        _clear(self._row)
        for st in self._states:
            self._row.addWidget(self._chip(st))

    def set_running(self, running: bool) -> None:
        """Mutual exclusion with any in-flight job (pipeline scan/bind, export render, or a
        dump): disables the "Re-run from here" affordance so a re-run can't launch a second,
        concurrent job while one runs (one job at a time, spec §5.3 -- mirrors
        :meth:`PipelineControls.set_running`). Inline preview is deliberately untouched (§6.5)."""
        self._busy = running

    def rerun_enabled(self) -> bool:
        return not self._busy

    def states(self) -> list[StageState]:
        return list(self._states)

    def running_stage(self) -> str | None:
        return self._running

    def request_rerun(self, stage: str) -> None:
        if self._busy:   # gated while a job runs -- no second concurrent job (spec §5.3)
            return
        self.rerun_requested.emit(stage)

    def _chip(self, st: StageState) -> QWidget:
        if st.name == self._running:
            colour, mark = RUNNING, "▶"
        elif st.done:
            colour, mark = OK, "✓"
        else:
            colour, mark = NEUTRAL, "○"
        label = f"{mark} {st.name}" + (" (GPU)" if st.gpu else "")
        chip = QLabel(label)
        chip.setToolTip(f"Pipeline stage: {st.name} — right-click to re-run from here")
        weight = "bold" if st.name == self._running else "normal"
        chip.setStyleSheet(f"color: {colour}; font-weight: {weight}; padding: 2px 6px;")
        chip.setContextMenuPolicy(Qt.CustomContextMenu)
        chip.customContextMenuRequested.connect(
            lambda pos, n=st.name, w=chip: self._chip_menu(w, pos, n))
        return chip

    def _chip_menu(self, chip: QWidget, pos, stage: str) -> None:
        menu = QMenu(self)
        menu.setAttribute(Qt.WA_DeleteOnClose)
        action = menu.addAction("Re-run from here")
        action.setEnabled(not self._busy)   # grayed out while a job runs (spec §5.3)
        action.triggered.connect(lambda: self.request_rerun(stage))
        menu.exec(chip.mapToGlobal(pos))


class PipelineControls(QWidget):
    """Scan + Bind/Process buttons (#69, spec §5.2). Bind is hidden for games with no GPU
    stage (DS); the shell attaches the CUDA probe + hours warning to Process."""

    scan_requested = Signal()
    process_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._workspace_empty = True
        self._scan_btn = QPushButton("Scan")
        self._bind_btn = QPushButton("Bind / Process")
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setToolTip("Always safe — terminates then force-kills the job")
        self._cancel_btn.setVisible(False)
        self._scan_btn.clicked.connect(lambda: self.scan_requested.emit())
        self._bind_btn.clicked.connect(lambda: self.process_requested.emit())
        self._cancel_btn.clicked.connect(lambda: self.cancel_requested.emit())
        row = QHBoxLayout(self)
        row.setAlignment(Qt.AlignLeft)
        row.addWidget(self._scan_btn)
        row.addWidget(self._bind_btn)
        row.addWidget(self._cancel_btn)
        self._apply_enable()

    def set_game_has_gpu(self, has_gpu: bool) -> None:
        self._bind_btn.setVisible(has_gpu)

    def bind_shown(self) -> bool:
        return self._bind_btn.isVisibleTo(self)

    def cancel_shown(self) -> bool:
        return self._cancel_btn.isVisibleTo(self)

    def set_running(self, running: bool) -> None:
        self._running = running
        self._apply_enable()

    def set_workspace_empty(self, empty: bool) -> None:
        self._workspace_empty = empty
        self._apply_enable()

    def _apply_enable(self) -> None:
        if self._running:
            self._scan_btn.setEnabled(False)
            self._bind_btn.setEnabled(False)
            self._cancel_btn.setVisible(True)
        else:
            not_empty = not self._workspace_empty
            self._scan_btn.setEnabled(not_empty)
            self._bind_btn.setEnabled(not_empty)
            self._cancel_btn.setVisible(False)

    def focus_scan(self) -> None:
        self._scan_btn.setFocus()

    def focus_bind(self) -> None:
        self._bind_btn.setFocus()


class CoverageBar(QWidget):
    """"X / Y bound · Z%", cap-aware, with a one-click "Transcribe all" escalation when a
    sample cap left ambiguous groups untranscribed (#69, spec §5.4). HZD-only in practice."""

    escalate_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._has_coverage = False
        self._label = QLabel("")
        self._escalate_btn = QPushButton("Transcribe all (hours)")
        self._escalate_btn.setStyleSheet(f"color: {WARN};")
        self._escalate_btn.clicked.connect(lambda: self.escalate_requested.emit())
        row = QHBoxLayout(self)
        row.setAlignment(Qt.AlignLeft)
        row.addWidget(self._label)
        row.addWidget(HelpIcon(
            "Coverage: how many voice lines have their audio bound. HZD/FW group "
            "lines into cutscene 'cores' and 'segments'; a sample cap can leave "
            "some groups untranscribed until you 'Transcribe all'."))
        row.addWidget(self._escalate_btn)

    def refresh(self, game: str, workspace: str) -> None:
        summary = coverage_summary(load_coverage(workspace, game))
        self._has_coverage = summary is not None
        self.setVisible(self._has_coverage)
        if summary is None:
            self._label.setText("")
            self._escalate_btn.setVisible(False)
            return
        self._label.setText(format_coverage(summary))
        self._escalate_btn.setVisible(needs_escalation(summary))

    def has_coverage(self) -> bool:
        return self._has_coverage

    def escalate_shown(self) -> bool:
        return self._escalate_btn.isVisibleTo(self)

    def text(self) -> str:
        return self._label.text()


class IssuesPanel(QWidget):
    """Per-stage ``*-errors.log`` + ``render-dupes.csv`` as a collapsed list (#69, §5.4)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups: list = []
        self._header = QLabel("<b>Issues</b>")
        self._header.setToolTip("Lines a pipeline stage dropped or failed to process")
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.addWidget(self._header)
        header_row.addWidget(HelpIcon(
            "Issues counts only real problems — lines a stage failed to process or had "
            "to drop. Expected housekeeping, like de-duplicating repeated voice lines, "
            "is listed separately below and is not an error."))
        header_row.addStretch(1)
        self._header_host = QWidget()
        self._header_host.setLayout(header_row)
        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        layout = QVBoxLayout(self)
        layout.addWidget(self._header_host)
        layout.addWidget(self._body)

    def refresh(self, game: str, workspace: str) -> None:
        self._groups = gather_issues(workspace, game)
        _clear(self._body_layout)
        errors, housekeeping = split_issues(self._groups)

        # Header counts ONLY real errors -- benign housekeeping (de-dupes) must never
        # make a successful run read as "Issues — 678" (dogfooding: it scared a user).
        error_total = sum(g.count for g in errors)
        self._header.setText("<b>Issues</b> — none" if error_total == 0
                             else f"<b>Issues</b> — {error_total:,}")
        for g in errors:
            row = QLabel(f"{g.source}: {g.count:,}")
            row.setStyleSheet(f"color: {WARN};")
            if g.sample:
                row.setToolTip("\n".join(g.sample))
            self._body_layout.addWidget(row)

        # Housekeeping: neutral, reassuring, and clearly NOT an error.
        if housekeeping:
            hk_total = sum(g.count for g in housekeeping)
            head = QLabel("<b>Housekeeping</b>")
            head.setStyleSheet(f"color: {NEUTRAL};")
            self._body_layout.addWidget(head)
            note = QLabel(
                f"{hk_total:,} duplicate lines de-duplicated (expected — identical "
                "repeated voice lines are collapsed in your reels).")
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {NEUTRAL};")
            self._body_layout.addWidget(note)

    def groups(self) -> list:
        return list(self._groups)


def controls_for(game: str) -> bool:
    """Whether the Bind/Process control should show for ``game`` (has a GPU stage)."""
    return has_gpu_stage(game)
