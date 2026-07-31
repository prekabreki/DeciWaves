"""Library view (#70, spec §6): the line list. All parsing/filter/selection logic lives in
the Qt-free :mod:`deciwaves.gui.library_model`; this is the thin widget that renders it into
a virtualized QTableView, wires the filter/selection controls, keeps the status line, and
persists checkbox state. Playback on ▶ (#71) and filtered export (#72) are separate issues --
here ▶ only reflects availability and emits an (as-yet unconnected) ``preview_requested``.
"""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import (
    QAbstractTableModel, QEvent, QModelIndex, QObject, QRunnable, Qt,
    QThreadPool, QTimer, Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from deciwaves.gui.export import ExportPanel
from deciwaves.gui.export_model import can_export_mp3, catalog_source_path
from deciwaves.gui.library_model import (
    STORY_ORDER_HINT,
    LineRow,
    availability_by_id,
    check_all,
    check_none,
    distinct_speakers,
    has_known_lengths,
    is_bind_done,
    load_lines,
    load_selection,
    preview_unavailable_tooltip,
    resolve_wav_durations,
    save_selection,
    sort_rows,
    uncheck_barks,
    uncheck_shorter_than,
    visible_rows,
)
from deciwaves.gui.theme import NEUTRAL, RUNNING

# Gray foreground for a pending/unavailable ▶ (spec §6.2/§6.5). A value type -- safe to build
# at import time without a running QApplication.
_PREVIEW_PENDING_FG = QColor(0x88, 0x88, 0x88)


class _TableModel(QAbstractTableModel):
    """Wraps the current filtered+sorted ``LineRow`` slice. Check state is read from the
    view's unchecked set (checked is the default), so a bulk selection command only needs a
    ``dataChanged`` over the checkbox column -- never a full model rebuild."""

    COLS = ["▶", "✓", "#", "id / name", "length", "speaker", "subtitle"]
    COL_PREVIEW, COL_CHECK, COL_ORDER, COL_ID, COL_LEN, COL_SPEAKER, COL_SUB = range(7)

    def __init__(self, view: LibraryView):
        super().__init__()
        self._view = view
        self._visible: list[LineRow] = []

    def set_rows(self, visible: list[LineRow]) -> None:
        old_by_row = {i: r.line_id for i, r in enumerate(self._visible)}
        new_by_id = {r.line_id: i for i, r in enumerate(visible)}
        persistent = self.persistentIndexList()
        self.layoutAboutToBeChanged.emit()
        for idx in persistent:
            if idx.isValid():
                row = idx.row()
                lid = old_by_row.get(row)
                if lid is not None and lid in new_by_id:
                    new_row = new_by_id[lid]
                    if new_row != row:
                        self.changePersistentIndex(idx, self.index(new_row, idx.column()))
        self._visible = visible
        self.layoutChanged.emit()

    def row_at(self, r: int) -> LineRow:
        return self._visible[r]

    def refresh_checks(self) -> None:
        if self._visible:
            top = self.index(0, self.COL_CHECK)
            bot = self.index(len(self._visible) - 1, self.COL_CHECK)
            self.dataChanged.emit(top, bot, [Qt.CheckStateRole])

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._visible)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLS[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == self.COL_CHECK:
            base |= Qt.ItemIsUserCheckable
        return base

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._visible[index.row()]
        col = index.column()
        if role == Qt.CheckStateRole and col == self.COL_CHECK:
            checked = row.line_id not in self._view._unchecked
            return Qt.Checked if checked else Qt.Unchecked
        # Center the ▶ glyph in its cell -- left-aligned (the Qt default) a lone glyph
        # reads as a tree/list disclosure arrow rather than a play control (dogfooding).
        if role == Qt.TextAlignmentRole and col == self.COL_PREVIEW:
            return int(Qt.AlignCenter)
        if role == Qt.DisplayRole:
            if col == self.COL_PREVIEW:
                return "▶"
            if col == self.COL_ORDER:
                return str(row.order_index + 1)
            if col == self.COL_ID:
                return row.name or row.line_id
            if col == self.COL_LEN:
                return "—" if row.length_s is None else f"{row.length_s:.1f}s"
            if col == self.COL_SPEAKER:
                return row.speaker or ""
            if col == self.COL_SUB:
                return row.subtitle or ""
        # ▷ availability (O(1) from the per-refresh lookup -- no per-row syscall on paint):
        # an unavailable preview is dimmed and carries a "why" tooltip (spec §6.2/§6.5).
        if col == self.COL_PREVIEW and role in (Qt.ForegroundRole, Qt.ToolTipRole):
            if self._view._available.get(row.line_id, False):
                if role == Qt.ToolTipRole:
                    return "Play preview"
                return None
            if role == Qt.ForegroundRole:
                return _PREVIEW_PENDING_FG
            return self._view._unavailable_tooltip
        return None

    def setData(self, index, value, role=Qt.EditRole) -> bool:
        if role == Qt.CheckStateRole and index.column() == self.COL_CHECK:
            checked = Qt.CheckState(value) == Qt.Checked
            self._view._set_checked(self._visible[index.row()].line_id, checked)
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            return True
        return False


class _EmptyStateOverlay(QWidget):
    """Child-of-viewport overlay that renders the empty-state guidance as real, accessible
    widgets (a ``QLabel`` plus, in the no-results case, a "Clear filters" button) instead of
    the old painted ``drawText`` pixels (issue #302, audit L4).

    Being a viewport child, it pins to the visible area (it never scrolls away with rows) and
    is hidden whenever rows are present so it can never swallow table events. The two states
    keep their old look: grey for "no catalog"/"no workspace", amber for "no results".
    """

    _GREY = "#888888"
    _AMBER = "#CC8800"

    def __init__(self, viewport: QWidget, view: LibraryView):
        super().__init__(viewport)
        self._view = view
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(True)
        font = self._label.font()
        font.setPointSize(font.pointSize() + 4)
        self._label.setFont(font)
        self._clear = QPushButton("Clear filters", self)
        self._clear.setAccessibleName("Clear filters")
        self._clear.clicked.connect(self._clear_filters)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addStretch(1)
        layout.addWidget(self._label)
        layout.addWidget(self._clear, 0, Qt.AlignHCenter)
        layout.addStretch(1)
        self.hide()

    def set_message(self, text: str | None, has_rows: bool) -> None:
        """Show *text* (grey when the catalog is empty, amber when it's a filter hit) with the
        "Clear filters" button only in the no-results case; hide the overlay entirely when
        rows are present so it cannot intercept clicks."""
        if text is None:
            self.hide()
            return
        self._label.setText(text)
        self._label.setAccessibleName(text)
        self._label.setStyleSheet(f"color: {self._AMBER if has_rows else self._GREY};")
        self._clear.setVisible(has_rows)
        self.show()

    def _clear_filters(self) -> None:
        self._view._search.clear()


class _LibraryTableView(QTableView):
    """QTableView subclass that overlays empty-state guidance on the viewport when no rows are
    visible — the message is a real ``QLabel``, not painted text, so assistive tech sees it.

    Three distinct messages:
    * no workspace → "Choose an output folder for your reels"
    * ``total == 0`` → "No catalog yet — run Scan on the Pipeline tab"
    * ``total > 0`` and ``visible == 0`` → "No lines match —" + a "Clear filters" button

    The overlay disappears once rows are present/visible.
    """

    def __init__(self, view: LibraryView):
        super().__init__()
        self._view = view
        self._overlay = _EmptyStateOverlay(self.viewport(), view)
        self._overlay.setGeometry(self.viewport().rect())
        self.viewport().installEventFilter(self)
        self._sync_overlay()

    @property
    def overlay_text(self) -> str | None:
        if not self._view._workspace:
            return "Choose an output folder for your reels"
        if not self._view._rows:
            return "No catalog yet — run Scan on the Pipeline tab"
        if not self._view._visible:
            return "No lines match —"
        return None

    def _sync_overlay(self) -> None:
        # Re-pin geometry on every state change: while the view is hidden (e.g. during
        # construction) Qt delivers no resize events, so the overlay would otherwise keep a
        # stale size until the widget is shown.
        self._overlay.setGeometry(self.viewport().rect())
        self._overlay.set_message(self.overlay_text, bool(self._view._rows))

    def showEvent(self, event):
        # Re-pin when first shown: the viewport may have been resized while hidden, which
        # Qt applies without delivering a resize event.
        super().showEvent(event)
        self._overlay.setGeometry(self.viewport().rect())

    def eventFilter(self, obj, event):
        # Keep the overlay pinned to the visible viewport area (it shrinks when a scrollbar
        # appears, so it must follow the viewport, not the table).
        if obj is self.viewport() and event.type() == QEvent.Resize:
            self._overlay.setGeometry(self.viewport().rect())
        return super().eventFilter(obj, event)


class _DurationSignaller(QObject):
    """QObject whose ``finished`` signal is emitted from the thread pool to the main thread
    with the generation tag and resolved durations."""
    finished = Signal(int, object)  # generation, dict[str, float | None]


class _DurationTask(QRunnable):
    """Runs ``resolve_wav_durations`` on a background thread and emits the result via the
    *signaller* when done. Carries a *generation* tag so the view can discard stale results
    when ``refresh()`` fires again before the probe finishes."""

    def __init__(self, signaller: _DurationSignaller, generation: int,
                 rows: list[LineRow]):
        super().__init__()
        self._signaller = signaller
        self._generation = generation
        self._rows = rows

    def run(self) -> None:
        durations = resolve_wav_durations(self._rows)
        self._signaller.finished.emit(self._generation, durations)


class _ParseSignaller(QObject):
    """QObject whose ``finished`` signal is emitted from the thread pool to the main thread
    with the generation tag and parsed lines. Mirrors ``_DurationSignaller``."""
    finished = Signal(int, object)  # generation, list[LineRow]


class _ParseTask(QRunnable):
    """Runs ``load_lines`` on a background thread and emits the result via the *signaller*
    when done. Carries a *generation* tag so the view can discard stale results when
    ``refresh()`` fires again before the parse finishes."""

    def __init__(self, signaller: _ParseSignaller, generation: int,
                 workspace: str, game: str):
        super().__init__()
        self._signaller = signaller
        self._generation = generation
        self._workspace = workspace
        self._game = game

    def run(self) -> None:
        rows = load_lines(self._workspace, self._game)
        self._signaller.finished.emit(self._generation, rows)


class LibraryView(QWidget):
    """The line list with search/speaker/dupe/no-subtitle filters, undoable selection
    commands, a persisted checkbox column, and an availability-aware ▶ preview column."""

    preview_requested = Signal(str)  # line_id -- wired to playback in #71

    # header section -> sort key on LineRow (preview/check columns don't sort)
    _SORT_KEYS = {
        _TableModel.COL_ORDER: "order_index",
        _TableModel.COL_ID: "line_id",
        _TableModel.COL_LEN: "length_s",
        _TableModel.COL_SPEAKER: "speaker",
        _TableModel.COL_SUB: "subtitle",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._game: str | None = None  # no game loaded yet -> first refresh is a game change
        self._workspace = ""
        self._rows: list[LineRow] = []
        self._visible: list[LineRow] = []
        self._unchecked: set[str] = set()
        self._undo: list[set[str]] = []
        self._bind_done = False
        self._available: dict[str, bool] = {}      # line_id -> ▷ available (per-refresh)
        self._unavailable_tooltip = ""
        self._sort_key: str | None = None
        self._sort_desc = False
        self._checked_count = 0
        self._can_export_mp3 = False
        self._has_catalog = False
        self._order_active = False
        self._order_count = 0
        self._duration_generation = 0
        self._duration_signaller = _DurationSignaller()
        self._duration_signaller.finished.connect(self._on_durations_ready)
        self._duration_pool = QThreadPool()
        self._parse_generation = 0
        self._parse_signaller = _ParseSignaller()
        self._parse_signaller.finished.connect(self._on_lines_loaded)
        self._parse_pool = QThreadPool()
        self._parse_game_changed = False

        # Selection debounce (issue #133 L3): a real member QTimer so rapid Space-toggling
        # produces exactly one disk write.
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(150)
        self._selection_timer.timeout.connect(self._flush_selection)

        # --- filter row ---
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search subtitle / id")
        self._speaker = QComboBox()
        self._speaker.addItem("all")
        self._hide_dupes = QCheckBox("Hide duplicates")
        self._hide_dupes.setToolTip(
            "Hides repeated lines within a scene — the 2nd+ time the exact same "
            "subtitle recurs (e.g. a stock line reused). This mirrors the "
            "de-duplication the exported reel already does, so it only declutters the "
            "list; it does not change what you export.")
        self._hide_nosub = QCheckBox("Hide no-subtitle")
        self._hide_nosub.setToolTip(
            "Hides voice lines that have audio but no on-screen subtitle — grunts, "
            "breaths, PA announcements, radio bleed, and lines the game never "
            "captioned. It's real audio, not silence. Useful because blank-subtitle "
            "rows can't be identified without playing them and are usually non-story "
            "noise; leave it off if you want incidental vocalizations too.")

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Search:"))
        filters.addWidget(self._search, 1)
        filters.addWidget(QLabel("Speaker:"))
        filters.addWidget(self._speaker)
        filters.addWidget(self._hide_dupes)
        filters.addWidget(self._hide_nosub)

        # --- selection row ---
        self._short_secs = QDoubleSpinBox()
        self._short_secs.setRange(0.1, 120.0)
        self._short_secs.setSingleStep(0.5)
        self._short_secs.setValue(1.0)
        self._short_secs.setSuffix(" s")
        self._uncheck_short_btn = QPushButton("Uncheck shorter than")
        self._uncheck_barks_btn = QPushButton("Uncheck barks")
        self._uncheck_barks_btn.setToolTip(
            "Barks are short, incidental voice lines — ambient NPC chatter, combat "
            "callouts and the like — rather than story dialogue. This unchecks them "
            "across the whole list (not just the filtered view), using a per-game "
            "heuristic: DS = lines with no subtitle; HZD = ambient-category or "
            "no-subtitle lines; FW = no subtitle or one-word lines.")
        self._check_all_btn = QPushButton("Check all")
        self._check_none_btn = QPushButton("Check none")
        self._undo_btn = QPushButton("Undo")

        selection = QHBoxLayout()
        selection.addWidget(self._uncheck_short_btn)
        selection.addWidget(self._short_secs)
        selection.addWidget(self._uncheck_barks_btn)
        selection.addWidget(self._check_all_btn)
        selection.addWidget(self._check_none_btn)
        selection.addWidget(self._undo_btn)
        selection.addStretch(1)

        # --- table ---
        self._model = _TableModel(self)
        self._table = _LibraryTableView(self)
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSortingEnabled(False)  # we sort the model ourselves (None-last)
        header = self._table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(_TableModel.COL_SUB, QHeaderView.Stretch)
        header.setSectionResizeMode(_TableModel.COL_PREVIEW, QHeaderView.Fixed)
        header.setSectionResizeMode(_TableModel.COL_ORDER, QHeaderView.Fixed)
        header.sectionClicked.connect(self._on_header_clicked)
        self._table.setColumnWidth(_TableModel.COL_PREVIEW, 36)
        self._table.setColumnWidth(_TableModel.COL_CHECK, 30)
        self._table.setColumnWidth(_TableModel.COL_ORDER, 40)
        self._table.setColumnWidth(_TableModel.COL_ID, 140)
        self._table.setColumnWidth(_TableModel.COL_LEN, 65)
        self._table.setColumnWidth(_TableModel.COL_SPEAKER, 110)

        self._status = QLabel("")

        # Export panel (#72, spec §8): operates on the checked rows. The shell connects its
        # intent signals and drives its running-state; the Library keeps its context in sync.
        self.export = ExportPanel()

        self._story_order_hint = QLabel(STORY_ORDER_HINT)
        self._story_order_hint.setStyleSheet(f"color: {NEUTRAL}; font-style: italic;")
        self._story_order_hint.setWordWrap(True)
        self._story_order_hint.hide()

        self._job_running_banner = QLabel(
            "A job is running — this list may change when it finishes.")
        self._job_running_banner.setStyleSheet(f"color: {RUNNING};")
        self._job_running_banner.hide()

        layout = QVBoxLayout(self)
        layout.addLayout(filters)
        layout.addLayout(selection)
        layout.addWidget(self._story_order_hint)
        layout.addWidget(self._job_running_banner)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._status)
        layout.addWidget(self.export)

        # --- search debounce (#120) ---
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(150)
        self._debounce_timer.timeout.connect(self._apply_filters)

        # --- wiring ---
        self._search.textChanged.connect(self._on_search_changed)
        self._speaker.currentIndexChanged.connect(self._apply_filters)
        self._hide_dupes.toggled.connect(self._apply_filters)
        self._hide_nosub.toggled.connect(self._apply_filters)
        self._uncheck_short_btn.clicked.connect(self._on_uncheck_short)
        self._uncheck_barks_btn.clicked.connect(self._on_uncheck_barks)
        self._check_all_btn.clicked.connect(self._on_check_all)
        self._check_none_btn.clicked.connect(self._on_check_none)
        self._undo_btn.clicked.connect(self._on_undo)
        self._table.clicked.connect(self._on_cell_clicked)
        # desktop conventions (spec §6.5): enter plays the current row, space toggles its
        # checkbox -- handled here rather than relying on the table's column-dependent default.
        self._table.installEventFilter(self)

    # --- data lifecycle ----------------------------------------------------

    def refresh(self, game: str, workspace: str) -> None:
        """Reload the game's lines + persisted selection and rebuild the table.

        A **game change** drops the prior game's stray filter/sort state (search, sort
        key/dir, both hide toggles, speaker) -- the list is per-game. A **same-game** refresh
        (e.g. a job finished for the current game) preserves all filter/sort state so an
        in-progress curation survives a background reload.

        CSV parsing runs on a background ``QThreadPool`` worker so the UI thread is never
        blocked by the parse (~200 ms at 26 k rows). WAV durations are also probed
        asynchronously and fill in progressively."""
        game_changed = game != self._game
        self._game = game
        self._workspace = workspace
        self._parse_game_changed = game_changed
        if not workspace:
            self._rows = []
            self._visible = []
            self._unchecked = set()
            self._checked_count = 0
            self._undo.clear()
            self._bind_done = False
            self._available = {}
            self._can_export_mp3 = False
            self._has_catalog = False
            self._order_active = False
            self._order_count = 0
            self._duration_generation += 1
            self._parse_generation += 1
            if game_changed:
                self._reset_filter_state()
            self._apply_filters()
            return

        # Row-independent state computed immediately on the UI thread.
        self._bind_done = is_bind_done(workspace, game)
        self._unavailable_tooltip = preview_unavailable_tooltip(game, bind_done=self._bind_done)
        self._can_export_mp3 = can_export_mp3(workspace, game)
        self._has_catalog = catalog_source_path(workspace, game) is not None
        self._undo.clear()

        # Bump both generations so any still-in-flight tasks discard themselves on finish.
        self._duration_generation += 1
        self._parse_generation += 1

        if game_changed:
            self._reset_filter_state()

        self._story_order_hint.setVisible(game == "ds")

        # Brief loading state while the parse runs on a background thread.
        self._status.setText("Loading...")

        task = _ParseTask(
            self._parse_signaller, self._parse_generation, workspace, game)
        self._parse_pool.start(task)

    def _reset_filter_state(self) -> None:
        """Clear search text, sort key/dir, and both hide toggles to defaults (called on a
        game change only). Signals are blocked so the single ``_apply_filters`` at the end of
        ``refresh`` does the one rebuild."""
        self._sort_key, self._sort_desc = None, False
        for w in (self._search, self._hide_dupes, self._hide_nosub):
            w.blockSignals(True)
        self._search.clear()
        self._hide_dupes.setChecked(False)
        self._hide_nosub.setChecked(False)
        for w in (self._search, self._hide_dupes, self._hide_nosub):
            w.blockSignals(False)

    def _on_lines_loaded(self, generation: int, rows: list[LineRow]) -> None:
        """Handle the result of a background CSV parse. Discards stale results
        from a prior ``refresh`` (whose generation was already bumped).

        Sets ``_rows`` and all derived per-refresh state, rebuilds the speaker
        dropdown, and applies filters so the table populates with the fresh data.
        Also launches the WAV-duration probe for FW (the duration generation was
        already bumped in ``refresh`` so any in-flight probe will discard itself
        naturally)."""
        if generation != self._parse_generation:
            return

        self._rows = rows
        self._unchecked = load_selection(self._workspace, self._game)
        self._checked_count = sum(
            1 for r in self._rows if r.line_id not in self._unchecked)
        self._available = availability_by_id(self._rows, self._game, bind_done=self._bind_done)

        from deciwaves.gui.export_model import has_imported_order
        self._order_active = has_imported_order(self._workspace, self._game) if self._game else False
        self._order_count = len(self._rows) if self._order_active else 0

        prev_speaker = self._speaker.currentText()
        self._speaker.blockSignals(True)
        self._speaker.clear()
        self._speaker.addItem("all")
        for sp in distinct_speakers(self._rows):
            self._speaker.addItem(sp)
        restore = self._speaker.findText(prev_speaker) if not self._parse_game_changed else -1
        self._speaker.setCurrentIndex(restore if restore >= 0 else 0)
        self._speaker.blockSignals(False)

        self._set_shortlen_enabled(has_known_lengths(self._rows))

        self._apply_filters()

        if self._game == "fw" and self._rows:
            task = _DurationTask(
                self._duration_signaller, self._duration_generation, list(self._rows))
            self._duration_pool.start(task)

    def _on_search_changed(self) -> None:
        if not self._debounce_timer.isActive():
            self._apply_filters()
        self._debounce_timer.start()

    def _apply_filters(self) -> None:
        self._debounce_timer.stop()
        self._visible = sort_rows(
            visible_rows(self._rows, search=self._search.text(),
                         speaker=self._speaker.currentText() or "all",
                         hide_dupes=self._hide_dupes.isChecked(),
                         hide_no_subtitle=self._hide_nosub.isChecked()),
            self._sort_key, self._sort_desc)
        self._model.set_rows(self._visible)
        self._table._sync_overlay()
        self._update_status()

    def _on_durations_ready(self, generation: int, durations: dict[str, float | None]) -> None:
        """Handle the result of a background WAV-duration probe. Discards stale results
        from a prior ``refresh`` (whose generation was already bumped).

        Updates ``_rows`` in-place with the filled durations and re-applies filters so the
        table repaints with the new length column values. The re-filter also handles the
        case where the user had sorted by length and order changes as None entries fill in."""
        if generation != self._duration_generation:
            return
        if not durations:
            return

        by_id = {r.line_id: i for i, r in enumerate(self._rows)}
        for lid, dur in durations.items():
            idx = by_id.get(lid)
            if idx is not None and self._rows[idx].length_s != dur:
                self._rows[idx] = replace(self._rows[idx], length_s=dur)

        self._apply_filters()

        self._set_shortlen_enabled(has_known_lengths(self._rows))

    def _set_shortlen_enabled(self, has_len: bool) -> None:
        """Enable/disable the "Uncheck shorter than" control + its spinbox, and set a
        tooltip that explains WHY when it's disabled -- dogfooding: DS/HZD carry no
        per-line duration, so the control was permanently greyed with no indication."""
        self._short_secs.setEnabled(has_len)
        self._uncheck_short_btn.setEnabled(has_len)
        if has_len:
            tip = ("Unchecks every line shorter than this many seconds "
                   "(uses each line's decoded audio length).")
        elif self._game == "fw":
            tip = ("Line durations are still loading — this filter enables once "
                   "they're ready.")
        else:
            tip = ("Not available for this game: filtering by length needs each line's "
                   "audio duration, which only Forbidden West provides. DS/HZD lines "
                   "carry no duration (the Length column shows “—”).")
        self._short_secs.setToolTip(tip)
        self._uncheck_short_btn.setToolTip(tip)

    def _on_header_clicked(self, section: int) -> None:
        key = self._SORT_KEYS.get(section)
        if key is None:
            return
        if key == self._sort_key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_key, self._sort_desc = key, False
        self._apply_filters()

    # --- selection (never touched by filters/sort) -------------------------

    def _set_checked(self, line_id: str, checked: bool) -> None:
        """A single checkbox toggle: update in-memory state immediately, defer disk write."""
        if checked:
            self._unchecked.discard(line_id)
            self._checked_count += 1
        else:
            self._unchecked.add(line_id)
            self._checked_count -= 1
        self._defer_save()
        self._update_status()

    def _defer_save(self) -> None:
        """Start or restart the selection debounce timer. ``QTimer.start()`` always resets the
        interval, so a rapid succession of toggles produces exactly one eventual flush."""
        self._selection_timer.start()

    def _flush_selection(self) -> None:
        """Persist the unchecked set to disk (called by the debounce timer, or immediately
        for bulk commands)."""
        if not self._workspace:
            return
        save_selection(self._workspace, self._game, self._unchecked)

    def flush_pending_selection(self) -> None:
        """Flush any pending selection save to disk immediately.

        If the debounce timer is active, stop it and persist the current unchecked set
        to disk. Strict no-op when nothing is pending — guards against gratuitous disk
        writes during every pytest-qt teardown ``close()``."""
        if self._selection_timer.isActive():
            self._selection_timer.stop()
            self._flush_selection()

    def _apply_selection(self, new_unchecked: set[str]) -> None:
        """Apply a bulk selection command — flush immediately, not debounced."""
        if not self._workspace:
            return
        self._selection_timer.stop()
        self._undo.append(set(self._unchecked))
        self._unchecked = new_unchecked
        self._checked_count = sum(
            1 for r in self._rows if r.line_id not in self._unchecked)
        self._flush_selection()
        self._model.refresh_checks()
        self._update_status()

    def _on_uncheck_short(self) -> None:
        """Uncheck rows shorter than *seconds* — operates on ALL loaded rows (not just the
        filtered ``_visible`` slice), because a length-based gate should never depend on what
        the user typed in the search box. (issue #133 L4 — scope made explicit.)"""
        self._apply_selection(
            uncheck_shorter_than(self._rows, self._unchecked, self._short_secs.value()))

    def _on_uncheck_barks(self) -> None:
        """Uncheck bark/chatter lines — operates on ALL loaded rows. Barks are identified by
        per-game heuristics (empty subtitle, ambient category, etc.) that are independent of
        the current search/speaker filter. (issue #133 L4 — scope made explicit.)"""
        self._apply_selection(uncheck_barks(self._rows, self._unchecked, self._game))

    def _on_check_all(self) -> None:
        """Check ALL loaded rows — never just the visible subset. The unchecked set becomes
        empty, making every line eligible for export regardless of current filters.
        (issue #133 L4 — scope made explicit.)"""
        self._apply_selection(check_all(self._rows))

    def _on_check_none(self) -> None:
        """Uncheck ALL loaded rows — never just the visible subset. The unchecked set becomes
        every line_id, making every line ineligible for export regardless of current filters.
        (issue #133 L4 — scope made explicit.)"""
        self._apply_selection(check_none(self._rows))

    def _on_undo(self) -> None:
        self._selection_timer.stop()
        if not self._undo:
            return
        self._unchecked = self._undo.pop()
        self._checked_count = sum(
            1 for r in self._rows if r.line_id not in self._unchecked)
        self._flush_selection()
        self._model.refresh_checks()
        self._update_status()

    # --- preview (#71 wires actual playback) -------------------------------

    def _on_cell_clicked(self, index) -> None:
        if index.column() != _TableModel.COL_PREVIEW:
            return
        row = self._model.row_at(index.row())
        if self._available.get(row.line_id, False):  # unavailable ▶ is a no-op
            self.preview_requested.emit(row.line_id)

    def eventFilter(self, obj, event):
        """Keyboard on the table (spec §6.5): Enter/Return previews the current row (same
        availability gate as clicking ▷); Space toggles the current row's checkbox from any
        column, not just the check column."""
        if obj is self._table and event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._preview_current_row()
                return True
            if key == Qt.Key_Space:
                self._toggle_current_row_check()
                return True
        return super().eventFilter(obj, event)

    def _current_row(self) -> LineRow | None:
        idx = self._table.currentIndex()
        return self._model.row_at(idx.row()) if idx.isValid() else None

    def _preview_current_row(self) -> None:
        row = self._current_row()
        if row is not None and self._available.get(row.line_id, False):
            self.preview_requested.emit(row.line_id)

    def _toggle_current_row_check(self) -> None:
        row = self._current_row()
        if row is None:
            return
        self._set_checked(row.line_id, row.line_id in self._unchecked)  # flip current state
        self._model.refresh_checks()

    def audio_path_for(self, line_id: str) -> str | None:
        """The row's ``audio_path`` for *line_id* (DS stream path / FW WAV; ``None`` for HZD or
        an unknown id) -- the shell hands it to the preview resolver alongside the id."""
        for r in self._rows:
            if r.line_id == line_id:
                return r.audio_path
        return None

    # --- checked-set accessors (export, #72) -------------------------------

    def unchecked_ids(self) -> set[str]:
        """The unchecked line_ids among the loaded rows -- a LIVE view (every toggle already
        saves selection.json, but reading state here avoids any stale-flush race). The
        filtered-CSV writer wants the unchecked set: it keeps rows whose id is NOT in it."""
        loaded = {r.line_id for r in self._rows}
        return {lid for lid in self._unchecked if lid in loaded}

    def checked_ids(self) -> set[str]:
        return {r.line_id for r in self._rows if r.line_id not in self._unchecked}

    def checked_rows(self) -> list[LineRow]:
        """The checked ``LineRow``s (id + audio_path), for the batch Dump-WAV worker."""
        return [r for r in self._rows if r.line_id not in self._unchecked]

    # --- status + test accessors -------------------------------------------

    def _sync_export(self) -> None:
        """Keep the Export panel's context (checked-count + which artifacts exist) current.
        Called on every status update, so it tracks refreshes and per-toggle selection edits.
        The shell owns the panel's running-state separately. Uses cached booleans from the
        last refresh -- no filesystem access per call (issue #133 L3)."""
        if self._game is None:
            return
        self.export.set_context(
            self._game, self._workspace, self.checked_count(),
            self._can_export_mp3, self._has_catalog,
            order_active=self._order_active, order_count=self._order_count)

    def _update_status(self) -> None:
        self._status.setText(self.status_text())
        self._sync_export()

    def rows(self) -> list[LineRow]:
        return list(self._rows)

    def total_count(self) -> int:
        return len(self._rows)

    def visible_count(self) -> int:
        return len(self._visible)

    def checked_count(self) -> int:
        return self._checked_count

    def status_text(self) -> str:
        base = f"{self.checked_count()} checked · {self.visible_count()} visible · {self.total_count()} total"
        if self._sort_key is None:
            base += " · story order"
        return base

    def _wait_for_parse(self) -> None:
        """Wait for any in-flight parse task to finish and deliver its result to the
        main thread. Test-only helper -- never called in production code paths."""
        self._parse_pool.waitForDone()
        QApplication.processEvents()

    def set_job_running(self, running: bool) -> None:
        if running:
            self._job_running_banner.show()
        else:
            self._job_running_banner.hide()
