import os
import subprocess
import sys

import pytest

from deciwaves.cli import main as cli


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


def test_lazy_stage_import():
    """`deciwaves.cli.main` must not eagerly import any stage module -- the CLI applies
    config-derived env (tool PATH/env vars) in `_apply_config_env()` before any stage
    module import, and `engine.audio_clip` / `games.fw.extract` / `games.hzd.atrac9`
    resolve their tool paths at import time. Run in a fresh subprocess so sys.modules
    isn't already polluted by other test files in this same pytest run.
    """
    script = (
        "import sys\n"
        "import deciwaves.cli.main\n"
        "assert 'deciwaves.engine.catalog' not in sys.modules, sorted(m for m in sys.modules if m.startswith('deciwaves'))\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
