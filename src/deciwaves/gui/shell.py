"""The one-window, two-view shell (issue #67, spec §2), with the pipeline wired (#69).

Global bar on top, a Pipeline/Library switcher, and one JobController app-wide (spec §5.3).
The install-status line reuses the CLI's own doctor check functions. The Pipeline view's
Scan/Bind/Re-run/Transcribe-all controls emit intent signals; this shell turns them into
``deciwaves <game> run …`` jobs on the single runner, attaching the pre-bind CUDA probe
(#68's gpu_gate) to every GPU action, and refreshes the strip/coverage/issues around runs."""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QTabBar, QVBoxLayout, QWidget

from deciwaves.cli import config, doctor
from deciwaves.gui.global_bar import GlobalBar
from deciwaves.gui.job_controller import JobController
from deciwaves.gui.pipeline_model import _marker_path, stage_states
from deciwaves.gui.preview import PreviewPlayer
from deciwaves.gui.progress_model import probe_progress
from deciwaves.gui.preview_model import PreviewResolver
from deciwaves.gui.views import GamePanel, LibraryView, PipelineView

# game key -> its doctor install/config check (reused from the CLI, issue #67 / spec §3).
_CHECKS = {
    "ds": lambda cfg: doctor.check_ds_install(cfg.get("ds_install", "")),
    "hzd": lambda cfg: doctor.check_hzd_package(cfg.get("hzd_package", "")),
    "fw": lambda cfg: doctor.check_fw_package(cfg.get("fw_package", "")),
}


class MainWindow(QMainWindow):
    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self._settings = settings if settings is not None else QSettings("DeciWaves", "gui")
        self.setWindowTitle("DeciWaves")
        self.setMinimumSize(900, 600)

        self.bar = GlobalBar()
        # The adaptive per-game panel (#73, spec §7): one frame between the global bar and the
        # tab stack, hosting DS/HZD/FW-specific controls. It swaps (hides/shows controls) on
        # game change; both views see it.
        self.game_panel = GamePanel()
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
        layout.addWidget(self.game_panel)
        layout.addWidget(self._tabs)
        layout.addWidget(self.views, 1)
        self.setCentralWidget(central)

        # exactly one pipeline job app-wide (spec §5.3)
        self._controller = JobController(self)
        self._controller.runner.output.connect(self.pipeline.append_log)
        self._controller.log_message.connect(self.pipeline.append_log)
        self._controller.job_chip_changed.connect(self.bar.set_job_chip)
        self._controller.busy_changed.connect(self._on_busy_changed)
        self._controller.runner.started.connect(self._on_poll_start)
        self._controller.runner.finished.connect(self._on_pipe_job_finished)
        self._controller.dump.progress.connect(self._on_dump_progress)
        self._controller.dump.finished.connect(self._on_dump_widget_finished)
        self._controller.dump_status.connect(self.library.export.dump_finished)
        self.library.export.export_mp3_requested.connect(self._on_export_mp3)
        self.library.export.dump_wav_requested.connect(self._on_dump_wav)
        self.library.export.export_catalog_requested.connect(self._on_export_catalog)
        self.library.export.dump_cancel_requested.connect(self._controller.dump.cancel)

        # inline audio preview (#71, spec §6.5): the Library's ▷ / enter emits
        # preview_requested(line_id); play it through one app-wide player, off the UI thread.
        self.player = PreviewPlayer(self)
        self._resolver: PreviewResolver | None = None
        self._resolver_key: tuple[str, str, float | None] | None = None
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
        self.pipeline.controls.cancel_requested.connect(self._controller.runner.cancel)
        self.pipeline.strip.rerun_requested.connect(self._on_rerun)
        self.pipeline.coverage.escalate_requested.connect(self._on_escalate)

        # the adaptive per-game panel (#73): swap controls on game change, then refresh its
        # types.json/GPU context; its intents drive standalone re-order + BYO-path persistence.
        self.game_panel.set_game(self.bar.current_game())
        self.bar.game_changed.connect(self.game_panel.set_game)
        self.bar.game_changed.connect(lambda _g: self._refresh_game_panel())
        self.game_panel.transcript_order_requested.connect(self._on_transcript_order)
        # BYO FW pickers persist through the setup path (merge/absolutize/clear + re-doctor),
        # NOT a direct config.save. skip_downloads=True: persist the path + re-check only, so
        # picking a file never triggers a surprise ~200 MB tool fetch (spec §7 / issue #103).
        self.game_panel.gamescript_picked.connect(
            lambda p: self.pipeline.setup_doctor.setup.run(fw_gamescript=p, skip_downloads=True))
        self.game_panel.types_picked.connect(
            lambda p: self.pipeline.setup_doctor.setup.run(fw_types=p, skip_downloads=True))
        # a finished doctor run (incl. the one setup triggers) re-grades the panel's types.json
        # + GPU/CUDA readiness from the fresh payload.
        self.pipeline.setup_doctor.doctor.refreshed.connect(self._refresh_game_panel)

        self.bar.game_changed.connect(lambda _g: self._refresh_status())
        # re-grade the Doctor panel's promoted GPU items for the selected game (spec §3)
        self.bar.game_changed.connect(self.pipeline.setup_doctor.set_game)
        self.bar.game_changed.connect(lambda _g: self._refresh_panels())
        # reload the Library's line list for the selected game (#70, spec §6)
        self.bar.game_changed.connect(lambda _g: self._refresh_library())

        self.bar.workspace_changed.connect(lambda _ws: self._refresh_status())
        self.bar.workspace_changed.connect(lambda _ws: self._refresh_panels())
        self.bar.workspace_changed.connect(lambda _ws: self._refresh_library())
        self.bar.workspace_changed.connect(lambda _ws: self._refresh_game_panel())
        self.bar.workspace_changed.connect(lambda _ws: setattr(self, '_resolver', None))

        # --- restore persisted session state ---------------------------------
        geo = self._settings.value("window/geometry")
        if geo is not None:
            self.restoreGeometry(geo)

        state = self._settings.value("window/state")
        if state is not None:
            self.restoreState(state)

        ws = self._settings.value("workspace")
        if ws is not None and ws:
            self.bar.set_workspace(ws)

        game = self._settings.value("game")
        if game in ("ds", "hzd", "fw"):
            self.bar.select_game(game)
            if game == "ds":
                # select_game("ds") leaves the combo on its existing index 0,
                # so game_changed does not fire -- prime explicitly.
                self._refresh_status()
                self._refresh_panels()
                self._refresh_library()
                self._refresh_game_panel()
        else:
            self.bar.select_game("ds")
            self._refresh_status()
            self._refresh_panels()
            self._refresh_library()
            self._refresh_game_panel()

        saved_header = self._settings.value("library/header_state")
        if saved_header is not None:
            QTimer.singleShot(0, lambda h=saved_header: (
                self.library._table.horizontalHeader().restoreState(h)))

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
        if self._controller.runner.is_running and self._controller._job_game == game:
            running = self._active_stage(game)
        progress = probe_progress(self._workspace(), game, running) if running else None
        self.pipeline.refresh_panels(game, self._workspace(), running, progress=progress)

    def _refresh_library(self) -> None:
        """Reload the Library's line list (#70). Cheap enough for game-change / tab-switch /
        job-finished; deliberately NOT on the mid-job poll, so it never resets mid-scroll."""
        self.library.refresh(self.bar.current_game(), self._workspace())

    def _refresh_game_panel(self) -> None:
        """Refresh the per-game panel's context (#73): the FW types.json grade + the GPU/CUDA
        readiness label, from the current workspace/config and the last doctor payload."""
        self.game_panel.set_context(
            self._workspace(), config.load(),
            self.pipeline.setup_doctor.doctor.last_payload())

    def _on_tab_changed(self, index: int) -> None:
        self.views.setCurrentIndex(index)
        if index == 1:   # Library -- pick up rows written since it was last shown
            self._refresh_library()

    # --- inline preview (#71) ----------------------------------------------

    def _preview_resolver(self) -> PreviewResolver:
        """The resolver for the current (game, workspace), rebuilt only when either changes or
        when the bind stage re-runs (``out/<game>/.done-bind`` mtime bumps) -- a rebuild drops
        the prior game's stale manifests/heavy handles, while repeated previews of the same
        game reuse its cached PackIndex/HzdPackage."""
        game = self.bar.current_game()
        workspace = self._workspace()
        marker = _marker_path(workspace, game, "bind")
        try:
            bind_mtime = os.path.getmtime(marker)
        except OSError:
            bind_mtime = None
        key = (game, workspace, bind_mtime)
        if self._resolver is None or self._resolver_key != key:
            self._resolver = PreviewResolver(game, workspace)
            self._resolver_key = key
        return self._resolver

    def _on_preview_requested(self, line_id: str) -> None:
        audio_path = self.library.audio_path_for(line_id)
        self.player.play_line(self._preview_resolver(), line_id, audio_path)

    # --- job control -------------------------------------------------------

    # Thin delegating properties for backward-compat (tests reach these directly)
    @property
    def runner(self):
        return self._controller.runner

    @property
    def dump(self):
        return self._controller.dump

    @property
    def _job_kind(self) -> str | None:
        return self._controller._job_kind

    @_job_kind.setter
    def _job_kind(self, value: str | None) -> None:
        self._controller._job_kind = value

    @property
    def _job_game(self) -> str | None:
        return self._controller._job_game

    @_job_game.setter
    def _job_game(self, value: str | None) -> None:
        self._controller._job_game = value

    # -- pipeline dispatch (delegates to the controller) ---------------------

    def _on_scan(self) -> None:
        self._controller.start_scan(self.bar.current_game(), self._workspace())

    def _on_process(self) -> None:
        self._controller.start_process(
            self.bar.current_game(), self._workspace(),
            self.game_panel.sample_cap(),
            self.pipeline.setup_doctor.doctor.last_payload())

    def _on_transcript_order(self, path: str) -> None:
        ok = self._controller.start_transcript_order(
            self.bar.current_game(), self._workspace(), path)
        if not ok:
            self.pipeline.append_log("re-order: a job is already running.\n")

    def _on_rerun(self, stage: str) -> None:
        self._controller.start_rerun(
            self.bar.current_game(), self._workspace(), stage,
            self.pipeline.setup_doctor.doctor.last_payload())

    def _on_escalate(self) -> None:
        self._controller.start_escalate(
            self.bar.current_game(), self._workspace(),
            self.pipeline.setup_doctor.doctor.last_payload())

    # -- UI callbacks from controller signals -------------------------------

    def _on_busy_changed(self, busy: bool) -> None:
        self.pipeline.controls.set_running(busy)
        self.pipeline.strip.set_running(busy)
        self.library.export.set_running(busy)
        self.library.export.set_dumping(self._controller.dump.is_running)

    def _on_poll_start(self) -> None:
        self._poll.start()

    def _on_pipe_job_finished(self, code: int) -> None:
        self._poll.stop()
        self._refresh_panels()
        self._refresh_library()
        self._refresh_game_panel()

    # -- delegate for tests that call _on_job_finished directly ---------------

    def _on_job_finished(self, code: int) -> None:
        self._controller._on_job_finished(code)
        self._on_pipe_job_finished(code)

    def _sync_running(self) -> None:
        self._controller._sync_running()
        self._on_busy_changed(self._controller.runner.is_running or self._controller.dump.is_running)

    def _report_export_result(self, game: str | None, code: int) -> None:
        msg = self._controller._report_export_result(game, code)
        self.pipeline.append_log(msg)

    # --- export flows (#72) ------------------------------------------------

    def _on_export_mp3(self, bitrate: int) -> None:
        error = self._controller.start_export_mp3(
            self.bar.current_game(), self._workspace(), bitrate,
            self.library.unchecked_ids(), self.game_panel.render_scope())
        if error:
            self.pipeline.append_log(error)

    def _on_dump_wav(self, dest: str) -> None:
        rows = [(r.line_id, r.audio_path) for r in self.library.checked_rows()]
        if not rows:
            self.pipeline.append_log("dump: no checked rows to dump.\n")
            return
        self.pipeline.append_log(f"dump: decoding {len(rows)} line(s) to {dest} …\n")
        game = self.bar.current_game()
        resolver = PreviewResolver(game, self._workspace())
        error = self._controller.start_dump_wav(game, self._workspace(), resolver, rows, dest)
        if error:
            self.pipeline.append_log(error)

    def _on_dump_progress(self, done: int, total: int) -> None:
        self.library.export.set_dump_progress(done, total)

    def _on_dump_widget_finished(self, ok: int, failed: int) -> None:
        self.library.export.dump_finished(ok, failed)

    def _on_dump_finished(self, ok: int, failed: int) -> None:
        """Backward-compat delegate: tests call this directly."""
        self._controller._on_dump_finished(ok, failed)
        self.library.export.dump_finished(ok, failed)

    def _on_export_catalog(self, dest: str) -> None:
        error = self._controller.export_catalog(
            self.bar.current_game(), self._workspace(), dest)
        if error:
            self.pipeline.append_log(error)
        else:
            self.pipeline.append_log(f"export: catalog copied to {dest}\n")

    # --- session persistence ------------------------------------------------

    def closeEvent(self, event) -> None:
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/state", self.saveState())
        self._settings.setValue("workspace", self.bar.workspace())
        self._settings.setValue("game", self.bar.current_game())
        self._settings.setValue("library/header_state",
                                self.library._table.horizontalHeader().saveState())
        super().closeEvent(event)
