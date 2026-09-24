"""Shared terminate-then-kill for the GUI's QProcess runners (#424).

Both :class:`~deciwaves.gui.jobs.JobRunner` and :class:`~deciwaves.gui.capture.CaptureRunner`
cancel the same way: ``terminate()``, then force-kill after a grace period. The kill-timer
is a child of the process it guards, so it can never outlive it: it is stopped and deleted
when the process finishes, and deleted with the process when the runner is torn down. A
free-standing ``QTimer.singleShot`` lambda closing over the process did outlive it, and
fired ``state()`` on a deleted ``QProcess`` inside whatever event loop ran next."""
from __future__ import annotations

from PySide6.QtCore import QProcess, QTimer

KILL_GRACE_MS = 2000  # after terminate(), force-kill if still alive (Windows consoles
# ignore the WM_CLOSE that terminate() sends, so the kill is what actually stops them)


def terminate_then_kill(p: QProcess, grace_ms: int | None = None) -> None:
    """Ask ``p`` to terminate, and kill it if it is still running ``grace_ms`` later
    (default :data:`KILL_GRACE_MS`, read at call time)."""
    p.terminate()
    timer = QTimer(p)  # owned by the process: destroyed with it, never fires on a dead one
    timer.setSingleShot(True)
    timer.timeout.connect(p.kill)
    p.finished.connect(timer.stop)
    p.finished.connect(timer.deleteLater)
    timer.start(KILL_GRACE_MS if grace_ms is None else grace_ms)
