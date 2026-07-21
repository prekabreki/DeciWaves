"""Library view (#70, spec §6): the line list. All parsing/filter/selection logic lives in
the Qt-free :mod:`deciwaves.gui.library_model`; this is the thin widget that renders it into
a virtualized QTableView, wires the filter/selection controls, keeps the status line, and
persists checkbox state. Playback on ▶ (#71) and filtered export (#72) are separate issues --
here ▶ only reflects availability and emits an (as-yet unconnected) ``preview_requested``.
"""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    save_selection,
    sort_rows,
    uncheck_barks,
    uncheck_shorter_than,
    visible_rows,
)

# Gray foreground for a pending/unavailable ▶ (spec §6.2/§6.5). A value type -- safe to build
# at import time without a running QApplication.
_PREVIEW_PENDING_FG = QColor(0x88, 0x88, 0x88)


class _TableModel(QAbstractTableModel):
    """Wraps the current filtered+sorted ``LineRow`` slice. Check state is read from the
    view's unchecked set (checked is the default), so a bulk selection command only needs a
    ``dataChanged`` over the checkbox column -- never a full model rebuild."""

    COLS = ["▶", "✓", "id / name", "length", "speaker", "subtitle"]
    COL_PREVIEW, COL_CHECK, COL_ID, COL_LEN, COL_SPEAKER, COL_SUB = range(6)

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
        if role == Qt.DisplayRole:
            if col == self.COL_PREVIEW:
                return "▶"
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


class _LibraryTableView(QTableView):
    """QTableView subclass that paints a viewport overlay when no rows are visible.

    Two distinct messages:
    * ``total == 0`` → "No catalog yet — run Scan on the Pipeline tab"
    * ``total > 0`` and ``visible == 0`` → "No lines match — [Clear filters]"

    The overlay disappears once rows are present/visible.
    """

    def __init__(self, view: LibraryView):
        super().__init__()
        self._view = view

    @property
    def overlay_text(self) -> str | None:
        if not self._view._rows:
            return "No catalog yet — run Scan on the Pipeline tab"
        if not self._view._visible:
            return "No lines match — [Clear filters]"
        return None

    def paintEvent(self, event):
        super().paintEvent(event)
        text = self.overlay_text
        if text is None:
            return
        color = QColor(0x88, 0x88, 0x88) if not self._view._rows else QColor(0xCC, 0x88, 0x00)
        p = QPainter(self.viewport())
        p.setPen(color)
        font = p.font()
        font.setPointSize(font.pointSize() + 4)
        p.setFont(font)
        p.drawText(self.viewport().rect(), Qt.AlignCenter, text)
        p.end()

    def mouseReleaseEvent(self, event):
        if self._view.total_count() > 0 and self._view.visible_count() == 0:
            self._view._search.clear()
            return
        super().mouseReleaseEvent(event)


class LibraryView(QWidget):
    """The line list with search/speaker/dupe/no-subtitle filters, undoable selection
    commands, a persisted checkbox column, and an availability-aware ▶ preview column."""

    preview_requested = Signal(str)  # line_id -- wired to playback in #71

    # header section -> sort key on LineRow (preview/check columns don't sort)
    _SORT_KEYS = {
        _TableModel.COL_ID: "line_id",
        _TableModel.COL_LEN: "length_s",
        _TableModel.COL_SPEAKER: "speaker",
        _TableModel.COL_SUB: "subtitle",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._game: str | None = None  # no game loaded yet -> first refresh is a game change
        self._workspace = "."
        self._rows: list[LineRow] = []
        self._visible: list[LineRow] = []
        self._unchecked: set[str] = set()
        self._undo: list[set[str]] = []
        self._bind_done = False
        self._available: dict[str, bool] = {}      # line_id -> ▷ available (per-refresh)
        self._unavailable_tooltip = ""
        self._sort_key: str | None = None
        self._sort_desc = False

        # --- filter row ---
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search subtitle / id")
        self._speaker = QComboBox()
        self._speaker.addItem("all")
        self._hide_dupes = QCheckBox("Hide duplicates (dropped at render by the pipeline)")
        self._hide_nosub = QCheckBox("Hide no-subtitle (dropped at render by the pipeline)")

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
        header.setSectionResizeMode(_TableModel.COL_SUB, QHeaderView.Stretch)
        header.sectionClicked.connect(self._on_header_clicked)
        self._table.setColumnWidth(_TableModel.COL_PREVIEW, 36)

        self._status = QLabel("")

        # Export panel (#72, spec §8): operates on the checked rows. The shell connects its
        # intent signals and drives its running-state; the Library keeps its context in sync.
        self.export = ExportPanel()

        layout = QVBoxLayout(self)
        layout.addLayout(filters)
        layout.addLayout(selection)
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
        in-progress curation survives a background reload."""
        game_changed = game != self._game
        self._game = game
        self._workspace = workspace
        self._rows = load_lines(workspace, game)
        self._unchecked = load_selection(workspace, game)
        self._bind_done = is_bind_done(workspace, game)
        self._available = availability_by_id(self._rows, game, bind_done=self._bind_done)
        self._unavailable_tooltip = preview_unavailable_tooltip(game, bind_done=self._bind_done)
        self._undo.clear()

        if game_changed:
            self._reset_filter_state()

        # Speaker list is game-specific, so it is always rebuilt; a same-game refresh restores
        # the prior selection if it still exists, a game change resets to "all".
        prev_speaker = self._speaker.currentText()
        self._speaker.blockSignals(True)
        self._speaker.clear()
        self._speaker.addItem("all")
        for sp in distinct_speakers(self._rows):
            self._speaker.addItem(sp)
        restore = self._speaker.findText(prev_speaker) if not game_changed else -1
        self._speaker.setCurrentIndex(restore if restore >= 0 else 0)
        self._speaker.blockSignals(False)

        has_len = has_known_lengths(self._rows)
        self._short_secs.setEnabled(has_len)
        self._uncheck_short_btn.setEnabled(has_len)

        self._apply_filters()

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
        self._update_status()

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
        """A single checkbox toggle: update + persist the unchecked set (no model rebuild)."""
        if checked:
            self._unchecked.discard(line_id)
        else:
            self._unchecked.add(line_id)
        save_selection(self._workspace, self._game, self._unchecked)
        self._update_status()

    def _apply_selection(self, new_unchecked: set[str]) -> None:
        """Apply a bulk selection command, pushing the prior set onto the undo stack."""
        self._undo.append(set(self._unchecked))
        self._unchecked = new_unchecked
        save_selection(self._workspace, self._game, self._unchecked)
        self._model.refresh_checks()
        self._update_status()

    def _on_uncheck_short(self) -> None:
        self._apply_selection(
            uncheck_shorter_than(self._rows, self._unchecked, self._short_secs.value()))

    def _on_uncheck_barks(self) -> None:
        self._apply_selection(uncheck_barks(self._rows, self._unchecked, self._game))

    def _on_check_all(self) -> None:
        self._apply_selection(check_all(self._rows))

    def _on_check_none(self) -> None:
        self._apply_selection(check_none(self._rows))

    def _on_undo(self) -> None:
        if not self._undo:
            return
        self._unchecked = self._undo.pop()
        save_selection(self._workspace, self._game, self._unchecked)
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
        The shell owns the panel's running-state separately."""
        if self._game is None:
            return
        self.export.set_context(
            self._game, self._workspace, self.checked_count(),
            can_export_mp3(self._workspace, self._game),
            catalog_source_path(self._workspace, self._game) is not None)

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
        return sum(1 for r in self._rows if r.line_id not in self._unchecked)

    def status_text(self) -> str:
        return f"{self.checked_count()} checked · {self.visible_count()} visible · {self.total_count()} total"
