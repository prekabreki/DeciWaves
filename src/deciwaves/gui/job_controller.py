"""JobController: owns runners + GPU gate + dispatch/mutual-exclusion (#146).

Window-free, Qt-signal-based, testable headless. Extracted from MainWindow so the
orchestration layer can be unit-tested without building a window."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from deciwaves.gui.export import DumpRunner
from deciwaves.gui.export_model import (
    ExportError,
    render_selection_argv,
    write_render_selection,
)
from deciwaves.gui.game_panel_model import transcript_order_argv
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
    """Window-free controller for one-pipeline-job-at-a-time orchestration.

    Owns the :class:`JobRunner` (pipeline/export subprocess) and
    :class:`DumpRunner` (batch WAV decode), enforces mutual exclusion, runs
    the GPU gate via overridable confirm methods, and emits signals for the
    shell to wire into UI state. No QWidget parents -- testable headless."""

    log_message = Signal(str)
    busy_changed = Signal()
    chip_text = Signal(str)
    dump_progress = Signal(int, int)
    dump_row_failed = Signal(str, str)
    dump_batch_finished = Signal(int, int)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.runner = JobRunner(self)
        self.dump = DumpRunner(self)
        self._job_game: str | None = None
        self._job_kind: str | None = None

        self.runner.output.connect(self.log_message)
        self.runner.started.connect(self._on_job_started)
        self.runner.finished.connect(self._on_job_finished)
        self.dump.progress.connect(self.dump_progress)
        self.dump.row_failed.connect(
            lambda lid, msg: self.log_message.emit(f"dump: {lid}: {msg}\n"))
        self.dump.finished.connect(self._on_dump_finished)

    # ------------------------------------------------------------------ properties

    @property
    def busy(self) -> bool:
        return self.runner.is_running or self.dump.is_running

    @property
    def dumping(self) -> bool:
        return self.dump.is_running

    @property
    def job_game(self) -> str | None:
        return self._job_game

    @property
    def job_kind(self) -> str | None:
        return self._job_kind

    # ------------------------------------------------------------------ confirm callbacks

    def _confirm_gpu(self, game: str) -> bool:
        """Override point for the shell's GPU gate dialog. Default: allow."""
        return True

    def _confirm_escalate(self) -> bool:
        """Override point for the shell's "Transcribe all" warning. Default: allow."""
        return True

    def _confirm_rerun(self, stage: str) -> bool:
        """Override point for the shell's re-run confirmation dialog. Default: allow."""
        return True

    # ------------------------------------------------------------------ pipeline starts

    def scan(self, base: list[str], game: str, workspace: str) -> bool:
        if self.busy:
            return False
        self._job_game = game
        self._job_kind = None
        return self.runner.start(scan_argv(base, workspace, game))

    def process(self, base: list[str], game: str, workspace: str,
                sample_cap: int | None = None) -> bool:
        if self.busy:
            return False
        if not self._confirm_gpu(game):
            return False
        self._job_game = game
        self._job_kind = None
        return self.runner.start(process_argv(base, workspace, game, sample_cap=sample_cap))

    def rerun(self, base: list[str], game: str, workspace: str, stage: str) -> bool:
        if self.busy:
            return False
        if _rerun_invalidates_completed(game, workspace, stage):
            if not self._confirm_rerun(stage):
                return False
        if rerun_hits_gpu(game, stage) and not self._confirm_gpu(game):
            return False
        self._job_game = game
        self._job_kind = None
        return self.runner.start(rerun_from_argv(base, workspace, game, stage))

    def escalate(self, base: list[str], game: str, workspace: str) -> bool:
        if self.busy:
            return False
        if not self._confirm_escalate():
            return False
        if not self._confirm_gpu(game):
            return False
        self._job_game = game
        self._job_kind = None
        return self.runner.start(escalate_bind_argv(base, workspace, game))

    def transcript_order(self, base: list[str], workspace: str, path: str) -> bool:
        if self.busy:
            self.log_message.emit("re-order: a job is already running.\n")
            return False
        self._job_game = "ds"
        self._job_kind = None
        argv = transcript_order_argv(base, workspace, path)
        if not self.runner.start(argv):
            self.log_message.emit("re-order: a job is already running.\n")
            self._job_game = None
            return False
        return True

    # ------------------------------------------------------------------ export flows

    def export_mp3(self, base: list[str], game: str, workspace: str,
                   unchecked_ids: set[str], bitrate: int, cfg: dict,
                   render_scope_kwargs: dict | None = None) -> bool:
        if self.busy:
            self.log_message.emit("export: a job is already running.\n")
            return False
        try:
            csv_path = write_render_selection(workspace, game, unchecked_ids)
            kwargs = render_scope_kwargs or {}
            argv = render_selection_argv(base, workspace, game, csv_path,
                                         bitrate=bitrate, cfg=cfg, **kwargs)
        except ExportError as exc:
            self.log_message.emit(f"export: {exc}\n")
            return False
        self._job_kind = "export"
        self._job_game = game
        if not self.runner.start(argv):
            self.log_message.emit("export: a job is already running.\n")
            self._job_kind = None
            self._job_game = None
            return False
        return True

    def dump_wav(self, resolver, rows: list[tuple[str, str]], dest: str) -> bool:
        if self.busy:
            self.log_message.emit("dump: a job is already running.\n")
            return False
        self.log_message.emit(f"dump: decoding {len(rows)} line(s) to {dest} …\n")
        self.dump.start(resolver, rows, dest)
        self.busy_changed.emit()
        return True

    def dump_cancel(self) -> None:
        self.dump.cancel()

    # ------------------------------------------------------------------ lifecycle

    def _on_job_started(self) -> None:
        self.chip_text.emit(f"{self._job_game} · running" if self._job_game else "running")
        self.busy_changed.emit()

    def _on_job_finished(self, code: int) -> None:
        kind, game = self._job_kind, self._job_game
        self._job_kind = None
        self._job_game = None
        if kind == "export":
            if code == 0:
                out = {"ds": "out/audio", "hzd": "out/hzd/audio",
                       "fw": "out/fw/reels"}.get(game or "", "out/")
                self.log_message.emit(
                    f"export: done — reels + tracklist sidecars written under {out}.\n")
            else:
                self.log_message.emit(
                    f"export: render failed (rc {code}) — see the log above "
                    f"(an empty selection with no renderable rows can also cause this).\n")
            self.chip_text.emit("idle")
        elif code == 0 or self.runner.was_cancelled:
            self.chip_text.emit("idle")
        else:
            self.chip_text.emit("failed")
            self.log_message.emit(
                f"pipeline job failed (rc {code}) — see the log above.\n")
        self.busy_changed.emit()

    def _on_dump_finished(self, ok: int, failed: int) -> None:
        self.log_message.emit(f"dump: done — {ok} ok, {failed} failed.\n")
        self.dump_batch_finished.emit(ok, failed)
        self.chip_text.emit("idle")
        self.busy_changed.emit()


def _rerun_invalidates_completed(game: str, workspace: str, stage: str) -> bool:
    states = stage_states(game, workspace)
    names = [s.name for s in states]
    if stage not in names:
        return False
    idx = names.index(stage)
    return any(states[i].done for i in range(idx + 1, len(states)))
