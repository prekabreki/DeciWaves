"""Thin Qt Export panel + batch Dump-WAV worker (#72, spec §8): the three output flows on the
CHECKED library rows -- Export MP3 (filtered-manifest render), Dump WAV (batch decode), Export
catalog CSV.

All non-Qt logic lives in the Qt-free :mod:`deciwaves.gui.export_model` (the filtered-CSV
writer, argv builder, catalog resolver) and :mod:`deciwaves.gui.preview_model` (the per-line
decode the dump reuses); this module only adds the widgets and the off-UI-thread batch worker.

The panel is intent-only: it emits ``export_mp3_requested`` / ``dump_wav_requested`` /
``export_catalog_requested`` (opening the file dialogs itself) and the shell turns them into a
render job / a thread-pool dump / a file copy. Enable-state is driven by two orthogonal calls
the Library and shell own: :meth:`ExportPanel.set_context` (game + checked-count + what
artifacts exist) and :meth:`ExportPanel.set_running` / :meth:`ExportPanel.set_dumping` (the
one-job-at-a-time mutual exclusion, mirroring ``PipelineControls.set_running``).
"""
from __future__ import annotations

import os
import shutil

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from deciwaves.gui.export_model import (
    ROUND_TRIP_INSTRUCTIONS,
    catalog_source_path,
    render_input_source,
)
from deciwaves.gui.theme import NEUTRAL
from deciwaves.gui.preview_model import PreviewError

_BITRATES = ("96", "128", "192")
_DEFAULT_BITRATE = 128
# Split size is a fixed constant in v1 (spec §8.2): static text, no field. --target-mb is #75.
_SPLIT_LABEL = "Reels split automatically at ~285 MB"


class ExportPanel(QWidget):
    """Export controls on the checked rows (spec §8.2). Thin: emits intents, opens dialogs,
    reflects enable-state; the shell does the real work."""

    export_mp3_requested = Signal(int)       # bitrate (DS-meaningful; 128 for HZD/FW)
    dump_wav_requested = Signal(str)          # chosen destination folder
    export_catalog_requested = Signal(str)    # chosen destination file
    dump_cancel_requested = Signal()          # the running dump should stop
    export_order_requested = Signal(str)      # chosen dest file (writes the ordered artifact)
    import_order_requested = Signal(str)      # chosen source file (the user's edited CSV)
    revert_order_requested = Signal()         # discard the override, back to auto order

    def __init__(self, parent=None):
        super().__init__(parent)
        self._game: str | None = None
        self._workspace = "."
        self._checked = 0
        self._can_mp3 = False
        self._can_catalog = False
        self._running = False
        self._dumping = False
        self._workspace_empty = False
        self._order_active = False
        self._order_count = 0

        self._mp3_btn = QPushButton("Export MP3")
        self._bitrate = QComboBox()
        self._bitrate.addItems(_BITRATES)
        self._bitrate.setCurrentText(str(_DEFAULT_BITRATE))
        self._bitrate_label = QLabel("128k")   # HZD/FW are hardcoded 128k (truth in labeling)
        self._dump_btn = QPushButton("Dump WAV (selected)")
        self._catalog_btn = QPushButton("Export catalog CSV")
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._status = QLabel("")

        self._split_label = QLabel(_SPLIT_LABEL)
        self._split_label.setWordWrap(True)

        row1 = QHBoxLayout()
        row1.addWidget(self._mp3_btn)
        row1.addWidget(QLabel("Bitrate:"))
        row1.addWidget(self._bitrate)
        row1.addWidget(self._bitrate_label)
        row1.addWidget(self._split_label, 1)
        row1.addStretch(1)

        row2 = QHBoxLayout()
        row2.addWidget(self._dump_btn)
        row2.addWidget(self._catalog_btn)
        row2.addStretch(1)

        self._order_export_btn = QPushButton("Export order CSV…")
        self._order_import_btn = QPushButton("Import order CSV…")
        self._order_revert_btn = QPushButton("Revert to auto order")
        self._order_status = QLabel("")
        self._order_status.setWordWrap(True)
        self._instructions = QLabel(ROUND_TRIP_INSTRUCTIONS)
        self._instructions.setWordWrap(True)
        self._instructions.setStyleSheet(f"color: {NEUTRAL};")
        self._instructions.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)

        order_hdr = QLabel("<b>Custom reel order (CSV round-trip)</b>")
        order_row = QHBoxLayout()
        order_row.addWidget(self._order_export_btn)
        order_row.addWidget(self._order_import_btn)
        order_row.addWidget(self._order_revert_btn)
        order_row.addStretch(1)

        self._status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row1)
        layout.addLayout(row2)
        layout.addWidget(self._progress)
        layout.addWidget(self._status)
        layout.addWidget(order_hdr)
        layout.addLayout(order_row)
        layout.addWidget(self._order_status)
        layout.addWidget(self._instructions)

        self._mp3_btn.clicked.connect(self._on_mp3_clicked)
        self._dump_btn.clicked.connect(self._on_dump_clicked)
        self._catalog_btn.clicked.connect(self._on_catalog_clicked)
        self._order_export_btn.clicked.connect(self._on_order_export_clicked)
        self._order_import_btn.clicked.connect(self._on_import_clicked)
        self._order_revert_btn.clicked.connect(self.revert_order_requested)

        self._update()

    # --- state the Library/shell drive -------------------------------------

    def set_context(self, game: str, workspace: str, checked_count: int,
                    can_mp3: bool, can_catalog: bool,
                    order_active: bool = False, order_count: int = 0) -> None:
        """The per-game/per-refresh facts: which game, how many rows are checked, and whether
        the render-input (Export MP3) and catalog artifacts exist. Also swaps the DS-only
        bitrate combo for the fixed "128k" label on HZD/FW (spec §8.2)."""
        self._game = game
        self._workspace = workspace
        self._checked = checked_count
        self._can_mp3 = can_mp3
        self._can_catalog = can_catalog
        self._order_active = order_active
        self._order_count = order_count
        is_ds = game == "ds"
        self._bitrate.setVisible(is_ds)
        self._bitrate_label.setVisible(not is_ds)
        self._update()

    def set_running(self, running: bool) -> None:
        """Mutual exclusion with any in-flight job (pipeline scan/bind, export render, or a
        dump): disables starting new exports while one runs (mirrors PipelineControls)."""
        self._running = running
        self._update()

    def set_dumping(self, dumping: bool) -> None:
        """This panel's batch dump is the active job -> the Dump button becomes Cancel."""
        self._dumping = dumping
        self._update()

    def set_workspace_empty(self, empty: bool) -> None:
        """Mirrors PipelineControls.set_workspace_empty: when no workspace is set the
        export actions are disabled (consistent with the pipeline gate from #246)."""
        self._workspace_empty = empty
        self._update()

    def set_dump_progress(self, done: int, total: int) -> None:
        self._progress.setVisible(True)
        self._progress.setMaximum(max(total, 1))
        self._progress.setValue(done)
        self._status.setText(f"Dumping {done}/{total}…")

    def dump_finished(self, ok: int, failed: int) -> None:
        self._progress.setVisible(False)
        self._progress.setValue(0)
        self._status.setText(f"Dumped {ok} clip(s)" + (f", {failed} failed" if failed else ""))

    def _update(self) -> None:
        has_workspace = not self._workspace_empty
        can_start = self._checked > 0 and not self._running and has_workspace
        self._mp3_btn.setEnabled(self._can_mp3 and can_start)
        self._catalog_btn.setEnabled(self._can_catalog and can_start)
        if self._dumping:
            self._dump_btn.setText("Cancel Dump")
            self._dump_btn.setEnabled(True)
        else:
            self._dump_btn.setText("Dump WAV (selected)")
            self._dump_btn.setEnabled(can_start)
        artifact = self._can_mp3
        self._order_export_btn.setEnabled(artifact and can_start)
        self._order_import_btn.setEnabled(artifact and not self._running and has_workspace)
        self._order_revert_btn.setEnabled(
            self._order_active and not self._running and has_workspace)
        if self._order_active:
            self._order_status.setText(
                f"\u25b6 Showing your imported order ({self._order_count:,} lines). "
                "Reels will render in this order.")
        else:
            self._order_status.setText("Order: automatic (story order).")

    # --- intents (dialogs opened here; the shell does the work) -------------

    def _on_mp3_clicked(self) -> None:
        self.export_mp3_requested.emit(self.bitrate())

    def _on_dump_clicked(self) -> None:
        if self._dumping:
            self.dump_cancel_requested.emit()
            return
        folder = QFileDialog.getExistingDirectory(self, "Dump selected WAVs to folder",
                                                  self._workspace)
        if folder:
            self.dump_wav_requested.emit(folder)

    def _on_catalog_clicked(self) -> None:
        default = os.path.join(self._workspace, f"{self._game or 'catalog'}-catalog.csv")
        path, _filter = QFileDialog.getSaveFileName(self, "Export catalog CSV", default,
                                                    "CSV files (*.csv)")
        if path:
            self.export_catalog_requested.emit(path)

    def _on_order_export_clicked(self) -> None:
        default = os.path.join(self._workspace, f"{self._game or 'order'}-order.csv")
        path, _f = QFileDialog.getSaveFileName(self, "Export order CSV", default,
                                               "CSV files (*.csv)")
        if path:
            self.export_order_requested.emit(path)

    def _on_import_clicked(self) -> None:
        path, _f = QFileDialog.getOpenFileName(self, "Import order CSV", self._workspace,
                                               "CSV files (*.csv);;All files (*.*)")
        if path:
            self.import_order_requested.emit(path)

    # --- accessors (test + shell) ------------------------------------------

    def bitrate(self) -> int:
        """The selected MP3 bitrate -- the combo value for DS, else the fixed 128k default."""
        if self._game == "ds":
            return int(self._bitrate.currentText())
        return _DEFAULT_BITRATE

    def bitrate_visible(self) -> bool:
        return self._bitrate.isVisibleTo(self)

    def mp3_enabled(self) -> bool:
        return self._mp3_btn.isEnabled()

    def dump_enabled(self) -> bool:
        return self._dump_btn.isEnabled()

    def catalog_enabled(self) -> bool:
        return self._catalog_btn.isEnabled()

    def status_text(self) -> str:
        return self._status.text()

    def export_order_enabled(self) -> bool:
        return self._order_export_btn.isEnabled()

    def import_enabled(self) -> bool:
        return self._order_import_btn.isEnabled()

    def revert_enabled(self) -> bool:
        return self._order_revert_btn.isEnabled()

    def order_status_text(self) -> str:
        return self._order_status.text()


# --- batch Dump-WAV worker (off the UI thread) -----------------------------

def _safe_name(line_id: str, used: set[str] | None = None) -> str:
    """A filesystem-safe basename for a line_id (ids can carry ``/`` or other path-hostile
    characters); non ``[A-Za-z0-9._-]`` chars become ``_``. When *used* is given, a name that
    collides with an existing entry is disambiguated with a ``_N`` suffix."""
    name = "".join(c if (c.isalnum() or c in "._-") else "_" for c in line_id) or "clip"
    if used is not None:
        base = name
        i = 1
        while name in used:
            name = f"{base}_{i}"
            i += 1
    return name


class _DumpSignals(QObject):
    """A ``QRunnable`` can't own signals, so the worker emits through this main-thread holder
    (the same pattern as :class:`gui.preview._WorkerSignals`)."""

    progress = Signal(int, int)      # done, total
    row_failed = Signal(str, str)    # line_id, message
    finished = Signal(int, int)      # ok, failed


class _DumpWorker(QRunnable):
    """Decode+copy each checked row's WAV to ``<dest>/<line_id>.wav`` on a pool thread, one at
    a time, reusing a single :class:`PreviewResolver` (its cached PackIndex/HzdPackage make the
    batch fast). Fail-soft: a per-row :class:`PreviewError` (and any unexpected error) is
    caught, counted, and reported -- the batch continues. Cancellable via a thread-safe flag."""

    def __init__(self, resolver, rows, dest, signals):
        super().__init__()
        self._resolver = resolver
        self._rows = rows           # list[(line_id, audio_path)]
        self._dest = dest
        self._signals = signals
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        ok = failed = 0
        total = len(self._rows)
        os.makedirs(self._dest, exist_ok=True)
        used_names: set[str] = set()
        for i, (line_id, audio_path) in enumerate(self._rows):
            if self._cancelled:
                break
            try:
                wav = self._resolver.resolve_wav(line_id, audio_path)
                safe = _safe_name(line_id, used_names)
                used_names.add(safe)
                dst = os.path.join(self._dest, f"{safe}.wav")
                if os.path.abspath(wav) != os.path.abspath(dst):
                    shutil.copyfile(wav, dst)
                ok += 1
            except PreviewError as exc:
                failed += 1
                self._signals.row_failed.emit(line_id, str(exc))
            except Exception as exc:  # backstop: an unexpected error must not kill the pool
                failed += 1
                self._signals.row_failed.emit(line_id, f"Dump failed: {exc}")
            self._signals.progress.emit(i + 1, total)
        self._signals.finished.emit(ok, failed)


class DumpRunner(QObject):
    """Runs at most one batch dump at a time on a ``QThreadPool``, re-exposing the worker's
    signals and flipping ``is_running`` around the batch (so the shell can mutually-exclude it
    with pipeline/export jobs -- one job at a time, spec §5.3). Mirrors the wrapper role
    :class:`gui.preview.PreviewPlayer` plays over its resolve worker."""

    progress = Signal(int, int)
    row_failed = Signal(str, str)
    finished = Signal(int, int)

    def __init__(self, parent=None, pool=None):
        super().__init__(parent)
        self._pool = pool if pool is not None else QThreadPool.globalInstance()
        self._signals = _DumpSignals()
        self._signals.progress.connect(self.progress)
        self._signals.row_failed.connect(self.row_failed)
        self._signals.finished.connect(self._on_finished)
        self._worker: _DumpWorker | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, resolver, rows, dest: str) -> bool:
        """Start a batch dump; returns False (does nothing) if one is already running."""
        if self._running:
            return False
        self._running = True
        self._worker = _DumpWorker(resolver, list(rows), dest, self._signals)
        self._pool.start(self._worker)
        return True

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    @Slot(int, int)
    def _on_finished(self, ok: int, failed: int) -> None:
        self._running = False
        self._worker = None
        self.finished.emit(ok, failed)


# --- async Catalog-copy worker (off the UI thread) -------------------------

class _CatalogCopySignals(QObject):
    """Signal holder for the catalog-copy worker. Mirrors :class:`_DumpSignals`."""
    finished = Signal(str)


class _CatalogCopyWorker(QRunnable):
    """Copy an artifact CSV to *dest* on a pool thread and emit the result
    message via :class:`_CatalogCopySignals.finished`. No QWidget access in ``run()`` —
    the result is marshalled back to the main thread by Qt's signal queuing.
    *kind* picks the source resolver: ``"catalog"`` uses :func:`catalog_source_path`,
    ``"order"`` uses :func:`render_input_source` (the current effective render-input,
    override-aware)."""

    def __init__(self, game: str, workspace: str, dest: str, signals: _CatalogCopySignals,
                 kind: str = "catalog"):
        super().__init__()
        self._game = game
        self._workspace = workspace
        self._dest = dest
        self._signals = signals
        self._kind = kind

    @Slot()
    def run(self) -> None:
        src = (render_input_source if self._kind == "order"
               else catalog_source_path)(self._workspace, self._game)
        noun = "order CSV" if self._kind == "order" else "catalog"
        if src is None:
            self._signals.finished.emit(
                f"export: no {noun} artifact yet for this game.\n")
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._dest)), exist_ok=True)
            shutil.copyfile(src, self._dest)
            self._signals.finished.emit(
                f"export: {noun} copied to {self._dest}\n")
        except OSError as exc:
            self._signals.finished.emit(
                f"export: could not write {noun}: {exc}\n")
