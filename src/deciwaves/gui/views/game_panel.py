"""The adaptive per-game panel (#73, spec §7): one frame, only this panel swaps between DS,
HZD, and FW -- irrelevant controls are HIDDEN, never greyed.

Thin, exactly like :mod:`deciwaves.gui.export`: every string/constant and all the per-game
logic (which controls each game shows, the FW ``types.json`` grade, the scan-warning copy, the
render-scope defaults, the standalone DS re-order argv) lives in the Qt-free
:mod:`deciwaves.gui.game_panel_model`; this widget only builds widgets, hides/shows them per
game, and emits intents the shell turns into work.

Intents (the shell does the real work):
- ``transcript_order_requested(path)`` -- DS: run standalone ``ds order --transcript`` (never
  ``ds run``); the picked transcript is transient/per-invocation, NOT persisted.
- ``gamescript_picked(path)`` / ``types_picked(path)`` -- FW: persist the BYO path via the
  setup path (``SetupScreen.run(fw_gamescript=...)`` / ``run(fw_types=...)``), NOT a direct
  ``config.save`` -- so they route through setup's merge/absolutize/clear + re-doctor.
- ``render_scope_changed()`` -- a scope control changed; the shell also just reads
  :meth:`render_scope` on export, so this is a convenience notification.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from deciwaves.gui.theme import ERROR, NEUTRAL, OK, WARN
from deciwaves.gui.cuda_probe import cuda_status
from deciwaves.gui.game_panel_model import (
    FW_TIERS_DEFAULT,
    FW_TIERS_HINT,
    SAMPLE_CAP_DEFAULT,
    controls_for,
    render_scope_defaults,
    scan_warning,
    types_status,
    validate_fw_tiers,
)

_SAMPLE_CAP_MAX = 100000   # generous ceiling; 0 = unlimited (special value text below)


class GamePanel(QWidget):
    """The swappable per-game control panel. :meth:`set_game` shows only that game's controls;
    :meth:`set_context` refreshes the FW types.json grade and the GPU/CUDA readiness label."""

    render_scope_changed = Signal()
    transcript_order_requested = Signal(str)   # DS: standalone `ds order --transcript <abs>`
    gamescript_picked = Signal(str)            # FW: persist via setup --fw-gamescript
    types_picked = Signal(str)                 # FW: persist via setup --fw-types

    def __init__(self, parent=None):
        super().__init__(parent)
        self._game: str | None = None
        self._workspace = "."
        self._cfg: dict = {}

        # --- GPU/CUDA readiness (HZD, FW) ---
        self._gpu_label = QLabel("")
        gpu_box = self._wrap(self._row(self._gpu_label))

        # --- ASR sample cap (HZD) ---
        self._sample_cap = QSpinBox()
        self._sample_cap.setRange(0, _SAMPLE_CAP_MAX)
        self._sample_cap.setValue(SAMPLE_CAP_DEFAULT)
        self._sample_cap.setSpecialValueText("unlimited")   # shown when value == 0
        sample_box = self._wrap(self._row(
            QLabel("ASR sample cap:"), self._sample_cap,
            QLabel("(first bind; 0 = unlimited)")))

        # --- render scope: DS --main-story ---
        self._main_story = QCheckBox("Main story only (--main-story)")
        self._main_story.setToolTip("Only include main story missions, skip side content")
        main_story_box = self._wrap(self._row(self._main_story))

        # --- render scope: HZD --spine-only ---
        self._spine_only = QCheckBox("Main-quest spine only (--spine-only)")
        spine_box = self._wrap(self._row(self._spine_only))

        # --- render scope: FW --tiers ---
        self._tiers_edit = QLineEdit(FW_TIERS_DEFAULT)
        self._tiers_edit.setMaximumWidth(120)
        self._tiers_hint = QLabel(FW_TIERS_HINT)
        self._tiers_hint.setStyleSheet(f"color: {NEUTRAL}; font-style: italic;")
        self._tiers_warning = QLabel("")
        self._tiers_warning.setStyleSheet(f"color: {ERROR};")
        self._tiers_warning.setVisible(False)
        tiers_box = QWidget()
        v = QVBoxLayout(tiers_box)
        v.setContentsMargins(0, 0, 0, 0)
        v.addLayout(self._row(QLabel("Tiers (--tiers):"), self._tiers_edit))
        v.addLayout(self._row(self._tiers_hint))
        v.addLayout(self._row(self._tiers_warning))

        # --- DS transcript picker + re-order affordance (transient, NOT persisted) ---
        self._transcript_edit = QLineEdit()
        self._transcript_edit.setPlaceholderText("Narrative transcript (BYO, optional)")
        self._transcript_edit.setToolTip("Path to a narrative transcript file for story ordering")
        self._transcript_browse = QPushButton("Browse…")
        self._transcript_browse.setToolTip("Browse for a narrative transcript file")
        self._reorder_btn = QPushButton("Re-order with transcript")
        self._reorder_btn.setToolTip("Re-order episodes using the selected transcript")
        transcript_box = self._wrap(self._row(
            QLabel("Transcript:"), self._transcript_edit,
            self._transcript_browse, self._reorder_btn))

        # --- FW required types.json picker ---
        self._types_edit = QLineEdit()
        self._types_edit.setReadOnly(True)
        self._types_edit.setToolTip("Path to types.json (required for subtitle bind)")
        self._types_browse = QPushButton("Browse…")
        self._types_browse.setToolTip("Browse for types.json")
        self._types_status = QLabel("")
        types_box = self._wrap(
            self._row(QLabel("types.json (required):"), self._types_edit, self._types_browse),
            self._row(self._types_status))

        # --- FW optional gamescript picker ---
        self._gamescript_edit = QLineEdit()
        self._gamescript_edit.setReadOnly(True)
        self._gamescript_edit.setPlaceholderText("Gamescript (BYO, optional -- speaker + order)")
        self._gamescript_edit.setToolTip("Path to a gamescript file for speaker labels and ordering")
        self._gamescript_browse = QPushButton("Browse…")
        self._gamescript_browse.setToolTip("Browse for a gamescript file")
        gamescript_box = self._wrap(self._row(
            QLabel("Gamescript:"), self._gamescript_edit, self._gamescript_browse))

        # control-name -> its container widget (the hide-not-grey unit, spec §7)
        self._widgets = {
            "gpu": gpu_box,
            "sample_cap": sample_box,
            "main_story": main_story_box,
            "spine_only": spine_box,
            "tiers": tiers_box,
            "transcript": transcript_box,
            "types_json": types_box,
            "gamescript": gamescript_box,
        }

        self._scan_warning = QLabel("")
        self._scan_warning.setStyleSheet(f"color: {NEUTRAL};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for w in self._widgets.values():
            layout.addWidget(w)
        layout.addWidget(self._scan_warning)

        # wiring
        self._transcript_browse.clicked.connect(self._on_transcript_browse)
        self._reorder_btn.clicked.connect(self._on_reorder)
        self._types_browse.clicked.connect(self._on_types_browse)
        self._gamescript_browse.clicked.connect(self._on_gamescript_browse)
        self._main_story.toggled.connect(lambda _c: self.render_scope_changed.emit())
        self._spine_only.toggled.connect(lambda _c: self.render_scope_changed.emit())
        self._tiers_edit.textChanged.connect(self._on_tiers_changed)

        self.set_game("ds")

    # --- layout helpers ----------------------------------------------------

    @staticmethod
    def _row(*widgets) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        for w in widgets:
            h.addWidget(w)
        h.addStretch(1)
        return h

    @staticmethod
    def _wrap(*rows) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        for r in rows:
            v.addLayout(r)
        return box

    # --- state the shell drives --------------------------------------------

    def set_game(self, game: str) -> None:
        """Show only *game*'s controls (spec §7: HIDE the rest, never grey them) and reset the
        render-scope controls to that game's defaults + the scan-warning copy."""
        self._game = game
        visible = controls_for(game)
        for name, w in self._widgets.items():
            w.setVisible(name in visible)
        self._scan_warning.setText(scan_warning(game))

        defaults = render_scope_defaults(game)
        # block scope signals so applying defaults doesn't fire render_scope_changed spuriously
        for w in (self._main_story, self._spine_only, self._tiers_edit):
            w.blockSignals(True)
        self._main_story.setChecked(bool(defaults.get("main_story", False)))
        self._spine_only.setChecked(bool(defaults.get("spine_only", False)))
        self._tiers_edit.setText(defaults.get("tiers", FW_TIERS_DEFAULT))
        self._tiers_warning.setVisible(False)
        for w in (self._main_story, self._spine_only, self._tiers_edit):
            w.blockSignals(False)

    def set_context(self, workspace: str, cfg: dict, payload: dict | None) -> None:
        """Refresh the FW types.json grade (satisfied/required-missing) and the GPU/CUDA
        readiness label, from the current workspace/config and the last ``doctor --json``
        payload. Cheap enough to call on game change / job finish / doctor completion."""
        self._workspace = workspace or "."
        self._cfg = cfg or {}
        self._refresh_types_status()
        self._refresh_gpu_status(payload)
        self._gamescript_edit.setText(self._cfg.get("fw_gamescript", "") or "")

    def _refresh_types_status(self) -> None:
        status, path = types_status(self._workspace, self._cfg)
        self._types_edit.setText(path)
        if status == "ok":
            self._types_status.setText(f"types.json: OK — {path}")
            self._types_status.setStyleSheet(f"color: {OK};")
        else:
            self._types_status.setText(
                "types.json: MISSING — required for bind (subtitle-bind onward); "
                "scan + preview work without it")
            self._types_status.setStyleSheet(f"color: {ERROR};")

    def _refresh_gpu_status(self, payload: dict | None) -> None:
        status = cuda_status(payload)
        if status == "ok":
            self._gpu_label.setText("GPU: CUDA ready")
            self._gpu_label.setStyleSheet(f"color: {OK};")
        elif status == "":
            self._gpu_label.setText("GPU: unknown — run Doctor to check CUDA")
            self._gpu_label.setStyleSheet(f"color: {NEUTRAL};")
        else:
            self._gpu_label.setText(
                "GPU: no CUDA GPU detected — this stage may take days on CPU")
            self._gpu_label.setStyleSheet(f"color: {WARN};")

    # --- picker intents (dialogs opened here; the shell does the work) ------

    def _on_transcript_browse(self) -> None:
        path, _f = QFileDialog.getOpenFileName(
            self, "Choose narrative transcript", self._workspace)
        if path:
            self._transcript_edit.setText(path)

    def _on_reorder(self) -> None:
        path = self._transcript_edit.text().strip()
        if path:   # ds order validates existence + fails loud; emit the absolute path
            self.transcript_order_requested.emit(os.path.abspath(path))

    def _on_types_browse(self) -> None:
        path, _f = QFileDialog.getOpenFileName(
            self, "Choose Forbidden West types.json", self._workspace,
            "JSON files (*.json);;All files (*.*)")
        if path and os.path.isfile(path):   # hygiene: verify existence at pick time (spec §7)
            self.types_picked.emit(path)

    def _on_gamescript_browse(self) -> None:
        path, _f = QFileDialog.getOpenFileName(
            self, "Choose Forbidden West gamescript", self._workspace)
        if path and os.path.isfile(path):   # hygiene: verify existence at pick time (spec §7)
            self.gamescript_picked.emit(path)

    # --- accessors (shell + tests) -----------------------------------------

    def visible_controls(self) -> set[str]:
        """The set of control names currently shown (the others are hidden, not disabled)."""
        return {name for name, w in self._widgets.items() if w.isVisibleTo(self)}

    def _on_tiers_changed(self, text: str) -> None:
        is_valid, unknown = validate_fw_tiers(text)
        if not is_valid and unknown:
            self._tiers_warning.setText(f"Unknown tier(s): {', '.join(unknown)}")
            self._tiers_warning.setVisible(True)
        else:
            self._tiers_warning.setVisible(False)
        self.render_scope_changed.emit()

    def render_scope(self) -> dict:
        """The current render scope for the shell to thread into ``render_selection_argv``:
        DS ``{"main_story": bool}``, HZD ``{"spine_only": bool}``, FW ``{"tiers": str}``."""
        if self._game == "ds":
            return {"main_story": self._main_story.isChecked()}
        if self._game == "hzd":
            return {"spine_only": self._spine_only.isChecked()}
        if self._game == "fw":
            return {"tiers": self._tiers_edit.text().strip() or FW_TIERS_DEFAULT}
        return {}

    def sample_cap(self) -> int | None:
        """The HZD first-bind ASR cap for ``process_argv``; ``None`` for non-HZD games (they
        have no cap to pass). 0 means uncapped."""
        return self._sample_cap.value() if self._game == "hzd" else None

    def types_status_text(self) -> str:
        return self._types_status.text()

    def gpu_status_text(self) -> str:
        return self._gpu_label.text()

    def scan_warning_text(self) -> str:
        return self._scan_warning.text()
