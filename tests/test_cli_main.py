import os

import pytest

from deciwaves.cli import main as cli
from deciwaves.cli import run as run_mod


@pytest.fixture(autouse=True)
def _restore_cwd():
    # main() intentionally os.chdir()s into --workspace; restore afterwards so
    # this test module never leaks a changed cwd onto the rest of the suite.
    cwd = os.getcwd()
    yield
    os.chdir(cwd)


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert "0.1.0" in capsys.readouterr().out


def test_stage_dispatch_passes_argv(monkeypatch, tmp_path):
    # NOTE: the brief's literal lambda was `lambda argv: called.setdefault("argv", argv) or 0`.
    # dict.setdefault(key, default) *returns the stored value*, not None -- so that
    # expression evaluates to the (truthy) argv list, never falling through to `0`, and
    # `rc == 0` could never pass regardless of the CLI implementation. Rewritten with the
    # same intent (record dispatched argv, report success) without the setdefault footgun.
    called = {}

    def _stage(argv):
        called["argv"] = argv
        return 0

    monkeypatch.setattr(cli, "_import_stage", lambda mod: _stage)
    rc = cli.main(["--workspace", str(tmp_path), "ds", "catalog", "--data-dir", "X", "--oodle", "Y"])
    assert rc == 0
    assert called["argv"] == ["--data-dir", "X", "--oodle", "Y"]


def test_workspace_chdir(monkeypatch, tmp_path):
    import os
    seen = {}
    monkeypatch.setattr(cli, "_import_stage", lambda mod: lambda argv: seen.setdefault("cwd", os.getcwd()) or 0)
    cli.main(["--workspace", str(tmp_path), "hzd", "catalog", "--package", "P"])
    assert seen["cwd"] == str(tmp_path)


def test_unknown_stage_errors(capsys):
    assert cli.main(["ds", "frobnicate"]) == 2


@pytest.mark.parametrize("game", ["ds", "hzd", "fw"])
def test_game_run_help_reaches_run_specific_parser(game, tmp_path, monkeypatch, capsys):
    """`deciwaves <game> run --help` must print run.py's own, run-specific help
    (its own prog string) and exit 0 -- not the generic `deciwaves <game>` stage-list
    help, and it must never dispatch a single stage. See #8."""
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", lambda mod: (lambda argv: calls.append((mod, argv)) or 0))

    with pytest.raises(SystemExit) as exc:
        cli.main(["--workspace", str(tmp_path), game, "run", "--help"])

    assert exc.value.code == 0
    assert calls == []
    out = capsys.readouterr().out
    # argparse's format_help() always starts with "usage: <prog> ..." -- this is
    # the one string unique to run.py's own parser (built with
    # prog="deciwaves <game> run"), so this proves it's genuinely the
    # run-specific help, not the generic `deciwaves <game>` stage-list help
    # (whose usage line has no trailing "run" and instead lists all stage names
    # as its positional argument's choices).
    assert out.startswith(f"usage: deciwaves {game} run ")
    assert "positional arguments:" not in out  # that's gp's generic stage-list section


def test_game_run_unknown_flag_still_exits_2_without_running_any_stage(tmp_path, monkeypatch, capsys):
    """A typo'd flag after `run` must still error out (exit 2) through the real CLI
    entry point, naming the bad flag, without dispatching any stage. See #8."""
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", lambda mod: (lambda argv: calls.append((mod, argv)) or 0))

    rc = cli.main(["--workspace", str(tmp_path), "ds", "run", "--bogus-flag"])

    assert rc == 2
    assert calls == []
    assert "--bogus-flag" in capsys.readouterr().err


def test_game_help_alone_still_shows_generic_stage_list(capsys):
    """`deciwaves ds --help` (no stage given) must still show the game-level help
    with the full stage list -- the fix for `run --help` must not break this."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["ds", "--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    for stage_name in ("catalog", "cutscenes", "trim", "order", "render", "run"):
        assert stage_name in out


def test_non_run_stage_help_does_not_execute_the_stage(tmp_path, capsys):
    """`deciwaves ds catalog --help` must not execute the catalog stage. Drives the
    REAL catalog module (no faking `_import_stage`): catalog.py's own argparse
    requires --data-dir/--oodle, so if the stage actually ran with only --help in
    its argv it would blow up on missing required args, not exit 0 cleanly. This
    proves --help short-circuits before any real work -- no output written. See
    #8 requirement to verify (not silently ship) this path."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["--workspace", str(tmp_path), "ds", "catalog", "--help"])

    assert exc.value.code == 0
    assert not (tmp_path / "out").exists()
