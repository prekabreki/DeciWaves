"""Qt preview player (#71, spec §6.5). Skips without the [gui-test] extra. The decode
resolver is Qt-free and covered in test_preview_model.py; here we assert the thin threaded
player: it plays a resolved path through an injectable sink, stops before each new play,
ignores stale (superseded) results, and surfaces failures as a signal -- all without a real
audio device (CI has none), via a fake sink + a fake thread pool driven deterministically.
"""
import pytest

pytest.importorskip("PySide6")

from deciwaves.gui.preview import PreviewPlayer  # noqa: E402
from deciwaves.gui.preview_model import PreviewError  # noqa: E402


class _FakeSink:
    def __init__(self):
        self.log = []

    def play(self, path):
        self.log.append(("play", path))

    def stop(self):
        self.log.append(("stop",))


class _FakeResolver:
    def __init__(self, mapping):
        self._m = mapping

    def resolve_wav(self, line_id, audio_path):
        return self._m[line_id]


class _BoomResolver:
    def resolve_wav(self, line_id, audio_path):
        raise PreviewError("no install")


class _FakePool:
    """Records dispatched runnables but never runs them, so the test drives the player's
    result slots deterministically (no thread, no timing)."""

    def __init__(self):
        self.jobs = []

    def start(self, runnable):
        self.jobs.append(runnable)


# --- real pool: worker resolves off-thread, result plays through the sink ---

def test_play_line_resolves_and_plays(qtbot):
    sink = _FakeSink()
    player = PreviewPlayer(sink=sink)
    resolver = _FakeResolver({"a": "C:/wav/a.wav"})
    with qtbot.waitSignal(player.now_playing, timeout=3000) as blocker:
        player.play_line(resolver, "a", None)
    assert blocker.args == ["C:/wav/a.wav"]
    assert ("play", "C:/wav/a.wav") in sink.log


def test_play_line_failure_emits_preview_failed(qtbot):
    sink = _FakeSink()
    player = PreviewPlayer(sink=sink)
    with qtbot.waitSignal(player.preview_failed, timeout=3000) as blocker:
        player.play_line(_BoomResolver(), "a", None)
    assert blocker.args == ["no install"]
    assert not any(c[0] == "play" for c in sink.log)


# --- deterministic (fake pool): generation token + single-at-a-time --------

def test_stop_precedes_play(qtbot):
    sink, pool = _FakeSink(), _FakePool()
    player = PreviewPlayer(sink=sink, pool=pool)
    player.play_line(_FakeResolver({"a": "a.wav"}), "a", None)
    player._on_done(1, "a.wav")
    assert sink.log == [("stop",), ("play", "a.wav")]


def test_two_rapid_plays_stop_first_and_ignore_stale(qtbot):
    sink, pool = _FakeSink(), _FakePool()
    player = PreviewPlayer(sink=sink, pool=pool)
    r = _FakeResolver({"a": "a.wav", "b": "b.wav"})
    player.play_line(r, "a", None)   # generation 1 -> stop
    player.play_line(r, "b", None)   # generation 2 -> stop
    assert sink.log == [("stop",), ("stop",)]  # both requests stopped current playback
    player._on_done(2, "b.wav")      # current result plays
    player._on_done(1, "a.wav")      # stale (superseded) result is ignored
    assert ("play", "b.wav") in sink.log
    assert ("play", "a.wav") not in sink.log


def test_stale_failure_is_ignored(qtbot):
    sink, pool = _FakeSink(), _FakePool()
    player = PreviewPlayer(sink=sink, pool=pool)
    fired = []
    player.preview_failed.connect(fired.append)
    player.play_line(_FakeResolver({"a": "a.wav"}), "a", None)  # generation 1
    player.play_line(_FakeResolver({"b": "b.wav"}), "b", None)  # generation 2
    player._on_failed(1, "stale error")   # from the superseded request -> ignored
    assert fired == []
    player._on_failed(2, "current error")
    assert fired == ["current error"]


# --- shell wiring ----------------------------------------------------------

def test_shell_wires_preview_requested_to_player(qtbot, monkeypatch):
    from deciwaves.gui.shell import MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    calls = []
    monkeypatch.setattr(w.player, "play_line", lambda resolver, lid, ap: calls.append(lid))
    w.library.preview_requested.emit("some-id")
    assert calls == ["some-id"]


def test_shell_surfaces_preview_failure_in_log(qtbot):
    from deciwaves.gui.shell import MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    w.player.preview_failed.emit("boom-message")
    assert "boom-message" in w.pipeline.log_text()


# --- config env applied on the GUI launch path (bypasses cli.main) ---------

def test_launch_applies_decoder_env_from_config(tmp_path, monkeypatch):
    import os

    from deciwaves import gui
    from deciwaves.cli import config
    from deciwaves.gui import app as app_mod

    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "vgmstream-cli.exe").write_bytes(b"x")
    (tools / "VGAudioCli.exe").write_bytes(b"x")
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))  # tracked, so the prepend is reverted
    config.save({"tools_dir": str(tools)})
    monkeypatch.delenv("DECIWAVES_VGMSTREAM", raising=False)
    monkeypatch.delenv("DECIWAVES_VGAUDIO", raising=False)
    monkeypatch.setattr(app_mod, "run_app", lambda argv=None: 0)  # don't build/exec the GUI

    assert gui.launch([]) == 0
    assert os.environ["DECIWAVES_VGMSTREAM"] == str(tools / "vgmstream-cli.exe")
    assert os.environ["DECIWAVES_VGAUDIO"] == str(tools / "VGAudioCli.exe")
