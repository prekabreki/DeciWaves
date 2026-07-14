"""Tests for `deciwaves <game> run` (Task 9): chained pipelines, resume, GPU/BYO gating.

Stage mains are monkeypatched to record (module, argv) and touch their primary
output so the resume/skip logic under test has something real to look at.
"""
import os
from pathlib import Path

import pytest

from deciwaves.cli import run as run_mod
from deciwaves.cli.main import STAGES


def _mods(game):
    return {k: v[0] for k, v in STAGES[game].items()}


def _touch(path):
    """Mimic a stage main producing its primary output (file or directory)."""
    if os.path.splitext(path)[1]:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        Path(path).touch()
    else:
        os.makedirs(path, exist_ok=True)


def _make_fake_import_stage(calls, outputs_by_module):
    def _import_stage(module_name):
        def _main(argv):
            calls.append((module_name, list(argv)))
            out = outputs_by_module.get(module_name)
            if out:
                _touch(out)
            return 0
        return _main
    return _import_stage


def _after(argv, flag):
    return argv[argv.index(flag) + 1]


@pytest.fixture(autouse=True)
def _restore_cwd():
    cwd = os.getcwd()
    yield
    os.chdir(cwd)


# ---------------------------------------------------------------------------
# ds
# ---------------------------------------------------------------------------

def _ds_outputs(mods):
    return {
        mods["catalog"]: "out/catalog.csv",
        mods["cutscenes"]: "out/cutscene_tracks.csv",
        mods["order"]: "out/playlist.csv",
        mods["render"]: "out/audio",
    }


def test_ds_chain_order_and_injection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mods = _mods("ds")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _ds_outputs(mods)))
    monkeypatch.setattr(run_mod.data, "packaged", lambda rel: Path(f"/pkg/{rel}"))

    cfg = {"ds_install": r"C:\Games\DS"}
    rc = run_mod.run_game("ds", cfg, [])
    assert rc == 0

    called = [m for m, _ in calls]
    assert called == [mods["catalog"], mods["cutscenes"], mods["order"], mods["render"]]

    expected_data_dir = os.path.join(cfg["ds_install"], "data")
    expected_oodle = os.path.join(cfg["ds_install"], "oo2core_7_win64.dll")

    catalog_argv = calls[0][1]
    assert _after(catalog_argv, "--data-dir") == expected_data_dir
    assert _after(catalog_argv, "--oodle") == expected_oodle
    assert _after(catalog_argv, "--file-list") == str(Path("/pkg/ds/data-file-list.txt"))

    cutscenes_argv = calls[1][1]
    assert _after(cutscenes_argv, "--data-dir") == expected_data_dir
    assert _after(cutscenes_argv, "--oodle") == expected_oodle

    render_argv = calls[3][1]
    assert _after(render_argv, "--data-dir") == expected_data_dir
    assert _after(render_argv, "--oodle") == expected_oodle
    assert "--main-story" in render_argv
    assert _after(render_argv, "--speech-trim") == str(Path("/pkg/ds/cutscene-keepspans.csv"))
    assert _after(render_argv, "--bitrate") == "96"


def test_ds_resume_skips_existing_stage(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    os.makedirs("out", exist_ok=True)
    Path("out/catalog.csv").write_text("", encoding="utf-8")

    mods = _mods("ds")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _ds_outputs(mods)))
    monkeypatch.setattr(run_mod.data, "packaged", lambda rel: Path(f"/pkg/{rel}"))

    rc = run_mod.run_game("ds", {"ds_install": "X"}, [])
    assert rc == 0

    called = [m for m, _ in calls]
    assert mods["catalog"] not in called
    assert called == [mods["cutscenes"], mods["order"], mods["render"]]

    out = capsys.readouterr().out
    assert "skip catalog (out/catalog.csv exists — delete it to re-run)" in out


def test_ds_missing_config_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = run_mod.run_game("ds", {}, [])
    assert rc == 1
    assert "deciwaves setup" in capsys.readouterr().out


def test_ds_catalog_missing_packaged_file_list_is_soft_failure(tmp_path, monkeypatch, capsys):
    # Real data.packaged() -- ds/data-file-list.txt genuinely isn't bundled yet in this repo.
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, {}))

    rc = run_mod.run_game("ds", {"ds_install": "X"}, [])
    assert rc == 1
    assert calls == []  # catalog main never invoked -- failed before dispatch

    out = capsys.readouterr().out
    assert "data-file-list" in out
    assert "--file-list" in out


# ---------------------------------------------------------------------------
# hzd
# ---------------------------------------------------------------------------

def _hzd_outputs(mods):
    return {
        mods["catalog"]: "out/hzd/catalog.csv",
        mods["clip-index"]: "out/hzd/clip-index.csv",
        mods["wem-metadata"]: "out/hzd/wem-metadata.csv",
        mods["bind"]: "out/hzd/asr-manifest.csv",
        mods["render"]: "out/hzd/audio",
    }


def test_hzd_chain_order_and_injection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, [])
    assert rc == 0

    called = [m for m, _ in calls]
    assert called == [mods["catalog"], mods["clip-index"], mods["wem-metadata"], mods["bind"], mods["render"]]
    for _, argv in calls:
        assert _after(argv, "--package") == "PKG"


def test_hzd_bind_gpu_gate_aborts_without_whisperx(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, [])
    assert rc == 1

    called = [m for m, _ in calls]
    assert called == [mods["catalog"], mods["clip-index"], mods["wem-metadata"]]

    out = capsys.readouterr().out
    assert "pip install deciwaves[asr]" in out
    assert "pytorch.org" in out


def test_hzd_missing_config_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = run_mod.run_game("hzd", {}, [])
    assert rc == 1
    assert "deciwaves setup" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# fw
# ---------------------------------------------------------------------------

def _fw_outputs(mods):
    return {
        mods["extract"]: "out/fw",
        mods["asr"]: "out/fw/transcripts.csv",
        mods["subtitle-bind"]: "out/fw/subtitle-manifest-full.csv",
        mods["match"]: "out/fw/story-manifest.csv",
        mods["full-reel"]: "out/fw/full-reel-manifest.csv",
        mods["render"]: "out/fw/audio",
    }


def test_fw_byo_stop_without_gamescript(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    rc = run_mod.run_game("fw", {"fw_package": "PKG"}, [])
    assert rc == 0

    called = [m for m, _ in calls]
    assert called == [mods["extract"], mods["asr"], mods["subtitle-bind"]]

    out = capsys.readouterr().out
    assert "gamescript" in out.lower()
    assert "--gamescript" in out


def test_fw_byo_stop_when_gamescript_path_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    rc = run_mod.run_game("fw", {"fw_package": "PKG"}, ["--gamescript", str(tmp_path / "nope.md")])
    assert rc == 0

    called = [m for m, _ in calls]
    assert called == [mods["extract"], mods["asr"], mods["subtitle-bind"]]


def test_fw_full_chain_with_gamescript(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    gamescript = tmp_path / "gamescript.md"
    gamescript.write_text("Aloy: Hello.\n", encoding="utf-8")

    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    rc = run_mod.run_game("fw", {"fw_package": "PKG"}, ["--gamescript", str(gamescript)])
    assert rc == 0

    called = [m for m, _ in calls]
    assert called == [mods["extract"], mods["asr"], mods["subtitle-bind"],
                       mods["match"], mods["full-reel"], mods["render"]]

    match_argv = calls[3][1]
    assert _after(match_argv, "--gamescript") == str(gamescript)

    render_argv = calls[-1][1]
    assert _after(render_argv, "--tiers") == "1,2,S"
    assert _after(render_argv, "--stem") == "fw_story_full"
    assert "--uniform-mono" in render_argv
    assert _after(render_argv, "--manifest") == "out/fw/full-reel-manifest.csv"


def test_fw_asr_gpu_gate_aborts_without_whisperx(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    rc = run_mod.run_game("fw", {"fw_package": "PKG"}, [])
    assert rc == 1

    called = [m for m, _ in calls]
    assert called == [mods["extract"]]

    out = capsys.readouterr().out
    assert "pip install deciwaves[asr]" in out


def test_fw_missing_config_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = run_mod.run_game("fw", {}, [])
    assert rc == 1
    assert "deciwaves setup" in capsys.readouterr().out
