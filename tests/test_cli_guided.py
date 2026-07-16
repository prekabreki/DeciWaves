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
    (hzd / "PackFileLocators.bin").write_bytes(b"x")
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


def test_eoferror_in_game_selection_prints_usage(monkeypatch, capsys):
    """Regression test: EOFError from input() (e.g., deciwaves < NUL on Windows)
    must be caught and handled like non-TTY, not propagate as a traceback.
    """
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def _raise_eof(prompt=""):
        raise EOFError("EOF when reading a line")

    monkeypatch.setattr("builtins.input", _raise_eof)

    rc = guided.run_guided({})
    assert rc == 2  # same exit code as non-TTY case
    out = capsys.readouterr().out
    assert "deciwaves" in out.lower()
    assert "no subcommand" in out.lower()


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


def test_fw_selection_prompts_for_gamescript_and_passes_it(monkeypatch, tmp_path):
    """Guided mode's whole point is completing FW end-to-end -- it must be able
    to both ask for and pass a --gamescript (#23), not just leave the user
    stuck at the BYO stop after subtitle-bind."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.chdir(tmp_path)
    cfg = _all_found_cfg(tmp_path)
    gamescript = tmp_path / "gamescript.md"
    gamescript.write_text("Aloy: Hello.\n", encoding="utf-8")

    responses = iter(["3", "", str(gamescript)])  # pick fw, default workspace, gamescript path
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    calls = {}

    def _fake_run_game(game, cfg_arg, extra_argv):
        calls["args"] = (game, cfg_arg, extra_argv)
        return 0

    monkeypatch.setattr(guided, "run_game", _fake_run_game)

    rc = guided.run_guided(cfg)
    assert rc == 0
    assert calls["args"] == ("fw", cfg, ["--gamescript", str(gamescript)])


def test_fw_selection_gamescript_skip_is_graceful(monkeypatch, tmp_path):
    """Pressing Enter with no gamescript configured must not block or error --
    it's BYO and optional. The run proceeds without a --gamescript flag and
    `run.py`'s own BYO message + graceful exit-0 handles the rest."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.chdir(tmp_path)
    cfg = _all_found_cfg(tmp_path)

    responses = iter(["3", "", ""])  # pick fw, default workspace, skip gamescript
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    calls = {}

    def _fake_run_game(game, cfg_arg, extra_argv):
        calls["args"] = (game, cfg_arg, extra_argv)
        return 0

    monkeypatch.setattr(guided, "run_game", _fake_run_game)

    rc = guided.run_guided(cfg)
    assert rc == 0
    assert calls["args"] == ("fw", cfg, [])


def test_fw_selection_gamescript_prompt_defaults_to_configured_value(monkeypatch, tmp_path):
    """If fw_gamescript is already configured (via `deciwaves setup
    --fw-gamescript`), pressing Enter accepts that configured value rather
    than skipping -- mirrors _prompt_workspace's default-on-blank behavior."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.chdir(tmp_path)
    cfg = _all_found_cfg(tmp_path)
    gamescript = tmp_path / "gamescript.md"
    gamescript.write_text("Aloy: Hello.\n", encoding="utf-8")
    cfg["fw_gamescript"] = str(gamescript)

    responses = iter(["3", "", ""])  # pick fw, default workspace, accept configured default
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    calls = {}

    def _fake_run_game(game, cfg_arg, extra_argv):
        calls["args"] = (game, cfg_arg, extra_argv)
        return 0

    monkeypatch.setattr(guided, "run_game", _fake_run_game)

    rc = guided.run_guided(cfg)
    assert rc == 0
    assert calls["args"] == ("fw", cfg, ["--gamescript", str(gamescript)])


def test_fw_selection_gamescript_eof_prints_usage(monkeypatch, tmp_path, capsys):
    """EOFError on the gamescript prompt (e.g. `deciwaves < NUL`) must be
    handled like every other guided-mode prompt -- never a raw traceback."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.chdir(tmp_path)
    cfg = _all_found_cfg(tmp_path)

    responses = iter(["3", ""])  # pick fw, default workspace, then EOF on gamescript prompt

    def _fake_input(prompt=""):
        try:
            return next(responses)
        except StopIteration:
            raise EOFError("EOF when reading a line")

    monkeypatch.setattr("builtins.input", _fake_input)

    called = {"run_game": False}
    monkeypatch.setattr(guided, "run_game", lambda *a, **k: called.update(run_game=True) or 0)

    rc = guided.run_guided(cfg)
    assert rc == 2
    assert not called["run_game"]
    out = capsys.readouterr().out
    assert "no subcommand" in out.lower()


def test_bare_invocation_dispatches_to_run_guided(monkeypatch):
    from deciwaves.cli import main as cli

    called = {}

    def _fake_run_guided(cfg, workspace=None):
        called["cfg"] = cfg
        called["workspace"] = workspace
        return 0

    monkeypatch.setattr("deciwaves.cli.guided.run_guided", _fake_run_guided)
    rc = cli.main([])
    assert rc == 0
    assert "cfg" in called


def test_bare_workspace_flag_is_not_silently_ignored(monkeypatch, tmp_path):
    """`deciwaves --workspace X` (no subcommand) must not silently drop the
    --workspace flag on the floor -- it must reach run_guided so guided mode's
    own workspace prompt can default to it, instead of always defaulting to
    the process cwd regardless of what --workspace said (issue #32)."""
    from deciwaves.cli import main as cli

    called = {}

    def _fake_run_guided(cfg, workspace=None):
        called["workspace"] = workspace
        return 0

    monkeypatch.setattr("deciwaves.cli.guided.run_guided", _fake_run_guided)
    rc = cli.main(["--workspace", str(tmp_path)])
    assert rc == 0
    assert called["workspace"] == str(tmp_path)


def test_selects_game_prompt_defaults_to_passed_in_workspace(monkeypatch, tmp_path):
    """When main.py passes a --workspace value through as guided's prompt
    default, accepting the prompt with a blank Enter must chdir into THAT
    workspace -- not the process cwd (which is what the old
    `default_ws = str(Path.cwd())` always used, ignoring anything main.py
    might pass in)."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    cfg = _all_found_cfg(tmp_path)

    ws = tmp_path / "my-workspace"

    responses = iter(["1", ""])  # pick ds, accept the shown default workspace
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    calls = {}

    def _fake_run_game(game, cfg_arg, extra_argv):
        calls["cwd"] = os.getcwd()
        return 0

    monkeypatch.setattr(guided, "run_game", _fake_run_game)

    rc = guided.run_guided(cfg, workspace=str(ws))
    assert rc == 0
    assert calls["cwd"] == str(ws)
