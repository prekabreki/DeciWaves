"""One-pipeline-job-at-a-time subprocess runner (issue #67, spec §5.3).

Wraps ``QProcess`` so the child runs asynchronously off the UI thread (the Qt event
loop drives it -- the UI never blocks on an hours-long bind). Streams merged
stdout/stderr as ``output``; ``cancel()`` terminates then kills, which is safe +
resumable per the CLI's atomic-write / resume-sidecar contract."""
from __future__ import annotations

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

_KILL_GRACE_MS = 2000  # after terminate(), force-kill if still alive (Windows consoles
# ignore the WM_CLOSE that terminate() sends, so the kill is what actually stops them)


class JobRunner(QObject):
    """Runs at most one pipeline subprocess at a time, app-wide."""

    started = Signal()
    output = Signal(str)
    finished = Signal(int)  # process exit code

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: QProcess | None = None

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.NotRunning

    def start(self, argv: list[str], cwd: str | None = None) -> bool:
        """Start ``argv`` as the single global job. Returns False (and does nothing) if a
        job is already running -- one GPU, one job (spec §5.3)."""
        if self.is_running:
            return False
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.MergedChannels)  # stderr -> stdout, one stream
        if cwd:
            p.setWorkingDirectory(cwd)
        p.readyReadStandardOutput.connect(self._drain)
        p.finished.connect(self._on_finished)
        self._proc = p
        p.start(argv[0], argv[1:])
        self.started.emit()
        return True

    def cancel(self) -> None:
        """Terminate the running job (then force-kill after a short grace). Safe: the
        CLI resumes from where it stopped."""
        p = self._proc
        if p is None or p.state() == QProcess.NotRunning:
            return
        p.terminate()
        QTimer.singleShot(_KILL_GRACE_MS,
                          lambda: p.kill() if p.state() != QProcess.NotRunning else None)

    def _drain(self) -> None:
        if self._proc is None:
            return
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        if data:
            self.output.emit(data)

    def _on_finished(self, code: int, _status) -> None:
        self._drain()          # flush any trailing output before signaling done
        self._proc = None
        self.finished.emit(int(code))
