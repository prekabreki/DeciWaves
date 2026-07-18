"""Pure CLI-command construction for the job runner (#67). Qt-free -- runs on a base
install with no [gui] extra (no importorskip), so the --workspace/abs-path discipline
is covered unconditionally."""
import os
import sys

from deciwaves.gui.cli_command import build_cli_command, default_base


def test_workspace_is_absolute_and_before_game(tmp_path):
    cmd = build_cli_command(["deciwaves"], str(tmp_path), "hzd", "run", "--until", "catalog")
    assert cmd[0] == "deciwaves"
    i_ws, i_game = cmd.index("--workspace"), cmd.index("hzd")
    assert i_ws < i_game                      # --workspace before the game token (spec §4, §9)
    assert os.path.isabs(cmd[i_ws + 1])


def test_relative_workspace_absolutized(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    cmd = build_cli_command(["deciwaves"], "outdir", "ds", "catalog")
    assert cmd[cmd.index("--workspace") + 1] == str((tmp_path / "outdir").resolve())


def test_default_base_uses_current_interpreter():
    assert default_base() == [sys.executable, "-m", "deciwaves.cli.main"]


def test_tokens_preserved_in_order():
    cmd = build_cli_command(["x"], "/w", "fw", "run", "--gamescript", "/abs/gs.txt")
    assert cmd[-3:] == ["run", "--gamescript", "/abs/gs.txt"]
