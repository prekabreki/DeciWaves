"""First-run Setup & Doctor widgets (#68, spec §3).

- :class:`DoctorPanel` shells out to ``deciwaves doctor --json`` (issue #65) and renders a
  status row per check. It re-grades on game change without re-running: the ASR extra and
  CUDA read as first-class readiness for HZD/FW but stay informational for DS (spec §3).
- :class:`SetupScreen` drives ``deciwaves setup`` with per-tool indeterminate spinners
  (setup emits no download progress), Re-download (``--force``) / offline Re-check
  (``--skip-downloads``) buttons, and surfaces setup's Oodle/HZD WARNING lines verbatim.

Both keep parsing in Qt-free modules (:mod:`doctor_model`, :mod:`setup_model`) so the
contract is tested without Qt; these classes are the thin view + wiring on top."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from deciwaves.gui.theme import ERROR, NEUTRAL, OK, WARN
from deciwaves.gui.capture import CaptureRunner
from deciwaves.gui.cli_command import default_base
from deciwaves.gui.doctor_model import (
    SEV_ERROR,
    SEV_NEUTRAL,
    SEV_OK,
    SEV_WARN,
    DoctorItem,
    load_doctor_payload,
    overall_ok,
    parse_doctor_payload,
    pill_for,
    severity,
)
from deciwaves.gui.guide_model import tools_ready
from deciwaves.gui.widgets import CollapsibleSection, HelpIcon, Pill
from deciwaves.gui.setup_model import (
    build_setup_argv,
    parse_setup_summary,
    parse_setup_warnings,
    tool_severity,
)

# severity -> (glyph, colour). Drawn from the shared theme module.
_SEV_STYLE = {
    SEV_OK: ("●", OK),
    SEV_ERROR: ("✕", ERROR),
    SEV_WARN: ("▲", WARN),
    SEV_NEUTRAL: ("—", NEUTRAL),
}

# The tools setup fetches, in summary order -- the rows that get a per-tool spinner.
_SETUP_TOOLS = ("vgmstream", "VGAudio", "ffmpeg")


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()


class DoctorPanel(QWidget):
    refreshed = Signal()  # emitted after a `doctor --json` run has been rendered

    def __init__(self, base: list[str] | None = None, parent=None):
        super().__init__(parent)
        self._base = base or default_base()
        self._game = "ds"
        self._items: list[DoctorItem] = []
        self._payload: dict | None = None
        self._auto_checked = False

        # doctor --json must be parsed from clean stdout (merge_stderr=False)
        self._runner = CaptureRunner(self, merge_stderr=False)
        self._runner.started.connect(self._on_started)
        self._runner.finished.connect(self._on_finished)

        self._recheck_btn = QPushButton("Re-check")
        self._recheck_btn.setToolTip("Re-run Doctor to check system and tool status")
        self._recheck_btn.clicked.connect(self.recheck)
        self._rows = QWidget()
        self._rows_layout = QVBoxLayout(self._rows)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Doctor</b>"))
        header.addStretch(1)
        header.addWidget(self._recheck_btn)
        layout.addLayout(header)
        layout.addWidget(self._rows)

    def set_game(self, game: str) -> None:
        self._game = game
        if self._payload is not None:
            self.render_payload(self._payload)  # re-grade the promoted GPU items

    def recheck(self) -> bool:
        """Run ``deciwaves doctor --json``. Returns False if a run is already in flight."""
        return self._runner.start([*self._base, "doctor", "--json"])

    def auto_check(self) -> bool:
        """Run doctor once, the first time the panel becomes visible (#107). Returns True
        iff this call started the run; later show/hide cycles are no-ops so the panel never
        re-spawns doctor behind the user's back."""
        if self._auto_checked:
            return False
        self._auto_checked = True
        return self.recheck()

    def showEvent(self, event) -> None:
        # On launch a healthy install must show its statuses immediately, not blank "-"
        # placeholders that read as broken (#107). Deferred to first-show (not __init__) so
        # widget tests that never show the panel don't spawn a doctor subprocess.
        super().showEvent(event)
        self.auto_check()

    def render_payload(self, payload: dict) -> None:
        self._payload = payload
        self._items = parse_doctor_payload(payload)
        _clear(self._rows_layout)
        for item in self._items:
            self._rows_layout.addWidget(self._row_widget(item))

    def items(self) -> list[DoctorItem]:
        return list(self._items)

    def last_payload(self) -> dict | None:
        """The most recent ``doctor --json`` payload (for the pre-bind CUDA probe, #69)."""
        return self._payload

    def severity_of(self, name: str) -> str:
        for item in self._items:
            if item.name == name:
                return severity(item, self._game)
        return SEV_NEUTRAL

    def rendered_text(self) -> str:
        """All visible row text -- used to assert fix hints render verbatim."""
        return "\n".join(
            f"{item.message} {item.fix}".strip() for item in self._items)

    def _row_widget(self, item: DoctorItem) -> QWidget:
        glyph, colour = _SEV_STYLE[severity(item, self._game)]
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        marker = QLabel(glyph)
        marker.setStyleSheet(f"color: {colour};")
        marker.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        h.addWidget(marker)
        text = item.message if not item.fix else f"{item.message}  —  Fix: {item.fix}"
        text_label = QLabel(text)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        h.addWidget(text_label, 1)
        pill = pill_for(item, self._game)
        if pill is not None:
            h.addWidget(Pill(*pill))
        return row

    def _on_started(self) -> None:
        _clear(self._rows_layout)
        placeholder = QLabel("<i>Checking…</i>")
        placeholder.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self._rows_layout.addWidget(placeholder)
        self._recheck_btn.setEnabled(False)

    def _on_finished(self, _code: int, text: str) -> None:
        self._recheck_btn.setEnabled(True)
        payload = load_doctor_payload(text)
        if payload is None:
            payload = {"ok": False, "checks": [
                {"name": "doctor", "ok": False, "status": "broken",
                 "message": "doctor --json produced no readable output", "fix": ""}]}
        self.render_payload(payload)
        self.refreshed.emit()


class SetupScreen(QWidget):
    finished = Signal(int)  # setup exit code, after rows + warnings are rendered
    output = Signal(str)    # raw stdout chunks, re-emitted for the shared log console
    busy_changed = Signal(bool)  # fired when _busy toggles, lets shell enforce mutual exclusion

    def __init__(self, base: list[str] | None = None, parent=None):
        super().__init__(parent)
        self._base = base or default_base()
        self._busy = False
        self._pipeline_busy = False
        self._rows: list = []
        self._warnings: list[str] = []

        self._runner = CaptureRunner(self)  # merged: setup's output is a live console
        self._runner.output.connect(self.output)  # stream to the log console (spec §5.3)
        self._runner.finished.connect(self._on_finished)

        self._run_btn = QPushButton("Run setup")
        self._run_btn.setToolTip("Download and configure required tools (vgmstream, VGAudio, ffmpeg)")
        self._redownload_btn = QPushButton("Re-download")
        self._redownload_btn.setToolTip("Force re-download of all tools")
        self._recheck_btn = QPushButton("Re-check (offline)")
        self._recheck_btn.setToolTip("Re-check installed tools without downloading")
        self._run_btn.clicked.connect(lambda: self.run())
        self._redownload_btn.clicked.connect(lambda: self.run(force=True))
        self._recheck_btn.clicked.connect(lambda: self.run(skip_downloads=True))

        # one fixed row per tool: a spinner while running, a status line after.
        self._tool_status: dict[str, QLabel] = {}
        self._tool_spinner: dict[str, QProgressBar] = {}
        tools_box = QVBoxLayout()
        for tool in _SETUP_TOOLS:
            tools_box.addLayout(self._tool_row(tool))

        self._paths_label = QLabel("")   # ds_install / oodle / hzd / fw summary rows
        self._paths_label.setWordWrap(True)
        self._paths_label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self._warnings_label = QLabel("")
        self._warnings_label.setWordWrap(True)
        self._warnings_label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self._warnings_label.setStyleSheet(f"color: {_SEV_STYLE[SEV_WARN][1]};")

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setToolTip("Stop the running setup (safe — terminates then kills)")
        self._cancel_btn.clicked.connect(lambda: self.cancel())
        self._cancel_btn.setVisible(False)

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Setup</b>"))
        header.addWidget(HelpIcon(
            "BYO (Bring Your Own): you supply your own legally-owned game files. "
            "Setup only downloads the open-source audio decoders (vgmstream, "
            "VGAudio, ffmpeg) — about 200 MB on first run. This app never ships "
            "game content."))
        header.addStretch(1)
        for btn in (self._run_btn, self._redownload_btn, self._recheck_btn):
            header.addWidget(btn)
        header.addWidget(self._cancel_btn)
        layout.addLayout(header)
        layout.addLayout(tools_box)
        layout.addWidget(self._paths_label)
        layout.addWidget(self._warnings_label)

    def _tool_row(self, tool: str) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addWidget(QLabel(tool))
        spinner = QProgressBar()
        spinner.setRange(0, 0)      # indeterminate -- setup emits no download progress
        spinner.setVisible(False)
        spinner.setMaximumWidth(120)
        status = QLabel("—")
        status.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self._tool_spinner[tool] = spinner
        self._tool_status[tool] = status
        h.addStretch(1)
        h.addWidget(spinner)
        h.addWidget(status)
        return h

    def run(self, *, force: bool = False, skip_downloads: bool = False, **paths) -> bool:
        """Start ``deciwaves setup``. Returns False if a run is already in flight."""
        argv = build_setup_argv(self._base, force=force, skip_downloads=skip_downloads, **paths)
        if not self._runner.start(argv):
            return False
        self._busy = True
        self._update_buttons()
        self.busy_changed.emit(True)
        for tool in _SETUP_TOOLS:
            self._tool_spinner[tool].setVisible(True)
            self._tool_status[tool].setVisible(False)
        return True

    def cancel(self) -> None:
        self._runner.cancel()

    def _update_buttons(self) -> None:
        enabled = not self._busy and not self._pipeline_busy
        self._run_btn.setEnabled(enabled)
        self._redownload_btn.setEnabled(enabled)
        self._recheck_btn.setEnabled(enabled)
        self._cancel_btn.setVisible(self._busy)

    def set_running(self, running: bool) -> None:
        """Disable setup buttons when the pipeline is busy (external mutual-exclusion)."""
        self._pipeline_busy = running
        self._update_buttons()

    @property
    def is_busy(self) -> bool:
        return self._busy

    def rows(self) -> list:
        return list(self._rows)

    def warnings(self) -> list[str]:
        return list(self._warnings)

    def regrade_against_doctor(self, doctor_items) -> None:
        """Re-grade the tool rows against doctor's verdict so Setup can't show a red FAILED
        for a tool Doctor reports present + valid (#110). A tool that failed to re-fetch but
        is still installed reads as "using existing copy", amber, not a hard error -- the two
        panels stop contradicting each other. A genuinely missing tool stays a red failure."""
        by_label = {r.label: r for r in self._rows}
        for tool in _SETUP_TOOLS:
            row = by_label.get(tool)
            if row is None:
                continue
            sev = tool_severity(row, doctor_items)
            status = self._tool_status[tool]
            # Always (re)set the text, not just on the WARN branch: a later re-check can move
            # a row WARN -> ERROR, and leaving the softened text would show "using existing
            # copy" under a red row for a tool that's now gone (#110 review).
            softened = sev == SEV_WARN and row.failed
            status.setText("using existing copy (couldn't refresh)" if softened else row.detail)
            status.setStyleSheet(f"color: {_SEV_STYLE[sev][1]};")

    def _on_finished(self, code: int, text: str) -> None:
        self._busy = False
        self._update_buttons()
        self.busy_changed.emit(False)
        self._rows = parse_setup_summary(text)
        self._warnings = parse_setup_warnings(text)
        by_label = {r.label: r for r in self._rows}
        for tool in _SETUP_TOOLS:
            self._tool_spinner[tool].setVisible(False)
            status = self._tool_status[tool]
            status.setVisible(True)
            row = by_label.get(tool)
            if row is None:
                status.setText("—")
                status.setStyleSheet("")
                continue
            status.setText(row.detail)
            sev = tool_severity(row, [])
            status.setStyleSheet(f"color: {_SEV_STYLE[sev][1]};")
        if code != 0 and not self._rows:
            self._paths_label.setText("setup exited with code {}".format(code))
        else:
            path_rows = [r for r in self._rows if r.label not in _SETUP_TOOLS]
            self._paths_label.setText("\n".join(f"{r.label}: {r.detail}" for r in path_rows))
        self._warnings_label.setText("\n".join(self._warnings))
        self.finished.emit(int(code))


class SetupDoctorView(QFrame):
    """Setup screen above the Doctor panel -- the first-run home (spec §2, §3),
    each wrapped in a CollapsibleSection that collapses once ready (#112)."""

    def __init__(self, base: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setup = SetupScreen(base)
        self.doctor = DoctorPanel(base)
        self.setup_section = CollapsibleSection("Setup", self.setup)
        self.doctor_section = CollapsibleSection("Doctor", self.doctor)

        # first-run flow: a finished setup re-checks doctor toward a green panel (spec §3)
        self.setup.finished.connect(lambda _code: self.doctor.recheck())
        # ...and every doctor result re-grades the setup rows (#110) and re-derives the
        # collapse/summary state (#112).
        self.doctor.refreshed.connect(
            lambda: self.setup.regrade_against_doctor(self.doctor.items()))
        self.doctor.refreshed.connect(self.apply_readiness_summary)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)
        layout.addWidget(self.setup_section)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        layout.addWidget(line)
        layout.addWidget(self.doctor_section)

    def set_game(self, game: str) -> None:
        self.doctor.set_game(game)

    def apply_readiness_summary(self) -> None:
        """Derive each section's one-line summary and default collapse from the
        latest doctor payload: collapse when ready (the rail carries status),
        expand where a required check is missing (#112)."""
        payload = self.doctor.last_payload()
        setup_ok = tools_ready(payload)
        doctor_ok = overall_ok(payload) if payload is not None else False

        self.setup_section.set_summary(
            "Tools ready ✓" if setup_ok else "Setup needed — downloads ~200 MB")
        self.setup_section.set_collapsed(setup_ok)

        items = self.doctor.items()
        total = len(items)
        optional = sum(1 for it in items
                       if pill_for(it, self.doctor._game) == ("Optional", "optional"))
        self.doctor_section.set_summary(
            f"{total - optional} required OK · {optional} optional" if doctor_ok
            else "Doctor found something to fix")
        self.doctor_section.set_collapsed(doctor_ok)
