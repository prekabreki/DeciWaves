"""A QProcess wrapper that streams stdout live AND accumulates it, emitting the full text
with the exit code on ``finished`` (#68).

The pipeline's :class:`~deciwaves.gui.jobs.JobRunner` streams for a live console but throws
the bytes away; the Setup and Doctor screens need the *whole* output to parse (setup's
summary, ``doctor --json``'s JSON), so this adds accumulation. Same one-at-a-time and
terminate-then-kill semantics -- both are read-only/idempotent CLI reads, safe to cancel."""
from __future__ import annotations

from PySide6.QtCore import QObject, QProcess, Signal

from deciwaves.gui._env import utf8_environment
from deciwaves.gui._process import terminate_then_kill


class CaptureRunner(QObject):
    started = Signal()
    output = Signal(str)         # streamed chunk (for a live console)
    finished = Signal(int, str)  # exit code, full accumulated stdout+stderr

    def __init__(self, parent=None, *, merge_stderr: bool = True):
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._buf: list[str] = []
        # Setup wants stderr folded in for a complete live console; the Doctor panel wants
        # clean stdout so `doctor --json`'s JSON can't be corrupted by a child's import noise.
        self._merge_stderr = merge_stderr

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.NotRunning

    def start(self, argv: list[str], cwd: str | None = None) -> bool:
        """Start ``argv``. Returns False (doing nothing) if a run is already in flight."""
        if self.is_running:
            return False
        self._buf = []
        p = QProcess(self)
        p.setProcessChannelMode(
            QProcess.MergedChannels if self._merge_stderr else QProcess.SeparateChannels)
        p.setProcessEnvironment(utf8_environment())
        if cwd:
            p.setWorkingDirectory(cwd)
        p.readyReadStandardOutput.connect(self._drain)
        p.finished.connect(self._on_finished)
        p.errorOccurred.connect(self._on_error)
        self._proc = p
        p.start(argv[0], argv[1:])
        self.started.emit()
        return True

    def cancel(self) -> None:
        p = self._proc
        if p is None or p.state() == QProcess.NotRunning:
            return
        terminate_then_kill(p)

    def _drain(self) -> None:
        if self._proc is None:
            return
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        if data:
            self._buf.append(data)
            self.output.emit(data)

    def _on_finished(self, code: int, _status) -> None:
        self._drain()  # flush trailing output before signaling done
        self._proc = None
        self.finished.emit(int(code), "".join(self._buf))

    def _on_error(self, error) -> None:
        # FailedToStart never fires finished(), so a caller would stay "busy" forever;
        # surface it as a finished-with-error so spinners clear and the UI recovers.
        if error == QProcess.FailedToStart and self._proc is not None:
            self._proc = None
            self.finished.emit(-1, "".join(self._buf))
