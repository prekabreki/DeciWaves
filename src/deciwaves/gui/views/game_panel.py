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

from PySide6.QtCore import Qt, Signal
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
from deciwaves.gui.widgets import AsrInstallHint, HelpIcon
from deciwaves.gui.cuda_probe import asr_extra_installed, cuda_display_text
from deciwaves.gui.game_panel_model import (
    FW_TIERS_DEFAULT,
    FW_TIERS_HINT,
    SAMPLE_CAP_DEFAULT,
    controls_for,
    render_scope_defaults,
    scan_warning,
    types_status,
)

_SAMPLE_CAP_MAX = 100000   # generous ceiling; 0 = unlimited (special value text below)

# FW --tiers, as user-facing checkboxes. (token, plain label) in canonical order;
# render_scope() joins the checked tokens back into the CSV the CLI expects.
_FW_TIER_CHECKS = [
    ("1", "Confident subtitle match (1)"),
    ("2", "Lower-confidence match (2)"),
    ("S", "Subtitle-only lines (S)"),
    ("W", "Scene-recovered story lines (W)"),
    ("D", "DLC — Burning Shores (D)"),
]


class GamePanel(QWidget):
    """The swappable per-game control panel. :meth:`set_game` shows only that game's controls;
    :meth:`set_context` refreshes the FW types.json grade and the GPU/CUDA readiness label."""

    render_scope_changed = Signal()
    asr_recheck_requested = Signal()           # ASR hint: re-run Doctor after install
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

        # --- ASR install hint (shown only when missing for GPU games) ---
        self._asr_hint = AsrInstallHint()
        self._asr_hint.setVisible(False)
        self._asr_hint.recheck_requested.connect(self.asr_recheck_requested)

        # --- HZD sample cap: transcribe-first-N-lines for test runs ---
        self._sample_cap = QSpinBox()
        self._sample_cap.setRange(0, _SAMPLE_CAP_MAX)
        self._sample_cap.setValue(SAMPLE_CAP_DEFAULT)
        self._sample_cap.setSpecialValueText("unlimited")   # shown when value == 0
        self._sample_cap.setToolTip(
            "ASR (Automatic Speech Recognition) sample cap for the first bind. "
            "Use a small number (e.g. 300) for a quick test run, "
            "or 0 to transcribe all lines (may take hours).")
        sample_box = self._wrap(self._row(
            QLabel("Transcribe first N lines (test run):"), self._sample_cap,
            QLabel("(0 = unlimited)")))

        # --- render scope: DS --main-story ---
        self._main_story = QCheckBox("Main story only (--main-story)")
        self._main_story.setToolTip("Only include main story missions, skip side content")
        main_story_box = self._wrap(self._row(self._main_story))

        # --- render scope: HZD --spine-only ---
        self._spine_only = QCheckBox("Main-quest spine only (--spine-only)")
        spine_box = self._wrap(self._row(self._spine_only))

        # --- render scope: FW --tiers (checkboxes, not a raw token box) ---
        self._tiers_blurb = QLabel(
            "Which voice lines to include, grouped by how each line was "
            "identified:")
        self._tiers_blurb.setWordWrap(True)
        self._tiers_checks: dict[str, QCheckBox] = {}
        _tier_default = set(FW_TIERS_DEFAULT.split(","))
        tiers_box = QWidget()
        v = QVBoxLayout(tiers_box)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel("Tiers (--tiers):"))
        v.addWidget(self._tiers_blurb)
        for token, label in _FW_TIER_CHECKS:
            cb = QCheckBox(label)
            cb.setChecked(token in _tier_default)
            cb.toggled.connect(lambda _c: self.render_scope_changed.emit())
            self._tiers_checks[token] = cb
            v.addWidget(cb)
        self._tiers_hint = QLabel(FW_TIERS_HINT)
        self._tiers_hint.setStyleSheet(f"color: {NEUTRAL}; font-style: italic;")
        self._tiers_hint.setWordWrap(True)
        v.addWidget(self._tiers_hint)

        # --- DS transcript picker + re-order affordance (transient, NOT persisted) ---
        self._transcript_edit = QLineEdit()
        self._transcript_edit.setPlaceholderText(
            'Narrative transcript — plain text, "Speaker: text" per line (BYO, optional)')
        self._transcript_edit.setToolTip("Path to a narrative transcript file for story ordering")
        self._transcript_browse = QPushButton("Browse…")
        self._transcript_browse.setToolTip("Browse for a narrative transcript file")
        self._reorder_btn = QPushButton("Re-order with transcript")
        self._reorder_btn.setToolTip("Re-order episodes using the selected transcript")
        # Inline help below the field (NOT behind a HelpIcon tooltip) -- same pattern
        # as the FW types.json help above, so a first-time user sees WHY this control
        # is here, that it's optional, and the exact file format without hunting for a
        # hover. Copy tracks docs/BYO.md's "Death Stranding: narrative transcript".
        self._transcript_help = QLabel(
            "Optional. DS already produces story-ordered reels without this — a "
            "transcript only sharpens cutscene ordering by anchoring scenes to their "
            "real position in the story. Format: plain UTF-8 text, one spoken line per "
            "line as “Speaker: text” (a bare subtitle line works too); a line "
            "that is just a bracketed marker like “[Chapter 2]” is treated as "
            "a scene break. BYO — DeciWaves never ships game text. See docs/BYO.md.")
        self._transcript_help.setWordWrap(True)
        self._transcript_help.setStyleSheet(f"color: {NEUTRAL};")
        self._transcript_help.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        transcript_box = QWidget()
        _tr_v = QVBoxLayout(transcript_box)
        _tr_v.setContentsMargins(0, 0, 0, 0)
        _tr_v.addLayout(self._row(
            QLabel("Transcript:"), self._transcript_edit,
            self._transcript_browse, self._reorder_btn))
        _tr_v.addWidget(self._transcript_help)  # full-width, wraps

        # --- FW required types.json picker ---
        self._types_edit = QLineEdit()
        self._types_edit.setReadOnly(True)
        self._types_edit.setToolTip("Path to types.json (required for subtitle bind)")
        self._types_browse = QPushButton("Browse…")
        self._types_browse.setToolTip("Browse for types.json")
        self._types_status = QLabel("")
        # Help text inline below the field (not behind a HelpIcon tooltip) so a
        # first-time user sees what types.json is without hunting for a hover.
        self._types_help = QLabel(
            "FW\u2019s RTTI (run-time type information) type database, "
            "dumped to JSON. Required for subtitle-bind "
            "(scan + preview work without it). Generate it yourself with "
            "odradek from your own FW install. DeciWaves never ships or "
            "downloads it. Place in the workspace root.")
        self._types_help.setWordWrap(True)
        self._types_help.setStyleSheet(f"color: {NEUTRAL};")
        self._types_help.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        types_box = QWidget()
        _types_v = QVBoxLayout(types_box)
        _types_v.setContentsMargins(0, 0, 0, 0)
        _types_v.addLayout(
            self._row(QLabel("types.json (required):"),
                      self._types_edit, self._types_browse))
        _types_v.addWidget(self._types_help)  # full-width, wraps
        _types_v.addLayout(self._row(self._types_status))

        # --- FW optional gamescript picker ---
        self._gamescript_edit = QLineEdit()
        self._gamescript_edit.setReadOnly(True)
        self._gamescript_edit.setPlaceholderText("Gamescript (BYO, optional -- speaker + order)")
        self._gamescript_edit.setToolTip("Path to a gamescript file for speaker labels and ordering")
        self._gamescript_browse = QPushButton("Browse…")
        self._gamescript_browse.setToolTip("Browse for a gamescript file")
        gamescript_box = self._wrap(self._row(
            QLabel("Gamescript:"), HelpIcon(
                "BYO (Bring Your Own): an optional file that adds speaker "
                "labels + story ordering when supplied. Persisted via setup. "
                "Same file as deciwaves fw run --gamescript."),
            self._gamescript_edit, self._gamescript_browse))

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
        for name, w in self._widgets.items():
            layout.addWidget(w)
            if name == "gpu":
                layout.addWidget(self._asr_hint)
        layout.addWidget(self._scan_warning)

        # wiring
        self._transcript_browse.clicked.connect(self._on_transcript_browse)
        self._reorder_btn.clicked.connect(self._on_reorder)
        self._types_browse.clicked.connect(self._on_types_browse)
        self._gamescript_browse.clicked.connect(self._on_gamescript_browse)
        self._main_story.toggled.connect(lambda _c: self.render_scope_changed.emit())
        self._spine_only.toggled.connect(lambda _c: self.render_scope_changed.emit())
        # tier checkboxes wire their own render_scope_changed at construction.

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
        tier_default = set(defaults.get("tiers", FW_TIERS_DEFAULT).split(","))
        scope_widgets = [self._main_story, self._spine_only, *self._tiers_checks.values()]
        # block scope signals so applying defaults doesn't fire render_scope_changed spuriously
        for w in scope_widgets:
            w.blockSignals(True)
        self._main_story.setChecked(bool(defaults.get("main_story", False)))
        self._spine_only.setChecked(bool(defaults.get("spine_only", False)))
        for token, cb in self._tiers_checks.items():
            cb.setChecked(token in tier_default)
        for w in scope_widgets:
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
        text = cuda_display_text(payload)
        self._gpu_label.setText(text)
        if "CUDA ready" in text:
            self._gpu_label.setStyleSheet(f"color: {OK};")
        elif "unknown" in text:
            self._gpu_label.setStyleSheet(f"color: {NEUTRAL};")
        else:
            self._gpu_label.setStyleSheet(f"color: {WARN};")

        _GPU_GAMES = frozenset({"hzd", "fw"})
        if self._game in _GPU_GAMES and not asr_extra_installed(payload):
            self._asr_hint.setVisible(True)
        else:
            self._asr_hint.setVisible(False)

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

    def render_scope(self) -> dict:
        """The current render scope for the shell to thread into ``render_selection_argv``:
        DS ``{"main_story": bool}``, HZD ``{"spine_only": bool}``, FW ``{"tiers": str}``.

        FW tiers are collected from the checkboxes in canonical order and joined
        into the CSV the CLI expects; if nothing is checked, falls back to the
        shipped default (matching the old empty-field behaviour)."""
        if self._game == "ds":
            return {"main_story": self._main_story.isChecked()}
        if self._game == "hzd":
            return {"spine_only": self._spine_only.isChecked()}
        if self._game == "fw":
            checked = [t for t, _ in _FW_TIER_CHECKS if self._tiers_checks[t].isChecked()]
            return {"tiers": ",".join(checked) or FW_TIERS_DEFAULT}
        return {}

    def set_reorder_enabled(self, enabled: bool) -> None:
        self._reorder_btn.setEnabled(enabled)

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
