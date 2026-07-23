"""Window-free pipeline + export job controller (issue #146).

Owns the single pipeline runner + dump runner + GPU gate + dispatch / mutual-exclusion
so orchestration can be unit-tested without constructing a MainWindow."""
from __future__ import annotations

from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtWidgets import QMessageBox

from deciwaves.cli import config
from deciwaves.gui.cli_command import default_base
from deciwaves.gui.export import DumpRunner, _CatalogCopySignals, _CatalogCopyWorker
from deciwaves.gui.export_model import (
    ExportError,
    render_selection_argv,
    write_render_selection_with_tiers,
)
from deciwaves.gui.game_panel_model import transcript_order_argv
from deciwaves.gui.gpu_gate import confirm_gpu
from deciwaves.gui.jobs import JobRunner
from deciwaves.gui.pipeline_model import (
    escalate_bind_argv,
    process_argv,
    rerun_from_argv,
    rerun_hits_gpu,
    scan_argv,
    stage_states,
)


class JobController(QObject):
    """Owns the one-pipeline-job app-wide runner + dump runner + GPS gate + mutual-exclusion.

    Window-free: unit-testable without constructing a MainWindow.  Confirm methods can be
    replaced for testing; the defaults pop up QMessageBox dialogs (parent=None), which still
    work headless but are safe to mock out.
    """

    log_message = Signal(str)
    job_chip_changed = Signal(str)
    busy_changed = Signal(bool)
    dump_progress = Signal(int, int)
    dump_status = Signal(int, int)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.runner = JobRunner(self)
        self.dump = DumpRunner(self)
        self._job_game: str | None = None
        self._job_kind: str | None = None

        self.runner.started.connect(self._on_job_started)
        self.runner.finished.connect(self._on_job_finished)

        self.dump.progress.connect(self.dump_progress)
        self.dump.row_failed.connect(
            lambda lid, msg: self.log_message.emit(f"dump: {lid}: {msg}\n"))
        self.dump.finished.connect(self._on_dump_finished)

    # -- pipeline dispatch ---------------------------------------------------

    def start_scan(self, game: str, workspace: str) -> None:
        if self.runner.is_running or self.dump.is_running:
            return
        self._job_game = game
        self.runner.start(scan_argv(default_base(), workspace, game))

    def start_process(self, game: str, workspace: str,
                      sample_cap: int | None, gpu_payload: dict | None) -> None:
        if self.runner.is_running or self.dump.is_running:
            return
        if not self._confirm_gpu(game, gpu_payload):
            return
        self._job_game = game
        self.runner.start(process_argv(default_base(), workspace, game,
                                        sample_cap=sample_cap))

    def start_transcript_order(self, game: str, workspace: str,
                               transcript_path: str) -> bool:
        if self.runner.is_running or self.dump.is_running:
            return False
        if game != "ds":
            return False
        self._job_game = game
        argv = transcript_order_argv(default_base(), workspace, transcript_path)
        if not self.runner.start(argv):
            self._job_game = None
            return False
        return True

    def start_rerun(self, game: str, workspace: str, stage: str,
                    gpu_payload: dict | None) -> None:
        if self.runner.is_running or self.dump.is_running:
            return
        if self._rerun_invalidates_completed(game, workspace, stage) and not self._confirm_rerun(stage):
            return
        if rerun_hits_gpu(game, stage) and not self._confirm_gpu(game, gpu_payload):
            return
        self._job_game = game
        self.runner.start(rerun_from_argv(default_base(), workspace, game, stage))

    def start_escalate(self, game: str, workspace: str,
                       gpu_payload: dict | None) -> None:
        if self.runner.is_running or self.dump.is_running:
            return
        if not self._confirm_escalate():
            return
        if not self._confirm_gpu(game, gpu_payload):
            return
        self._job_game = game
        self.runner.start(escalate_bind_argv(default_base(), workspace, game))

    # -- export dispatch (#72) -----------------------------------------------

    def start_export_mp3(self, game: str, workspace: str, bitrate: int,
                         unchecked_ids: list[str], checked_count: int = 0,
                         render_scope_kwargs: dict | None = None) -> str | None:
        if self.runner.is_running or self.dump.is_running:
            return "export: a job is already running.\n"
        if checked_count <= 0:
            return "export: nothing selected — check some rows first.\n"
        try:
            csv_path, fw_tiers = write_render_selection_with_tiers(
                workspace, game, unchecked_ids)
            scope = render_scope_kwargs or {}
            if game == "fw" and "tiers" not in scope:
                scope["tiers"] = fw_tiers
            argv = render_selection_argv(default_base(), workspace, game, csv_path,
                                          bitrate=bitrate, cfg=config.load(),
                                          **scope)
        except ExportError as exc:
            return f"export: {exc}\n"
        self._job_kind = "export"
        self._job_game = game
        if not self.runner.start(argv):
            self._job_kind = None
            self._job_game = None
            return "export: a job is already running.\n"
        return None

    def start_dump_wav(self, game: str, workspace: str,
                       resolver, rows, dest: str) -> str | None:
        if self.runner.is_running or self.dump.is_running:
            return "dump: a job is already running.\n"
        if not rows:
            return "dump: no checked rows to dump.\n"
        self.dump.start(resolver, rows, dest)
        self._sync_running()
        return None

    def start_catalog_copy(self, game: str, workspace: str, dest: str) -> None:
        signals = _CatalogCopySignals()
        signals.finished.connect(self._on_catalog_copy_finished)
        worker = _CatalogCopyWorker(game, workspace, dest, signals)
        self._catalog_signals = signals
        QThreadPool.globalInstance().start(worker)

    def start_order_copy(self, game: str, workspace: str, dest: str) -> None:
        signals = _CatalogCopySignals()
        signals.finished.connect(self._on_catalog_copy_finished)
        worker = _CatalogCopyWorker(game, workspace, dest, signals, kind="order")
        self._catalog_signals = signals
        QThreadPool.globalInstance().start(worker)

    def _on_catalog_copy_finished(self, msg: str) -> None:
        self.log_message.emit(msg)
        self._catalog_signals = None

    # -- job lifecycle -------------------------------------------------------

    def _on_job_started(self) -> None:
        self.job_chip_changed.emit("running")
        self._sync_running()

    def _on_job_finished(self, code: int) -> None:
        kind, game = self._job_kind, self._job_game
        self._job_kind = None
        self._job_game = None
        if kind == "export":
            msg = self._report_export_result(game, code)
            self.log_message.emit(msg)
            self.job_chip_changed.emit("idle")
        elif code == 0 or self.runner.was_cancelled:
            self.job_chip_changed.emit("idle")
        else:
            self.job_chip_changed.emit("failed")
            self.log_message.emit(
                f"pipeline job failed (rc {code}) — see the log above.\n")
        self._sync_running()

    def _sync_running(self) -> None:
        busy = self.runner.is_running or self.dump.is_running
        self.busy_changed.emit(busy)

    # -- confirm dialogs (replaceable for testing) ---------------------------

    def _confirm_gpu(self, game: str, payload: dict | None) -> bool:
        return confirm_gpu(None, game, payload)

    def _confirm_escalate(self) -> bool:
        resp = QMessageBox.warning(
            None, "Transcribe all",
            "This re-transcribes every line uncapped — hours. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return resp == QMessageBox.Yes

    def _confirm_rerun(self, stage: str) -> bool:
        resp = QMessageBox.warning(
            None, "Re-run from here",
            f"Re-running from \"{stage}\" will discard completed stages after "
            f"this point. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return resp == QMessageBox.Yes

    def _rerun_invalidates_completed(self, game: str, workspace: str,
                                     stage: str) -> bool:
        states = stage_states(game, workspace)
        names = [s.name for s in states]
        if stage not in names:
            return False
        idx = names.index(stage)
        return any(states[i].done for i in range(idx + 1, len(states)))

    # -- helpers -------------------------------------------------------------

    def _on_dump_finished(self, ok: int, failed: int) -> None:
        self.log_message.emit(f"dump: done — {ok} ok, {failed} failed.\n")
        self.dump_status.emit(ok, failed)
        self._sync_running()

    def _report_export_result(self, game: str | None, code: int) -> str:
        if code == 0:
            out = {"ds": "out/audio", "hzd": "out/hzd/audio",
                   "fw": "out/fw/reels"}.get(game or "", "out/")
            return (f"export: done — reels + tracklist sidecars written "
                    f"under {out}.\n")
        return (
            f"export: render failed (rc {code}) — see the log above "
            f"(an empty selection with no renderable rows can also cause this).\n"
        )
