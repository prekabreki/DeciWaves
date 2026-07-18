"""The one-window, two-view shell (issue #67, spec §2), with the pipeline wired (#69).

Global bar on top, a Pipeline/Library switcher, and one JobRunner app-wide (spec §5.3).
The install-status line reuses the CLI's own doctor check functions. The Pipeline view's
Scan/Bind/Re-run/Transcribe-all controls emit intent signals; this shell turns them into
`deciwaves <game> run …` jobs on the single runner, attaching the pre-bind CUDA probe
(#68's gpu_gate) to every GPU action, and refreshes the strip/coverage/issues around runs."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QTabBar, QVBoxLayout, QWidget

from deciwaves.cli import config, doctor
from deciwaves.gui.cli_command import default_base
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
        self._tabs.currentChanged.connect(self.views.setCurrentIndex)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.bar)
        layout.addWidget(self._tabs)
        layout.addWidget(self.views, 1)
        self.setCentralWidget(central)

        # exactly one pipeline job app-wide (spec §5.3)
        self.runner = JobRunner(self)
        self._job_game: str | None = None
        self.runner.output.connect(self.pipeline.append_log)
        self.runner.started.connect(self._on_job_started)
        self.runner.finished.connect(self._on_job_finished)

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
        self.bar.select_game("ds")   # DS is the built-first vertical slice
        # select_game("ds") leaves the combo on its existing index 0, so game_changed does
        # not fire -- prime the status line and panels for the initial game explicitly.
        self._refresh_status()
        self._refresh_panels()

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
        self.pipeline.controls.set_running(True)
        self._poll.start()

    def _on_job_finished(self, _code: int) -> None:
        self.bar.set_job_chip("idle")
        self.pipeline.controls.set_running(False)
        self._poll.stop()
        self._job_game = None
        self._refresh_panels()
