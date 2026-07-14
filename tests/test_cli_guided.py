"""TDD for `deciwaves` with no subcommand: the thin guided interactive flow
(Task 17).

The one hard safety rule: run_guided() must never block on input() when
stdin isn't a TTY (CI, pipes, scripted invocation). Everything else is a thin
wrapper: detect usable games via doctor.py's existing check_*_install/package
functions (no duplicated logic), read a numbered choice with plain input(),
then dispatch through the identical deciwaves.cli.run.run_game() path the
`<game> run` subcommand already uses.
"""
import os

import pytest

from deciwaves.cli import guided


@pytest.fixture(autouse=True)
def _restore_cwd():
    cwd = os.getcwd()
    yield
    os.chdir(cwd)


def _all_found_cfg(tmp_path):
    ds = tmp_path / "ds"
    (ds / "data").mkdir(parents=True)
    hzd = tmp_path / "hzd"
    hzd.mkdir()
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "streaming_graph.core").write_bytes(b"x")
    return {"ds_install": str(ds), "hzd_package": str(hzd), "fw_package": str(fw)}


def test_non_tty_never_calls_input_and_prints_usage(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    def _boom(prompt=""):
        raise AssertionError("input() must not be called when stdin isn't a TTY")

    monkeypatch.setattr("builtins.input", _boom)

    rc = guided.run_guided({})
    assert rc != 0
    out = capsys.readouterr().out
    assert "deciwaves" in out.lower()


def test_selects_game_and_dispatches_with_default_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.chdir(tmp_path)
    cfg = _all_found_cfg(tmp_path)

    responses = iter(["1", ""])  # pick game 1 (ds), accept default workspace
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    calls = {}

    def _fake_run_game(game, cfg_arg, extra_argv):
        calls["args"] = (game, cfg_arg, extra_argv)
        calls["cwd"] = os.getcwd()
        return 0

    monkeypatch.setattr(guided, "run_game", _fake_run_game)

    rc = guided.run_guided(cfg)
    assert rc == 0
    assert calls["args"] == ("ds", cfg, [])
    assert calls["cwd"] == str(tmp_path)


def test_invalid_selection_then_valid_reprompts(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.chdir(tmp_path)
    cfg = _all_found_cfg(tmp_path)

    responses = iter(["bogus", "2", ""])  # invalid, then game 2 (hzd), default workspace
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    calls = {}

    def _fake_run_game(game, c, argv):
        calls["game"] = game
        return 0

    monkeypatch.setattr(guided, "run_game", _fake_run_game)

    rc = guided.run_guided(cfg)
    assert rc == 0
    assert calls["game"] == "hzd"
    out = capsys.readouterr().out
    assert "1, 2, or 3" in out  # reprompt message shown after the bad input


def test_unconfigured_game_selection_points_at_setup(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.chdir(tmp_path)
    cfg = {}  # nothing configured -- all three games are "not configured"

    responses = iter(["1"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    called = {"run_game": False}

    def _fail(*a, **k):
        called["run_game"] = True
        return 0

    monkeypatch.setattr(guided, "run_game", _fail)

    rc = guided.run_guided(cfg)
    assert rc != 0
    assert not called["run_game"]
    out = capsys.readouterr().out
    assert "deciwaves setup" in out


def test_bare_invocation_dispatches_to_run_guided(monkeypatch):
    from deciwaves.cli import main as cli

    called = {}

    def _fake_run_guided(cfg):
        called["cfg"] = cfg
        return 0

    monkeypatch.setattr("deciwaves.cli.guided.run_guided", _fake_run_guided)
    rc = cli.main([])
    assert rc == 0
    assert "cfg" in called
