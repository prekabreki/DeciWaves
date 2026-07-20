"""The one-window, two-view shell (issue #67, spec §2), with the pipeline wired (#69).

Global bar on top, a Pipeline/Library switcher, and one JobRunner app-wide (spec §5.3).
The install-status line reuses the CLI's own doctor check functions. The Pipeline view's
Scan/Bind/Re-run/Transcribe-all controls emit intent signals; this shell turns them into
``deciwaves <game> run …`` jobs on the single runner, attaching the pre-bind CUDA probe
(#68's gpu_gate) to every GPU action, and refreshes the strip/coverage/issues around runs.

Orchestration (mutual exclusion, GPU gate, job lifecycle) is delegated to
:class:`~deciwaves.gui.job_controller.JobController` (#146)."""
from __future__ import annotations

import os
import shutil

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMainWindow, QMessageBox, QStackedWidget, QTabBar, QVBoxLayout, QWidget

from deciwaves.cli import config, doctor
from deciwaves.gui.cli_command import default_base
from deciwaves.gui.export_model import catalog_source_path
from deciwaves.gui.global_bar import GlobalBar
from deciwaves.gui.gpu_gate import confirm_gpu
from deciwaves.gui.job_controller import JobController
from deciwaves.gui.pipeline_model import _marker_path, stage_states
from deciwaves.gui.preview import PreviewPlayer
from deciwaves.gui.preview_model import PreviewResolver
from deciwaves.gui.views import GamePanel, LibraryView, PipelineView

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
        self.game_panel = GamePanel()
        self.pipeline = PipelineView()
        self.library = LibraryView()

        self.views = QStackedWidget()
        self.views.addWidget(self.pipeline)
        self.views.addWidget(self.library)

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

        self._controller = JobController(self)
        self._controller.log_message.connect(self.pipeline.append_log)
        self._controller.chip_text.connect(self.bar.set_job_chip)
        self._controller.busy_changed.connect(self._on_busy_changed)
        self._controller.dump_progress.connect(
            lambda done, total: self.library.export.set_dump_progress(done, total))
        self._controller.dump_batch_finished.connect(
            lambda ok, failed: self.library.export.dump_finished(ok, failed))

        self._controller._confirm_gpu = lambda game: confirm_gpu(
            self, game, self.pipeline.setup_doctor.doctor.last_payload())
        self._controller._confirm_escalate = lambda: self._confirm_escalate()
        self._controller._confirm_rerun = lambda stage: self._confirm_rerun(stage)

        self.player = PreviewPlayer(self)
        self._resolver: PreviewResolver | None = None
        self._resolver_key: tuple[str, str, float | None] | None = None
        self.library.preview_requested.connect(self._on_preview_requested)
        self.player.preview_failed.connect(lambda msg: self.pipeline.append_log(f"preview: {msg}\n"))

        # poll markers/coverage while a job runs so the strip advances live (spec §5.3)
        self._poll = QTimer(self)
        self._poll.setInterval(1500)
        self._poll.timeout.connect(self._refresh_panels)

        # pipeline controls -> controller methods
        self.pipeline.controls.scan_requested.connect(self._on_scan)
        self.pipeline.controls.process_requested.connect(self._on_process)
        self.pipeline.strip.rerun_requested.connect(self._on_rerun)
        self.pipeline.coverage.escalate_requested.connect(self._on_escalate)

        # export panel -> controller methods
        self.library.export.export_mp3_requested.connect(self._on_export_mp3)
        self.library.export.dump_wav_requested.connect(self._on_dump_wav)
        self.library.export.export_catalog_requested.connect(self._on_export_catalog)
        self.library.export.dump_cancel_requested.connect(self._controller.dump_cancel)

        self.game_panel.set_game(self.bar.current_game())
        self.bar.game_changed.connect(self.game_panel.set_game)
        self.bar.game_changed.connect(lambda _g: self._refresh_game_panel())
        self.game_panel.transcript_order_requested.connect(self._on_transcript_order)
        self.game_panel.gamescript_picked.connect(
            lambda p: self.pipeline.setup_doctor.setup.run(fw_gamescript=p, skip_downloads=True))
        self.game_panel.types_picked.connect(
            lambda p: self.pipeline.setup_doctor.setup.run(fw_types=p, skip_downloads=True))
        self.pipeline.setup_doctor.doctor.refreshed.connect(self._refresh_game_panel)

        self.bar.game_changed.connect(lambda _g: self._refresh_status())
        self.bar.game_changed.connect(self.pipeline.setup_doctor.set_game)
        self.bar.game_changed.connect(lambda _g: self._refresh_panels())
        self.bar.game_changed.connect(lambda _g: self._refresh_library())

        self.bar.workspace_changed.connect(lambda _ws: self._refresh_status())
        self.bar.workspace_changed.connect(lambda _ws: self._refresh_panels())
        self.bar.workspace_changed.connect(lambda _ws: self._refresh_library())
        self.bar.workspace_changed.connect(lambda _ws: self._refresh_game_panel())
        self.bar.workspace_changed.connect(lambda _ws: setattr(self, '_resolver', None))

        self.bar.select_game("ds")
        self._refresh_status()
        self._refresh_panels()
        self._refresh_library()
        self._refresh_game_panel()

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
                return st.name
        return None

    def _refresh_panels(self) -> None:
        game = self.bar.current_game()
        running = None
        if self._controller.runner.is_running and self._controller.job_game == game:
            running = self._active_stage(game)
        self.pipeline.refresh_panels(game, self._workspace(), running)

    def _refresh_library(self) -> None:
        self.library.refresh(self.bar.current_game(), self._workspace())

    def _refresh_game_panel(self) -> None:
        self.game_panel.set_context(
            self._workspace(), config.load(),
            self.pipeline.setup_doctor.doctor.last_payload())

    def _on_tab_changed(self, index: int) -> None:
        self.views.setCurrentIndex(index)
        if index == 1:
            self._refresh_library()

    # --- inline preview (#71) ----------------------------------------------

    def _preview_resolver(self) -> PreviewResolver:
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

    # --- job orchestration bridge (#146) -----------------------------------

    def _confirm_escalate(self) -> bool:
        resp = QMessageBox.warning(
            self, "Transcribe all",
            "This re-transcribes every line uncapped — hours. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return resp == QMessageBox.Yes

    def _confirm_rerun(self, stage: str) -> bool:
        resp = QMessageBox.warning(
            self, "Re-run from here",
            f"Re-running from \"{stage}\" will discard completed stages after "
            f"this point. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return resp == QMessageBox.Yes

    def _on_busy_changed(self) -> None:
        busy = self._controller.busy
        self.pipeline.controls.set_running(busy)
        self.pipeline.strip.set_running(busy)
        self.library.export.set_running(busy)
        self.library.export.set_dumping(self._controller.dumping)
        if self._controller.runner.is_running:
            self._poll.start()
        else:
            self._poll.stop()
            self._refresh_panels()
            self._refresh_library()
            self._refresh_game_panel()

    def _on_scan(self) -> None:
        self._controller.scan(default_base(), self.bar.current_game(), self._workspace())

    def _on_process(self) -> None:
        self._controller.process(default_base(), self.bar.current_game(), self._workspace(),
                                 sample_cap=self.game_panel.sample_cap())

    def _on_rerun(self, stage: str) -> None:
        self._controller.rerun(default_base(), self.bar.current_game(), self._workspace(), stage)

    def _on_escalate(self) -> None:
        self._controller.escalate(default_base(), self.bar.current_game(), self._workspace())

    def _on_transcript_order(self, path: str) -> None:
        if self.bar.current_game() != "ds":
            return
        self._controller.transcript_order(default_base(), self._workspace(), path)

    def _on_export_mp3(self, bitrate: int) -> None:
        self._controller.export_mp3(
            default_base(), self.bar.current_game(), self._workspace(),
            self.library.unchecked_ids(), bitrate, config.load(),
            self.game_panel.render_scope())

    def _on_dump_wav(self, dest: str) -> None:
        rows = [(r.line_id, r.audio_path) for r in self.library.checked_rows()]
        if not rows:
            self.pipeline.append_log("dump: no checked rows to dump.\n")
            return
        self._controller.dump_wav(self._preview_resolver(), rows, dest)

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
