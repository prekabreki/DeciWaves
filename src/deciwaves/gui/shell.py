"""The one-window, two-view shell (issue #67, spec §2), with the pipeline wired (#69).

Global bar on top, a Pipeline/Library switcher, and one JobRunner app-wide (spec §5.3).
The install-status line reuses the CLI's own doctor check functions. The Pipeline view's
Scan/Bind/Re-run/Transcribe-all controls emit intent signals; this shell turns them into
`deciwaves <game> run …` jobs on the single runner, attaching the pre-bind CUDA probe
(#68's gpu_gate) to every GPU action, and refreshes the strip/coverage/issues around runs."""
from __future__ import annotations

import os
import shutil

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QTabBar, QVBoxLayout, QWidget

from deciwaves.cli import config, doctor
from deciwaves.gui.cli_command import default_base
from deciwaves.gui.export import DumpRunner
from deciwaves.gui.export_model import (
    ExportError,
    catalog_source_path,
    render_selection_argv,
    write_render_selection,
)
from deciwaves.gui.global_bar import GlobalBar
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
from deciwaves.gui.preview import PreviewPlayer
from deciwaves.gui.preview_model import PreviewResolver
from deciwaves.gui.views import LibraryView, PipelineView

# game key -> its doctor install/config check (reused from the CLI, issue #67 / spec §3).
_CHECKS = {
    "ds": lambda cfg: doctor.check_ds_install(cfg.get("ds_install", "")),
    "hzd": lambda cfg: doctor.check_hzd_package(cfg.get("hzd_package", "")),
    "fw": lambda cfg: doctor.check_fw_package(cfg.get("fw_package", "")),
}


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DeciWaves")

        self.bar = GlobalBar()
        self.pipeline = PipelineView()
        self.library = LibraryView()

        self.views = QStackedWidget()
        self.views.addWidget(self.pipeline)   # index 0
        self.views.addWidget(self.library)    # index 1

        self._tabs = QTabBar()
        self._tabs.addTab("Pipeline")
        self._tabs.addTab("Library")
        self._tabs.currentChanged.connect(self._on_tab_changed)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.bar)
        layout.addWidget(self._tabs)
        layout.addWidget(self.views, 1)
        self.setCentralWidget(central)

        # exactly one pipeline job app-wide (spec §5.3)
        self.runner = JobRunner(self)
        self._job_game: str | None = None
        self._job_kind: str | None = None  # "export" for a render job; None for pipeline jobs
        self.runner.output.connect(self.pipeline.append_log)
        self.runner.started.connect(self._on_job_started)
        self.runner.finished.connect(self._on_job_finished)

        # filtered export (#72, spec §8): the Library's Export panel emits three intents. Export
        # MP3 goes through the SAME single JobRunner (tracked via _job_kind so _on_job_finished
        # surfaces the render rc); Dump WAV runs as an off-thread batch on its own runner; the
        # catalog is a file copy. All three mutually-exclude with pipeline jobs (_sync_running).
        self.dump = DumpRunner(self)
        self.dump.progress.connect(self._on_dump_progress)
        self.dump.row_failed.connect(
            lambda lid, msg: self.pipeline.append_log(f"dump: {lid}: {msg}\n"))
        self.dump.finished.connect(self._on_dump_finished)
        self.library.export.export_mp3_requested.connect(self._on_export_mp3)
        self.library.export.dump_wav_requested.connect(self._on_dump_wav)
        self.library.export.export_catalog_requested.connect(self._on_export_catalog)
        self.library.export.dump_cancel_requested.connect(self.dump.cancel)

        # inline audio preview (#71, spec §6.5): the Library's ▷ / enter emits
        # preview_requested(line_id); play it through one app-wide player, off the UI thread.
        self.player = PreviewPlayer(self)
        self._resolver: PreviewResolver | None = None
        self._resolver_key: tuple[str, str] | None = None
        self.library.preview_requested.connect(self._on_preview_requested)
        # decode/config failures are surfaced in the same log console job output uses, so a
        # missing decoder or unconfigured install is visible rather than swallowed.
        self.player.preview_failed.connect(lambda msg: self.pipeline.append_log(f"preview: {msg}\n"))

        # poll markers/coverage while a job runs so the strip advances live (spec §5.3)
        self._poll = QTimer(self)
        self._poll.setInterval(1500)
        self._poll.timeout.connect(self._refresh_panels)

        # pipeline controls -> jobs on the single runner
        self.pipeline.controls.scan_requested.connect(self._on_scan)
        self.pipeline.controls.process_requested.connect(self._on_process)
        self.pipeline.strip.rerun_requested.connect(self._on_rerun)
        self.pipeline.coverage.escalate_requested.connect(self._on_escalate)

        self.bar.game_changed.connect(lambda _g: self._refresh_status())
        # re-grade the Doctor panel's promoted GPU items for the selected game (spec §3)
        self.bar.game_changed.connect(self.pipeline.setup_doctor.set_game)
        self.bar.game_changed.connect(lambda _g: self._refresh_panels())
        # reload the Library's line list for the selected game (#70, spec §6)
        self.bar.game_changed.connect(lambda _g: self._refresh_library())
        self.bar.select_game("ds")   # DS is the built-first vertical slice
        # select_game("ds") leaves the combo on its existing index 0, so game_changed does
        # not fire -- prime the status line and panels for the initial game explicitly.
        self._refresh_status()
        self._refresh_panels()
        self._refresh_library()

    # --- status + panels ---------------------------------------------------

    def _workspace(self) -> str:
        return self.bar.workspace() or "."

    def _refresh_status(self) -> None:
        cfg = config.load()
        check = _CHECKS[self.bar.current_game()](cfg)
        self.bar.set_install_status(check.detail, check.status is doctor.Availability.OK)

    def _active_stage(self, game: str) -> str | None:
        for st in stage_states(game, self._workspace()):
            if not st.done:
                return st.name   # first incomplete stage == the one currently running
        return None

    def _refresh_panels(self) -> None:
        game = self.bar.current_game()
        running = None
        if self.runner.is_running and self._job_game == game:
            running = self._active_stage(game)
        self.pipeline.refresh_panels(game, self._workspace(), running)

    def _refresh_library(self) -> None:
        """Reload the Library's line list (#70). Cheap enough for game-change / tab-switch /
        job-finished; deliberately NOT on the mid-job poll, so it never resets mid-scroll."""
        self.library.refresh(self.bar.current_game(), self._workspace())

    def _on_tab_changed(self, index: int) -> None:
        self.views.setCurrentIndex(index)
        if index == 1:   # Library -- pick up rows written since it was last shown
            self._refresh_library()

    # --- inline preview (#71) ----------------------------------------------

    def _preview_resolver(self) -> PreviewResolver:
        """The resolver for the current (game, workspace), rebuilt only when either changes --
        a rebuild drops the prior game's stale manifests/heavy handles, while repeated previews
        of the same game reuse its cached PackIndex/HzdPackage."""
        key = (self.bar.current_game(), self._workspace())
        if self._resolver is None or self._resolver_key != key:
            self._resolver = PreviewResolver(key[0], key[1])
            self._resolver_key = key
        return self._resolver

    def _on_preview_requested(self, line_id: str) -> None:
        audio_path = self.library.audio_path_for(line_id)
        self.player.play_line(self._preview_resolver(), line_id, audio_path)

    # --- job control -------------------------------------------------------

    def _confirm_gpu(self, game: str) -> bool:
        return confirm_gpu(self, game, self.pipeline.setup_doctor.doctor.last_payload())

    def _on_scan(self) -> None:
        game = self.bar.current_game()
        self._job_game = game
        self.runner.start(scan_argv(default_base(), self._workspace(), game))

    def _on_process(self) -> None:
        game = self.bar.current_game()
        if not self._confirm_gpu(game):
            return
        self._job_game = game
        self.runner.start(process_argv(default_base(), self._workspace(), game))

    def _on_rerun(self, stage: str) -> None:
        game = self.bar.current_game()
        if rerun_hits_gpu(game, stage) and not self._confirm_gpu(game):
            return
        self._job_game = game
        self.runner.start(rerun_from_argv(default_base(), self._workspace(), game, stage))

    def _on_escalate(self) -> None:
        game = self.bar.current_game()
        if not self._confirm_gpu(game):
            return
        self._job_game = game
        self.runner.start(escalate_bind_argv(default_base(), self._workspace(), game))

    def _on_job_started(self) -> None:
        self.bar.set_job_chip(f"{self.bar.current_game()} · running")
        self._sync_running()
        self._poll.start()

    def _on_job_finished(self, code: int) -> None:
        self.bar.set_job_chip("idle")
        self._poll.stop()
        kind, game = self._job_kind, self._job_game
        self._job_kind = None
        self._job_game = None
        # Export renders run through this same runner: surface the render rc as success/error
        # (this is where the empty-input / missing-decoder non-zero exits become a visible
        # error, never a silent green -- spec §8.2). Pipeline jobs keep the existing behavior.
        if kind == "export":
            self._report_export_result(game, code)
        self._sync_running()
        self._refresh_panels()
        self._refresh_library()   # surface catalog/asr-manifest rows written by Scan/Bind

    def _sync_running(self) -> None:
        """One job at a time (spec §5.3): a pipeline job, an export render, and a dump batch all
        mutually exclude. Disable the pipeline controls and the export panel whenever ANY is
        active; the export panel additionally shows a Cancel while its own dump runs."""
        running = self.runner.is_running or self.dump.is_running
        self.pipeline.controls.set_running(running)
        self.library.export.set_running(running)
        self.library.export.set_dumping(self.dump.is_running)

    def _report_export_result(self, game: str | None, code: int) -> None:
        if code == 0:
            out = {"ds": "out/audio", "hzd": "out/hzd/audio",
                   "fw": "out/fw/reels"}.get(game or "", "out/")
            self.pipeline.append_log(
                f"export: done — reels + tracklist sidecars written under {out}.\n")
        else:
            self.pipeline.append_log(
                f"export: render failed (rc {code}) — see the log above "
                f"(an empty selection with no renderable rows can also cause this).\n")

    # --- export flows (#72) ------------------------------------------------

    def _on_export_mp3(self, bitrate: int) -> None:
        game = self.bar.current_game()
        ws = self._workspace()
        try:
            csv_path = write_render_selection(ws, game, self.library.unchecked_ids())
            argv = render_selection_argv(default_base(), ws, game, csv_path,
                                         bitrate=bitrate, cfg=config.load())
        except ExportError as exc:
            self.pipeline.append_log(f"export: {exc}\n")
            return
        self._job_kind = "export"
        self._job_game = game
        if not self.runner.start(argv):
            self.pipeline.append_log("export: a job is already running.\n")
            self._job_kind = None
            self._job_game = None

    def _on_dump_wav(self, dest: str) -> None:
        if self.runner.is_running or self.dump.is_running:
            self.pipeline.append_log("dump: a job is already running.\n")
            return
        rows = [(r.line_id, r.audio_path) for r in self.library.checked_rows()]
        if not rows:
            self.pipeline.append_log("dump: no checked rows to dump.\n")
            return
        self.pipeline.append_log(f"dump: decoding {len(rows)} line(s) to {dest} …\n")
        self.dump.start(self._preview_resolver(), rows, dest)
        self._sync_running()

    def _on_dump_progress(self, done: int, total: int) -> None:
        self.library.export.set_dump_progress(done, total)

    def _on_dump_finished(self, ok: int, failed: int) -> None:
        self.pipeline.append_log(f"dump: done — {ok} ok, {failed} failed.\n")
        self.library.export.dump_finished(ok, failed)
        self._sync_running()

    def _on_export_catalog(self, dest: str) -> None:
        game = self.bar.current_game()
        src = catalog_source_path(self._workspace(), game)
        if src is None:
            self.pipeline.append_log("export: no catalog artifact yet for this game.\n")
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
            shutil.copyfile(src, dest)
        except OSError as exc:
            self.pipeline.append_log(f"export: could not write catalog: {exc}\n")
            return
        self.pipeline.append_log(f"export: catalog copied to {dest}\n")
