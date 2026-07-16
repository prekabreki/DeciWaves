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


def test_workspace_help_documents_ordering_and_path_resolution_semantics(capsys):
    """--workspace's help text must actually explain the two easy-to-get-wrong
    semantics (issue #32): it must precede the game name, and a relative
    stage-flag path resolves against the invocation cwd, not --workspace --
    but ONLY for a path that already exists there. A not-yet-existing
    relative path (e.g. a stage's own output flag) stays workspace-relative,
    same as always -- the help text must not overclaim otherwise (review
    follow-up: it previously said "any relative path ... is resolved
    against ..." unconditionally, which doesn't match
    config.absolutize_existing_paths' existence-based rule)."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])

    assert exc.value.code == 0
    # argparse wraps --workspace's help text across lines -- normalize
    # whitespace before substring-checking so wrap points don't matter.
    out = " ".join(capsys.readouterr().out.split())
    assert "BEFORE the game name" in out
    assert "ALREADY EXISTS there is resolved against the directory you ran" in out
    assert "doesn't exist yet" in out and "stays workspace-relative" in out


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


def test_doctor_unknown_flag_returns_2_not_raw_systemexit(capsys):
    """`deciwaves doctor`'s own argparse usage errors must honor the same
    "usage errors return 2" contract as the top-level parser and the `run`
    subcommand (which already wraps SystemExit via run.py's _parse_or_exit) --
    not propagate as an uncaught SystemExit (issue #33)."""
    assert cli.main(["doctor", "--bogus"]) == 2
    assert "--bogus" in capsys.readouterr().err


def test_setup_unknown_flag_returns_2_not_raw_systemexit(capsys):
    assert cli.main(["setup", "--bogus"]) == 2
    assert "--bogus" in capsys.readouterr().err


def test_stage_own_unknown_flag_returns_2_not_raw_systemexit(tmp_path, capsys):
    """A stage's OWN argparse usage error (dispatched directly, not through
    `run`) must also return 2 rather than propagate SystemExit -- distinct
    from test_unknown_stage_errors (an invalid STAGE NAME, handled by
    main()'s own gp.error() already) and from
    test_game_run_unknown_flag_still_exits_2_without_running_any_stage
    (which goes through run.py's own _parse_or_exit)."""
    rc = cli.main(["--workspace", str(tmp_path), "ds", "catalog",
                   "--data-dir", "X", "--oodle", "Y", "--bogus"])
    assert rc == 2
    assert "--bogus" in capsys.readouterr().err


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


@pytest.mark.parametrize("game", ["ds", "hzd", "fw"])
def test_game_help_shows_each_stage_curated_description(game, capsys):
    """STAGES' per-stage help strings (the second element of each
    `(module_path, help_text)` tuple) used to be dead data -- nothing ever
    printed them (main.py's own dispatch discarded it into `_help`, see
    STAGES[args.cmd][stage]). They must now actually reach the user, as the
    game subparser's epilog (issue #32)."""
    with pytest.raises(SystemExit) as exc:
        cli.main([game, "--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    for stage_name, (_mod, help_text) in cli.STAGES[game].items():
        assert stage_name in out
        assert help_text in out, f"{game} {stage_name}'s curated help text missing from --help output"


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


def test_relative_stage_flag_path_survives_workspace_chdir(monkeypatch, tmp_path):
    """chdir-before-dispatch used to mis-resolve relative stage-flag paths: a
    relative --gamescript is meant relative to where the user ran `deciwaves`
    from, but main.py's --workspace chdir happens BEFORE the stage (or `run`)
    ever sees it, so it got looked up inside the workspace instead -- silently
    wrong (issue #32). A path that exists relative to the original cwd must
    be absolutized before the chdir, so it still points at the same file."""
    invoke_dir = tmp_path / "invoke_dir"
    invoke_dir.mkdir()
    gamescript = invoke_dir / "gamescript.md"
    gamescript.write_text("Aloy: hi\n", encoding="utf-8")
    monkeypatch.chdir(invoke_dir)

    workspace = tmp_path / "ws"

    seen = {}

    def _fake_run_game(game, cfg, extra_argv):
        seen["argv"] = extra_argv
        return 0

    monkeypatch.setattr(run_mod, "run_game", _fake_run_game)

    rc = cli.main(["--workspace", str(workspace), "fw", "run",
                   "--gamescript", "gamescript.md"])

    assert rc == 0
    assert seen["argv"] == ["--gamescript", str(gamescript)]


def test_relative_path_that_never_existed_is_left_untouched(monkeypatch, tmp_path):
    """A typo'd/never-existed relative path must not be rewritten -- it still
    fails whatever stage's own "not found" check the same way it always did,
    just relative to the workspace instead of the original cwd (no change for
    this case, which was already a loud, correctly-nonzero failure)."""
    called = {}

    def _stage(argv):
        called["argv"] = argv
        return 0

    monkeypatch.setattr(cli, "_import_stage", lambda mod: _stage)
    rc = cli.main(["--workspace", str(tmp_path), "ds", "catalog",
                   "--data-dir", "no-such-relative-dir", "--oodle", "Y"])
    assert rc == 0
    assert called["argv"] == ["--data-dir", "no-such-relative-dir", "--oodle", "Y"]
