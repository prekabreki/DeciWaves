"""CaptureRunner: a QProcess wrapper that streams AND accumulates stdout, so the Doctor
panel can parse `doctor --json` and the Setup screen can parse setup's summary on finish
(#68). One run at a time, cancel is safe -- same contract as JobRunner. Skips without [gui]."""
import sys

import pytest

pytest.importorskip("PySide6")
from deciwaves.gui.capture import CaptureRunner  # noqa: E402

SLOW = "import time\nfor i in range(200):\n print(i, flush=True); time.sleep(0.02)"


def test_finished_carries_exit_code_and_full_text(qtbot):
    r = CaptureRunner()
    with qtbot.waitSignal(r.finished, timeout=5000) as blocker:
        assert r.start([sys.executable, "-c", "print('a'); print('b')"]) is True
    code, text = blocker.args
    assert code == 0
    assert "a" in text and "b" in text


def test_streams_chunks_for_a_live_console(qtbot):
    r = CaptureRunner()
    chunks = []
    r.output.connect(chunks.append)
    with qtbot.waitSignal(r.finished, timeout=5000):
        assert r.start([sys.executable, "-c", "print('hi', flush=True)"]) is True
    assert any("hi" in c for c in chunks)


def test_only_one_run_at_a_time(qtbot):
    r = CaptureRunner()
    assert r.start([sys.executable, "-c", SLOW]) is True
    assert r.is_running is True
    assert r.start([sys.executable, "-c", "print('nope')"]) is False
    with qtbot.waitSignal(r.finished, timeout=5000):
        r.cancel()
    assert r.is_running is False


def test_cancel_is_safe(qtbot):
    r = CaptureRunner()
    r.start([sys.executable, "-c", SLOW])
    with qtbot.waitSignal(r.finished, timeout=5000):
        r.cancel()
    assert r.is_running is False


def test_failed_to_start_finishes_instead_of_hanging(qtbot):
    # QProcess.start() is async and won't report FailedToStart synchronously; without
    # errorOccurred handling a bad program would leave a caller "busy" forever.
    r = CaptureRunner()
    with qtbot.waitSignal(r.finished, timeout=5000) as blocker:
        assert r.start(["deciwaves-no-such-program-zzz"]) is True
    code, _text = blocker.args
    assert code != 0
    assert r.is_running is False
