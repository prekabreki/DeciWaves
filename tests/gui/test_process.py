"""Terminate-then-kill for the QProcess runners (#424): the kill-timer is owned by the
process it guards, so it cannot fire on a finished or deleted process inside a later event
loop, and a hung child is still force-killed after the grace. Skips without [gui]."""
import sys
import time

import pytest

pytest.importorskip("PySide6")
import shiboken6  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, QTimer  # noqa: E402

from deciwaves.gui import _process  # noqa: E402
from deciwaves.gui.capture import CaptureRunner  # noqa: E402
from deciwaves.gui.jobs import JobRunner  # noqa: E402

GRACE_MS = 300
SLOW = "import time\nfor i in range(200):\n print(i, flush=True); time.sleep(0.02)"
# ignores terminate() on every platform: SIGTERM on POSIX, and a console child on Windows
# never sees the WM_CLOSE -- so only the grace-period kill can stop it
HUNG = ("import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print('ready', flush=True)\ntime.sleep(30)")

RUNNERS = pytest.mark.parametrize("runner_cls", [JobRunner, CaptureRunner])


@pytest.fixture(autouse=True)
def _short_grace(monkeypatch):
    monkeypatch.setattr(_process, "KILL_GRACE_MS", GRACE_MS)


def _flush_deferred_deletes():
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _cancel_and_finish(qtbot, runner):
    """Start a slow child, cancel it, and wait for it to exit. Returns the QProcess."""
    assert runner.start([sys.executable, "-c", SLOW]) is True
    proc = runner._proc
    with qtbot.waitSignal(runner.finished, timeout=5000):
        runner.cancel()
    return proc


@RUNNERS
def test_kill_timer_is_stopped_and_deleted_when_the_process_finishes(qtbot, runner_cls):
    r = runner_cls()
    proc = _cancel_and_finish(qtbot, r)
    _flush_deferred_deletes()
    assert proc.findChildren(QTimer) == []


@RUNNERS
def test_kill_timer_never_fires_on_a_deleted_process(qtbot, runner_cls):
    # The flake from #424: the runner (and with it the QProcess) is torn down while the
    # kill-timer is still armed, and the timer then fires in a later event loop.
    r = runner_cls()
    proc = _cancel_and_finish(qtbot, r)
    shiboken6.delete(r)
    assert not shiboken6.isValid(proc)
    with qtbot.captureExceptions() as exceptions:
        qtbot.wait(GRACE_MS * 3)
    assert exceptions == []


@RUNNERS
def test_hung_process_is_still_killed_after_the_grace(qtbot, runner_cls):
    r = runner_cls()
    chunks = []
    r.output.connect(chunks.append)
    assert r.start([sys.executable, "-c", HUNG]) is True
    qtbot.waitUntil(lambda: any("ready" in c for c in chunks), timeout=5000)
    t0 = time.monotonic()
    with qtbot.waitSignal(r.finished, timeout=5000):
        r.cancel()
    assert time.monotonic() - t0 >= GRACE_MS / 1000 * 0.9  # terminate() alone didn't stop it
    assert r.is_running is False
