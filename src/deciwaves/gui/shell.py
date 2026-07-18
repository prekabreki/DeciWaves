"""The one-window, two-view shell (issue #67, spec §2).

Global bar on top, a Pipeline/Library switcher, and one JobRunner wired to the log
console + job chip. The install-status line reuses the same doctor check functions the
CLI and guided mode read, so "found / not configured / broken" stays one source of truth."""
from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QStackedWidget, QTabBar, QVBoxLayout, QWidget

from deciwaves.cli import config, doctor
from deciwaves.gui.global_bar import GlobalBar
from deciwaves.gui.jobs import JobRunner
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
        self.runner.output.connect(self.pipeline.append_log)
        self.runner.started.connect(self._on_job_started)
        self.runner.finished.connect(self._on_job_finished)

        self.bar.game_changed.connect(lambda _g: self._refresh_status())
        self.bar.select_game("ds")   # DS is the built-first vertical slice
        self._refresh_status()

    def _refresh_status(self) -> None:
        cfg = config.load()
        check = _CHECKS[self.bar.current_game()](cfg)
        self.bar.set_install_status(check.detail, check.status is doctor.Availability.OK)

    def _on_job_started(self) -> None:
        self.bar.set_job_chip(f"{self.bar.current_game()} · running")

    def _on_job_finished(self, _code: int) -> None:
        self.bar.set_job_chip("idle")
