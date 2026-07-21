"""JobRunner: one-global-job QProcess wrapper (#67, spec §5.3). Skips cleanly without
the [gui] extra."""
import sys

import pytest

pytest.importorskip("PySide6")
from deciwaves.gui.jobs import JobRunner  # noqa: E402

# a child that prints for a while, so a bind/extract-length job can be cancelled mid-run
SLOW = "import sys, time\nfor i in range(200):\n print('line', i, flush=True); time.sleep(0.02)"


def test_streams_output(qtbot):
    r = JobRunner()
    lines = []
    r.output.connect(lines.append)
    # finished is terminal and fires only after the last output is drained, so a single
    # wait on it captures all streamed text without racing a fast process.
    with qtbot.waitSignal(r.finished, timeout=5000):
        assert r.start([sys.executable, "-c", "print('hello', flush=True)"]) is True
    assert any("hello" in chunk for chunk in lines)


def test_only_one_job_at_a_time(qtbot):
    r = JobRunner()
    assert r.start([sys.executable, "-c", SLOW]) is True
    assert r.is_running is True
    assert r.start([sys.executable, "-c", "print('nope')"]) is False   # rejected while busy
    with qtbot.waitSignal(r.finished, timeout=5000):
        r.cancel()
    assert r.is_running is False


def test_cancel_terminates(qtbot):
    r = JobRunner()
    r.start([sys.executable, "-c", SLOW])
    with qtbot.waitSignal(r.finished, timeout=5000):
        r.cancel()
    assert r.is_running is False


def test_start_returns_false_and_no_signal_when_busy(qtbot):
    r = JobRunner()
    r.start([sys.executable, "-c", SLOW])
    assert r.start([sys.executable, "-c", "print(1)"]) is False
    r.cancel()
    with qtbot.waitSignal(r.finished, timeout=5000):
        pass


def test_failed_to_start_finishes_instead_of_hanging(qtbot):
    r = JobRunner()
    with qtbot.waitSignal(r.finished, timeout=5000) as blocker:
        assert r.start(["deciwaves-no-such-program-zzz"]) is True
    (code,) = blocker.args
    assert code == -1
    assert r.is_running is False


def test_sets_utf8_unbuffered_environment(qtbot):
    r = JobRunner()
    assert r.start([sys.executable, "-c", "pass"]) is True
    env = r._proc.processEnvironment()
    assert env.value("PYTHONUTF8") == "1"
    assert env.value("PYTHONIOENCODING") == "utf-8"
    assert env.value("PYTHONUNBUFFERED") == "1"
    with qtbot.waitSignal(r.finished, timeout=5000):
        pass
