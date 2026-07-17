"""Tests for `deciwaves <game> run` (Task 9): chained pipelines, resume, GPU/BYO gating.

Stage mains are monkeypatched to record (module, argv) and touch their real
output path/dir, so tests can assert on the actual directory shape a stage
leaves behind (e.g. the fw extract fake creates out/fw/audio, matching the
real extractor -- see #6). Resume/skip itself is driven purely by per-stage
done-marker files (see `_marker` below), never by that output existing.
"""
import os
from pathlib import Path

import pytest

from deciwaves.cli import run as run_mod
from deciwaves.cli.main import STAGES
from deciwaves.cli.main import _import_stage as real_import_stage


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


def _marker(game, stage):
    """The per-stage done-marker path _run_chain reads/writes (issues #15, #6)."""
    return os.path.join("out", game, f".done-{stage}")


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
    # "cutscenes" is NOT part of the default chain -- the order stage is fed the
    # bundled, pre-resolved cutscene tracks instead of regenerating them.
    assert called == [mods["catalog"], mods["order"], mods["render"]]

    expected_data_dir = os.path.join(cfg["ds_install"], "data")
    expected_oodle = os.path.join(cfg["ds_install"], "oo2core_7_win64.dll")

    catalog_argv = calls[0][1]
    assert _after(catalog_argv, "--data-dir") == expected_data_dir
    assert _after(catalog_argv, "--oodle") == expected_oodle
    assert _after(catalog_argv, "--file-list") == str(Path("/pkg/ds/data-file-list.txt"))

    order_argv = calls[1][1]
    assert _after(order_argv, "--cutscene-tracks") == str(Path("/pkg/ds/cutscene_tracks.csv"))

    render_argv = calls[2][1]
    assert _after(render_argv, "--data-dir") == expected_data_dir
    assert _after(render_argv, "--oodle") == expected_oodle
    assert "--main-story" in render_argv
    assert _after(render_argv, "--speech-trim") == str(Path("/pkg/ds/cutscene-keepspans.csv"))
    assert _after(render_argv, "--bitrate") == "96"


def test_ds_stage_not_skipped_by_old_output_sentinel_alone(tmp_path, monkeypatch):
    """Path/directory existence is no longer a skip criterion (#15): a pre-existing
    output file (e.g. a leftover from an old build, or a crash right after a stage's
    own mkdir) must not look like "done" -- only a written done-marker does."""
    monkeypatch.chdir(tmp_path)
    os.makedirs("out", exist_ok=True)
    Path("out/catalog.csv").write_text("", encoding="utf-8")  # old-style sentinel; no marker

    mods = _mods("ds")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _ds_outputs(mods)))
    monkeypatch.setattr(run_mod.data, "packaged", lambda rel: Path(f"/pkg/{rel}"))

    rc = run_mod.run_game("ds", {"ds_install": "X"}, [])
    assert rc == 0

    called = [m for m, _ in calls]
    assert called == [mods["catalog"], mods["order"], mods["render"]]


def test_ds_stage_skipped_when_done_marker_exists(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    marker = _marker("ds", "catalog")
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    Path(marker).write_text("", encoding="utf-8")

    mods = _mods("ds")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _ds_outputs(mods)))
    monkeypatch.setattr(run_mod.data, "packaged", lambda rel: Path(f"/pkg/{rel}"))

    rc = run_mod.run_game("ds", {"ds_install": "X"}, [])
    assert rc == 0

    called = [m for m, _ in calls]
    assert mods["catalog"] not in called
    assert called == [mods["order"], mods["render"]]

    out = capsys.readouterr().out
    assert f"skip catalog ({marker} exists -- delete it to force a re-run)" in out
    assert "catalog.csv" not in out  # must name the marker, never advise deleting the output


def test_ds_marker_not_written_on_failure_and_chain_aborts(tmp_path, monkeypatch):
    """A stage that returns nonzero must not be marked done, and the chain must
    stop there (this abort path was previously untested)."""
    monkeypatch.chdir(tmp_path)
    mods = _mods("ds")
    calls = []

    def _import_stage(module_name):
        def _main(argv):
            calls.append((module_name, list(argv)))
            return 3 if module_name == mods["order"] else 0
        return _main

    monkeypatch.setattr(run_mod, "_import_stage", _import_stage)
    monkeypatch.setattr(run_mod.data, "packaged", lambda rel: Path(f"/pkg/{rel}"))

    rc = run_mod.run_game("ds", {"ds_install": "X"}, [])
    assert rc == 3

    called = [m for m, _ in calls]
    assert called == [mods["catalog"], mods["order"]]  # render never reached

    assert os.path.isfile(_marker("ds", "catalog"))    # succeeded -> marked done
    assert not os.path.exists(_marker("ds", "order"))  # failed -> no marker
    assert not os.path.exists(_marker("ds", "render"))  # never ran


def test_ds_rerunning_early_stage_invalidates_downstream_markers(tmp_path, monkeypatch):
    """Issue #37: re-running an early stage must invalidate every LATER stage's
    done-marker, so a stale catalog rebuild doesn't leave stale order/render
    markers standing (which would make a fresh run indistinguishable from a
    stale one). Deleting only the catalog marker and re-running must re-execute
    catalog, order, AND render -- not just catalog."""
    monkeypatch.chdir(tmp_path)
    mods = _mods("ds")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _ds_outputs(mods)))
    monkeypatch.setattr(run_mod.data, "packaged", lambda rel: Path(f"/pkg/{rel}"))

    cfg = {"ds_install": r"C:\Games\DS"}
    rc = run_mod.run_game("ds", cfg, [])
    assert rc == 0
    assert [m for m, _ in calls] == [mods["catalog"], mods["order"], mods["render"]]
    for stage in ("catalog", "order", "render"):
        assert os.path.isfile(_marker("ds", stage))

    calls.clear()
    os.remove(_marker("ds", "catalog"))  # simulate a game-patch-triggered re-catalog

    rc = run_mod.run_game("ds", cfg, [])
    assert rc == 0

    # catalog re-ran (its own marker was gone) and that re-run must have
    # invalidated order's and render's markers too, so both re-execute rather
    # than being skipped on stale data.
    assert [m for m, _ in calls] == [mods["catalog"], mods["order"], mods["render"]]


def test_ds_full_skip_run_stays_full_skip(tmp_path, monkeypatch, capsys):
    """Guard for #37's fix: when every stage is already done, nothing executes
    and nothing gets invalidated -- a fully-resumed run must remain a no-op."""
    monkeypatch.chdir(tmp_path)
    mods = _mods("ds")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _ds_outputs(mods)))
    monkeypatch.setattr(run_mod.data, "packaged", lambda rel: Path(f"/pkg/{rel}"))

    cfg = {"ds_install": r"C:\Games\DS"}
    rc = run_mod.run_game("ds", cfg, [])
    assert rc == 0
    calls.clear()

    rc = run_mod.run_game("ds", cfg, [])
    assert rc == 0
    assert calls == []  # every stage skipped -- none invalidated, none re-ran
    for stage in ("catalog", "order", "render"):
        assert os.path.isfile(_marker("ds", stage))


def test_ds_missing_config_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = run_mod.run_game("ds", {}, [])
    assert rc == 1
    assert "deciwaves setup" in capsys.readouterr().out


def test_ds_catalog_missing_packaged_file_list_is_soft_failure(tmp_path, monkeypatch, capsys):
    # ds/data-file-list.txt is bundled in this repo now (Task 5); simulate an older
    # build that predates it by monkeypatching packaged() to raise for it specifically.
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, {}))

    def _packaged_side_effect(rel):
        if "data-file-list" in rel:
            raise FileNotFoundError(rel)
        return Path(f"/pkg/{rel}")

    monkeypatch.setattr(run_mod.data, "packaged", _packaged_side_effect)

    rc = run_mod.run_game("ds", {"ds_install": "X"}, [])
    assert rc == 1
    assert calls == []  # catalog main never invoked -- failed before dispatch

    out = capsys.readouterr().out
    assert "data-file-list" in out
    assert "--file-list" in out


def test_ds_order_missing_packaged_cutscene_tracks_is_soft_failure(tmp_path, monkeypatch, capsys):
    # Simulate an older build that predates the bundled ds/cutscene_tracks.csv.
    monkeypatch.chdir(tmp_path)
    mods = _mods("ds")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _ds_outputs(mods)))

    def _packaged_side_effect(rel):
        if "cutscene_tracks" in rel:
            raise FileNotFoundError(rel)
        return Path(f"/pkg/{rel}")

    monkeypatch.setattr(run_mod.data, "packaged", _packaged_side_effect)

    rc = run_mod.run_game("ds", {"ds_install": "X"}, [])
    assert rc == 1
    # order/render mains never invoked -- failed at stage config (before dispatch)
    # But catalog should have run first.
    assert [m for m, _ in calls] == [mods["catalog"]]

    out = capsys.readouterr().out
    assert "cutscene_tracks" in out
    assert "--cutscene-tracks" in out


def test_ds_render_missing_packaged_keepspans_is_soft_failure(tmp_path, monkeypatch, capsys):
    # Monkeypatch packaged() to raise FileNotFoundError for cutscene-keepspans.csv
    monkeypatch.chdir(tmp_path)
    mods = _mods("ds")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _ds_outputs(mods)))

    def _packaged_side_effect(rel):
        if "cutscene-keepspans" in rel:
            raise FileNotFoundError(rel)
        return Path(f"/pkg/{rel}")

    monkeypatch.setattr(run_mod.data, "packaged", _packaged_side_effect)

    rc = run_mod.run_game("ds", {"ds_install": "X"}, [])
    assert rc == 1
    # render main never invoked -- failed at stage config (before dispatch)
    # But earlier stages (catalog, order) should have run
    assert mods["render"] not in [m for m, _ in calls]

    out = capsys.readouterr().out
    assert "cutscene-keepspans" in out
    assert "--speech-trim" in out


def test_ds_run_help_exits_0_without_running_any_stage(tmp_path, monkeypatch, capsys):
    """`deciwaves ds run --help` must print real help for the run parser (its own
    prog name, at minimum) and exit 0 -- and never dispatch a single stage. See #8."""
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, {}))

    with pytest.raises(SystemExit) as exc:
        run_mod.run_game("ds", {"ds_install": "X"}, ["--help"])

    assert exc.value.code == 0
    assert calls == []
    assert "deciwaves ds run" in capsys.readouterr().out


def test_ds_run_help_after_other_flags_still_exits_0_without_running_any_stage(tmp_path, monkeypatch, capsys):
    """--help must win no matter where it falls in argv, same as any argparse CLI."""
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, {}))

    with pytest.raises(SystemExit) as exc:
        run_mod.run_game("ds", {"ds_install": "X"}, ["--data-dir", "OTHER", "--help"])

    assert exc.value.code == 0
    assert calls == []
    assert "deciwaves ds run" in capsys.readouterr().out


def test_ds_run_unknown_flag_exits_2_without_running_any_stage(tmp_path, monkeypatch, capsys):
    """A typo'd flag must be a usage error naming it (exit 2), not silently
    dropped into a live multi-hour pipeline. See #8."""
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, {}))

    rc = run_mod.run_game("ds", {"ds_install": "X"}, ["--bogus-flag"])

    assert rc == 2
    assert calls == []
    assert "--bogus-flag" in capsys.readouterr().err


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


def test_hzd_bind_argv_omits_transcripts_when_sidecar_absent(tmp_path, monkeypatch):
    """A fresh workspace (no prior asr-transcripts.csv) has nothing to resume from --
    bind's argv must not include --transcripts."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, [])
    assert rc == 0

    bind_argv = dict(calls)[mods["bind"]]
    assert "--transcripts" not in bind_argv


def test_hzd_bind_argv_includes_transcripts_when_sidecar_present(tmp_path, monkeypatch):
    """A sidecar already sitting at asr_bind's own default --transcripts-out path (left
    behind by a crashed/interrupted prior bind run) must be passed back in via
    --transcripts, so a re-run of `hzd run` actually resumes instead of re-transcribing
    everything from scratch -- making the README's "an interrupted bind picks up where
    it stopped" claim true for the chained `run` command, not just a manual `hzd bind
    --transcripts ...` invocation."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    sidecar = Path(run_mod.asr_bind.DEFAULT_TRANSCRIPTS_OUT)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text("clip_row,transcript\n0,prior ok\n", encoding="utf-8")

    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, [])
    assert rc == 0

    bind_argv = dict(calls)[mods["bind"]]
    assert _after(bind_argv, "--transcripts") == run_mod.asr_bind.DEFAULT_TRANSCRIPTS_OUT


def test_hzd_bind_argv_omits_sample_cap_when_not_given(tmp_path, monkeypatch):
    """No --sample-cap given to `hzd run`: bind's argv must not include it at all, so
    the bind stage falls back to its own bounded default (300) -- issue #35."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, [])
    assert rc == 0

    bind_argv = dict(calls)[mods["bind"]]
    assert "--sample-cap" not in bind_argv


def test_hzd_bind_argv_forwards_sample_cap_when_given(tmp_path, monkeypatch):
    """`--sample-cap` passed to `hzd run` must reach the bind stage (issue #35) --
    it's the flag that governs how much ASR work bind actually does; without
    forwarding, a user-supplied cap would be silently ignored by the chain."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, ["--sample-cap", "42"])
    assert rc == 0

    bind_argv = dict(calls)[mods["bind"]]
    assert _after(bind_argv, "--sample-cap") == "42"


def test_hzd_bind_argv_forwards_sample_cap_zero_for_full_pass(tmp_path, monkeypatch):
    """0 must be forwarded as-is, never treated as falsy/omitted -- it's the
    documented "unlimited full pass" sentinel asr_bind.py's --sample-cap already
    understands (issue #35)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, ["--sample-cap", "0"])
    assert rc == 0

    bind_argv = dict(calls)[mods["bind"]]
    assert _after(bind_argv, "--sample-cap") == "0"


def test_hzd_run_help_documents_sample_cap_flag(tmp_path, monkeypatch, capsys):
    """`deciwaves hzd run --help` must document --sample-cap and that 0 means an
    unlimited full pass (issue #35) -- a forwarded flag `run --help` never mentions
    is undiscoverable."""
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, {}))

    with pytest.raises(SystemExit) as exc:
        run_mod.run_game("hzd", {"hzd_package": "PKG"}, ["--help"])

    assert exc.value.code == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "--sample-cap" in out
    assert "unlimited" in out.lower()


def test_hzd_bind_gpu_gate_aborts_without_whisperx(tmp_path, monkeypatch, capsys):
    """The GPU gate is scanned UPFRONT, before any stage runs -- not discovered
    mid-chain after catalog/clip-index/wem-metadata already ran (potentially
    hours of work wasted just to learn `bind` will fail). See issue #33."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, [])
    assert rc == 1

    called = [m for m, _ in calls]
    assert called == []  # nothing runs -- the gate fires before catalog even starts

    out = capsys.readouterr().out
    assert "pip install deciwaves[asr]" in out
    assert "pytorch.org" in out


def test_hzd_bind_gpu_gate_ignored_when_bind_already_done(tmp_path, monkeypatch, capsys):
    """The upfront scan must not block a chain whose GPU-gated stage is
    already marked done (e.g. it ran earlier when whisperx WAS installed) --
    only a not-yet-done GPU stage should trip the gate."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))
    for stage in ("catalog", "clip-index", "wem-metadata", "bind"):
        marker = _marker("hzd", stage)
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        Path(marker).write_text("", encoding="utf-8")

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, [])
    assert rc == 0

    called = [m for m, _ in calls]
    assert called == [mods["render"]]  # every earlier stage skipped via its marker


def test_hzd_gpu_gate_fires_upfront_when_early_marker_deleted_forces_bind_rerun(
        tmp_path, monkeypatch, capsys):
    """Finding 1 (WORST): the upfront GPU scan must be invalidation-aware. A user
    without the [asr] extra deletes .done-catalog to force a re-catalog; every
    other marker (including .done-bind) is still present. Because catalog WILL
    re-run, it will invalidate .done-bind mid-chain -- so bind WILL effectively
    run and hit the missing-whisperx wall. The gate must recognise this UP FRONT
    (bind's own marker present is not enough), abort before catalog's hours of
    work, and run ZERO stages."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)  # whisperx absent
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))
    # Seed EVERY stage's done-marker (a fully-resumed workspace)...
    for stage in ("catalog", "clip-index", "wem-metadata", "bind", "render"):
        marker = _marker("hzd", stage)
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        Path(marker).write_text("", encoding="utf-8")
    # ...then delete only the EARLY one, forcing a re-catalog that will cascade
    # invalidation down to bind.
    os.remove(_marker("hzd", "catalog"))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, [])
    assert rc == 1

    assert [m for m, _ in calls] == []  # nothing ran -- gate fired before catalog
    out = capsys.readouterr().out
    assert "pip install deciwaves[asr]" in out


def test_fw_gpu_gate_fires_upfront_when_extract_marker_deleted_forces_asr_rerun(
        tmp_path, monkeypatch, capsys):
    """Finding 1, fw variant: the invalidation-aware scan must reason over the
    FULL chain even though fw splits it into two `_run_chain` calls. Deleting
    .done-extract forces extract to re-run, which invalidates the (present)
    .done-asr marker -- so the GPU-gated asr stage will effectively run. Gate
    must fire upfront with no stages executed."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)  # whisperx absent
    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))
    for stage in ("extract", "asr", "subtitle-bind", "match", "full-reel", "render"):
        marker = _marker("fw", stage)
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        Path(marker).write_text("", encoding="utf-8")
    os.remove(_marker("fw", "extract"))

    rc = run_mod.run_game("fw", {"fw_package": "PKG"}, [])
    assert rc == 1

    assert [m for m, _ in calls] == []
    out = capsys.readouterr().out
    assert "pip install deciwaves[asr]" in out


def test_hzd_missing_config_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = run_mod.run_game("hzd", {}, [])
    assert rc == 1
    assert "deciwaves setup" in capsys.readouterr().out


def test_hzd_run_help_exits_0_without_running_any_stage(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, {}))

    with pytest.raises(SystemExit) as exc:
        run_mod.run_game("hzd", {"hzd_package": "PKG"}, ["--help"])

    assert exc.value.code == 0
    assert calls == []
    assert "deciwaves hzd run" in capsys.readouterr().out


def test_hzd_run_help_after_other_flags_still_exits_0_without_running_any_stage(tmp_path, monkeypatch, capsys):
    """--help must win no matter where it falls in argv, same as any argparse CLI."""
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, {}))

    with pytest.raises(SystemExit) as exc:
        run_mod.run_game("hzd", {"hzd_package": "PKG"}, ["--package", "OTHER", "--help"])

    assert exc.value.code == 0
    assert calls == []
    assert "deciwaves hzd run" in capsys.readouterr().out


def test_hzd_run_unknown_flag_exits_2_without_running_any_stage(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, {}))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, ["--bogus-flag"])

    assert rc == 2
    assert calls == []
    assert "--bogus-flag" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# fw
# ---------------------------------------------------------------------------

def _fw_outputs(mods):
    return {
        # extract's fake must create the real directory shape (out/fw/audio),
        # not just the shared parent out/fw -- see #6 (regression test below).
        mods["extract"]: "out/fw/audio",
        mods["asr"]: "out/fw/transcripts.csv",
        mods["subtitle-bind"]: "out/fw/subtitle-manifest-full.csv",
        mods["match"]: "out/fw/story-manifest.csv",
        mods["full-reel"]: "out/fw/full-reel-manifest.csv",
        mods["render"]: "out/fw/reels",
    }


def test_fw_render_runs_despite_extract_creating_audio_dir(tmp_path, monkeypatch):
    """Regression for #6: fw render must not be skipped just because fw extract
    unconditionally creates out/fw/audio. The old resume mechanism skipped a
    stage on its output path existing, and render's own sentinel used to BE
    out/fw/audio -- so a chained `fw run` could never reach render. Resume is
    now per-stage done-markers (#15), so this directory existing must not
    matter at all.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    gamescript = tmp_path / "gamescript.md"
    gamescript.write_text("Aloy: Hello.\n", encoding="utf-8")

    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    rc = run_mod.run_game("fw", {"fw_package": "PKG"}, ["--gamescript", str(gamescript)])
    assert rc == 0

    assert os.path.isdir("out/fw/audio")  # extract's real directory shape, present throughout
    called = [m for m, _ in calls]
    assert mods["render"] in called
    assert called == [mods["extract"], mods["asr"], mods["subtitle-bind"],
                       mods["match"], mods["full-reel"], mods["render"]]


def test_fw_run_missing_types_json_aborts_chain_cleanly(tmp_path, monkeypatch, capsys):
    """`fw run` must surface a missing --types-json at the subtitle-bind stage as
    a clean, actionable failure -- not an unhandled FileNotFoundError traceback
    (issue #7). extract/asr are faked (they need a real install); subtitle-bind
    dispatches to its REAL main() so its own check is what's under test here.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    mods = _mods("fw")
    calls = []
    fake_import_stage = _make_fake_import_stage(calls, _fw_outputs(mods))

    def _import_stage(module_name):
        if module_name == mods["subtitle-bind"]:
            return real_import_stage(module_name)  # the real subtitle_bind.main
        return fake_import_stage(module_name)

    monkeypatch.setattr(run_mod, "_import_stage", _import_stage)

    rc = run_mod.run_game("fw", {"fw_package": "PKG"}, [])
    assert rc == 1

    called = [m for m, _ in calls]
    assert called == [mods["extract"], mods["asr"]]  # subtitle-bind ran for real, then chain stopped

    captured = capsys.readouterr()
    assert "--types-json" in captured.out
    assert "docs/BYO.md" in captured.out
    assert "vendor/odradek" not in captured.out
    assert captured.err == ""  # no traceback

    assert not os.path.exists(_marker("fw", "subtitle-bind"))  # failed -> no done-marker
    assert not os.path.exists(_marker("fw", "match"))          # never reached


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


def test_fw_gamescript_path_missing_exits_nonzero_and_names_path(tmp_path, monkeypatch, capsys):
    """An explicitly-given --gamescript path that doesn't exist must be reported and
    fail the run -- not silently treated like no --gamescript at all (#38). Otherwise
    anything scripted on the exit code believes match/full-reel/render actually ran.

    Since #62 the check is UPFRONT (zero stages run), same reasoning as the
    upfront GPU gate (#33): the run is known-doomed before extract's (or the
    GPU asr pass's) hours are spent, so fail before them, not after."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    bad_path = str(tmp_path / "nope.md")
    rc = run_mod.run_game("fw", {"fw_package": "PKG"}, ["--gamescript", bad_path])
    assert rc != 0

    assert [m for m, _ in calls] == []  # known-doomed run: nothing executes

    out = capsys.readouterr().out
    assert bad_path in out


def test_fw_full_chain_with_gamescript(tmp_path, monkeypatch, parsed_stage_args):
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
    assert _after(render_argv, "--stem") == "fw_story_full"
    assert "--uniform-mono" in render_argv
    # --manifest/--tiers are no longer hand-wired here (issue #17): render's
    # own defaults already match the full-reel stage's output and ship set,
    # so this resolves render_argv through render's REAL parser rather than
    # asserting a literal that would just be a second copy of the default.
    from deciwaves.games.fw import render as render_mod
    ns = parsed_stage_args(render_mod.main, render_argv)
    assert ns.manifest == render_mod.DEFAULT_MANIFEST
    assert ns.tiers == render_mod.DEFAULT_TIERS


def test_fw_extract_rerun_invalidates_downstream_across_gamescript_gate(tmp_path, monkeypatch):
    """Issue #37, fw-specific: fw's chain is split into two `_run_chain` calls
    around the BYO --gamescript gate (extract/asr/subtitle-bind, then
    match/full-reel/render). Invalidation must still follow the FULL declared
    chain order across that split -- re-running `extract` must invalidate
    match/full-reel/render's markers too, not just subtitle-bind's (the only
    later stage that happens to share extract's own _run_chain call)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    gamescript = tmp_path / "gamescript.md"
    gamescript.write_text("Aloy: Hello.\n", encoding="utf-8")

    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    cfg = {"fw_package": "PKG"}
    rc = run_mod.run_game("fw", cfg, ["--gamescript", str(gamescript)])
    assert rc == 0
    all_stages = ["extract", "asr", "subtitle-bind", "match", "full-reel", "render"]
    assert [m for m, _ in calls] == [mods[s] for s in all_stages]
    for stage in all_stages:
        assert os.path.isfile(_marker("fw", stage))

    calls.clear()
    os.remove(_marker("fw", "extract"))  # simulate a re-extract after a game patch

    rc = run_mod.run_game("fw", cfg, ["--gamescript", str(gamescript)])
    assert rc == 0

    # extract re-ran, which must invalidate every later stage's marker --
    # including match/full-reel/render, which live in the *second* _run_chain
    # call (past the --gamescript gate) -- so all six re-execute.
    assert [m for m, _ in calls] == [mods[s] for s in all_stages]


def test_fw_run_uses_configured_gamescript_when_no_flag(tmp_path, monkeypatch):
    """No --gamescript flag: fw_gamescript from config is used automatically,
    the same precedence pattern as ds_install/hzd_package/fw_package (#23)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    gamescript = tmp_path / "gamescript.md"
    gamescript.write_text("Aloy: Hello.\n", encoding="utf-8")

    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    cfg = {"fw_package": "PKG", "fw_gamescript": str(gamescript)}
    rc = run_mod.run_game("fw", cfg, [])
    assert rc == 0

    called = [m for m, _ in calls]
    assert called == [mods["extract"], mods["asr"], mods["subtitle-bind"],
                       mods["match"], mods["full-reel"], mods["render"]]
    match_argv = dict(calls)[mods["match"]]
    assert _after(match_argv, "--gamescript") == str(gamescript)


def test_fw_explicit_gamescript_flag_overrides_configured(tmp_path, monkeypatch):
    """An explicit --gamescript beats a saved fw_gamescript config value."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    configured = tmp_path / "configured-gamescript.md"
    configured.write_text("Aloy: Hello.\n", encoding="utf-8")
    explicit = tmp_path / "explicit-gamescript.md"
    explicit.write_text("Aloy: Hi.\n", encoding="utf-8")

    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    cfg = {"fw_package": "PKG", "fw_gamescript": str(configured)}
    rc = run_mod.run_game("fw", cfg, ["--gamescript", str(explicit)])
    assert rc == 0

    match_argv = dict(calls)[mods["match"]]
    assert _after(match_argv, "--gamescript") == str(explicit)


def test_fw_configured_gamescript_missing_exits_nonzero_and_names_path(tmp_path, monkeypatch, capsys):
    """A configured-but-now-missing fw_gamescript must fail loud (nonzero), the
    same as an explicitly-given missing --gamescript path (#38) -- it was
    explicitly configured, just earlier, via `deciwaves setup --fw-gamescript`."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    missing = str(tmp_path / "gone-gamescript.md")
    cfg = {"fw_package": "PKG", "fw_gamescript": missing}
    rc = run_mod.run_game("fw", cfg, [])
    assert rc != 0

    # Since #62 the check is upfront (see the explicit-flag variant above):
    # a run that will cross the gamescript gate fails before any stage runs.
    assert [m for m, _ in calls] == []

    out = capsys.readouterr().out
    assert missing in out


def test_fw_byo_message_shows_exact_rerun_command(tmp_path, monkeypatch, capsys):
    """The BYO message (#23) must show the exact command to re-run with -- the
    real --package path this run used, plus a placeholder for the still-BYO
    gamescript -- not just a generic "pass --gamescript" hint."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    rc = run_mod.run_game("fw", {"fw_package": "PKG"}, [])
    assert rc == 0

    out = capsys.readouterr().out
    assert "deciwaves fw run" in out
    assert "--package PKG" in out
    assert "--gamescript" in out
    assert "deciwaves setup --fw-gamescript" in out


def test_fw_byo_message_quotes_package_path_with_spaces():
    """Finding 10: the suggested re-run command must survive a package path with
    spaces -- an unquoted path breaks the command it tells the user to paste."""
    msg = run_mod._fw_byo_message(r"C:\Games\Forbidden West\package")
    assert '"C:\\Games\\Forbidden West\\package"' in msg


def test_fw_asr_gpu_gate_aborts_without_whisperx(tmp_path, monkeypatch, capsys):
    """Same upfront-scan contract as HZD's bind gate (issue #33): `extract` must
    not run at all if `asr` is going to fail the GPU gate anyway."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    rc = run_mod.run_game("fw", {"fw_package": "PKG"}, [])
    assert rc == 1

    called = [m for m, _ in calls]
    assert called == []  # nothing runs -- the gate fires before extract even starts

    out = capsys.readouterr().out
    assert "pip install deciwaves[asr]" in out


def test_fw_missing_config_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = run_mod.run_game("fw", {}, [])
    assert rc == 1
    assert "deciwaves setup" in capsys.readouterr().out


def test_fw_run_help_exits_0_without_running_any_stage(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, {}))

    with pytest.raises(SystemExit) as exc:
        run_mod.run_game("fw", {"fw_package": "PKG"}, ["--help"])

    assert exc.value.code == 0
    assert calls == []
    assert "deciwaves fw run" in capsys.readouterr().out


def test_fw_run_help_after_other_flags_still_exits_0_without_running_any_stage(tmp_path, monkeypatch, capsys):
    """--help must win no matter where it falls in argv, same as any argparse CLI."""
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, {}))

    with pytest.raises(SystemExit) as exc:
        run_mod.run_game("fw", {"fw_package": "PKG"}, ["--package", "OTHER", "--help"])

    assert exc.value.code == 0
    assert calls == []
    assert "deciwaves fw run" in capsys.readouterr().out


def test_fw_run_unknown_flag_exits_2_without_running_any_stage(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, {}))

    rc = run_mod.run_game("fw", {"fw_package": "PKG"}, ["--bogus-flag"])

    assert rc == 2
    assert calls == []
    assert "--bogus-flag" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# --until / --from chain slicing (issue #62, GUI spec §5.2)
# ---------------------------------------------------------------------------

def _seed_markers(game, stages):
    for stage in stages:
        marker = _marker(game, stage)
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        Path(marker).write_text("", encoding="utf-8")


def test_hzd_until_wem_metadata_completes_without_whisperx(tmp_path, monkeypatch):
    """THE acceptance test for #62: the GUI's Scan button is `hzd run --until
    wem-metadata` on a machine that may lack the [asr] extra. The pre-GPU slice
    must run to completion -- the upfront GPU gate only considers stages inside
    the slice -- writing exactly the markers a full run would have written for
    those stages, and nothing for bind/render."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)  # whisperx absent
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, ["--until", "wem-metadata"])
    assert rc == 0

    assert [m for m, _ in calls] == [mods["catalog"], mods["clip-index"], mods["wem-metadata"]]
    for stage in ("catalog", "clip-index", "wem-metadata"):
        assert os.path.isfile(_marker("hzd", stage))
    for stage in ("bind", "render"):
        assert not os.path.exists(_marker("hzd", stage))


def test_hzd_until_bind_still_gpu_gated_without_whisperx(tmp_path, monkeypatch, capsys):
    """--until must not weaken the gate for a slice that INCLUDES the GPU stage:
    `--until bind` without the [asr] extra aborts upfront, zero stages run."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, ["--until", "bind"])
    assert rc == 1

    assert [m for m, _ in calls] == []
    assert "pip install deciwaves[asr]" in capsys.readouterr().out


def test_ds_until_order_stops_before_render(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mods = _mods("ds")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _ds_outputs(mods)))
    monkeypatch.setattr(run_mod.data, "packaged", lambda rel: Path(f"/pkg/{rel}"))

    rc = run_mod.run_game("ds", {"ds_install": "X"}, ["--until", "order"])
    assert rc == 0

    assert [m for m, _ in calls] == [mods["catalog"], mods["order"]]
    assert os.path.isfile(_marker("ds", "catalog"))
    assert os.path.isfile(_marker("ds", "order"))
    assert not os.path.exists(_marker("ds", "render"))


def test_hzd_until_honors_markers_inside_slice(tmp_path, monkeypatch):
    """Markers keep skipping work inside the slice -- re-clicking Scan on an
    already-scanned workspace only runs what isn't done yet."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    _seed_markers("hzd", ["catalog"])
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, ["--until", "wem-metadata"])
    assert rc == 0

    assert [m for m, _ in calls] == [mods["clip-index"], mods["wem-metadata"]]


def test_hzd_until_invalidation_still_reaches_beyond_slice(tmp_path, monkeypatch):
    """--until bounds what EXECUTES, not what gets invalidated: a re-catalog
    inside the slice makes bind/render stale exactly as a full run would, so
    their markers (outside the slice) must be deleted too -- while the GPU gate
    still stays quiet, because bind isn't going to execute THIS run."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    _seed_markers("hzd", ["catalog", "clip-index", "wem-metadata", "bind", "render"])
    os.remove(_marker("hzd", "catalog"))  # game patch -> force a re-catalog
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, ["--until", "wem-metadata"])
    assert rc == 0

    assert [m for m, _ in calls] == [mods["catalog"], mods["clip-index"], mods["wem-metadata"]]
    for stage in ("bind", "render"):
        assert not os.path.exists(_marker("hzd", stage))


def test_ds_from_order_reruns_order_and_downstream_only(tmp_path, monkeypatch):
    """--from <stage> = delete that stage's marker and run: the stage re-executes
    and cascade invalidation re-runs everything after it; earlier stages still
    skip via their own markers."""
    monkeypatch.chdir(tmp_path)
    mods = _mods("ds")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _ds_outputs(mods)))
    monkeypatch.setattr(run_mod.data, "packaged", lambda rel: Path(f"/pkg/{rel}"))

    cfg = {"ds_install": "X"}
    rc = run_mod.run_game("ds", cfg, [])
    assert rc == 0
    calls.clear()

    rc = run_mod.run_game("ds", cfg, ["--from", "order"])
    assert rc == 0

    assert [m for m, _ in calls] == [mods["order"], mods["render"]]


def test_ds_from_only_deletes_its_marker_run_still_resumes_normally(tmp_path, monkeypatch):
    """--from never blind-skips earlier stages: it only deletes the named stage's
    marker. If an EARLIER stage's marker is also missing (here: catalog), the
    run resumes from there exactly like a plain `run` would -- running from a
    later stage over missing/stale earlier outputs would be wrong."""
    monkeypatch.chdir(tmp_path)
    mods = _mods("ds")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _ds_outputs(mods)))
    monkeypatch.setattr(run_mod.data, "packaged", lambda rel: Path(f"/pkg/{rel}"))

    cfg = {"ds_install": "X"}
    rc = run_mod.run_game("ds", cfg, [])
    assert rc == 0
    calls.clear()
    os.remove(_marker("ds", "catalog"))

    rc = run_mod.run_game("ds", cfg, ["--from", "render"])
    assert rc == 0

    assert [m for m, _ in calls] == [mods["catalog"], mods["order"], mods["render"]]


def test_fw_until_extract_stops_before_gate_without_whisperx_or_byo_noise(tmp_path, monkeypatch, capsys):
    """The GUI's FW Scan is `fw run --until extract` (spec §5.2). On a machine
    without the [asr] extra it must still complete (asr is outside the slice),
    and it must NOT print the BYO gamescript stop message -- the run stopped
    because the user said stop, not because a gamescript is missing."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)  # whisperx absent
    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    rc = run_mod.run_game("fw", {"fw_package": "PKG"}, ["--until", "extract"])
    assert rc == 0

    assert [m for m, _ in calls] == [mods["extract"]]
    assert os.path.isfile(_marker("fw", "extract"))
    assert not os.path.exists(_marker("fw", "asr"))
    assert "gamescript" not in capsys.readouterr().out.lower()


def test_fw_until_subtitle_bind_skips_byo_message(tmp_path, monkeypatch, capsys):
    """--until subtitle-bind ends the run exactly AT the gamescript gate: the BYO
    stop message is about continuing past subtitle-bind, which the user
    explicitly didn't ask for -- printing it would misreport why the run ended."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    rc = run_mod.run_game("fw", {"fw_package": "PKG"}, ["--until", "subtitle-bind"])
    assert rc == 0

    assert [m for m, _ in calls] == [mods["extract"], mods["asr"], mods["subtitle-bind"]]
    assert "gamescript" not in capsys.readouterr().out.lower()


def test_fw_until_match_with_gamescript_stops_before_full_reel(tmp_path, monkeypatch):
    """--until reaching PAST the gamescript gate still gates on the gamescript as
    usual, then stops after the named stage."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    gamescript = tmp_path / "gamescript.md"
    gamescript.write_text("Aloy: Hello.\n", encoding="utf-8")
    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    rc = run_mod.run_game("fw", {"fw_package": "PKG"},
                          ["--gamescript", str(gamescript), "--until", "match"])
    assert rc == 0

    assert [m for m, _ in calls] == [mods["extract"], mods["asr"], mods["subtitle-bind"], mods["match"]]
    assert os.path.isfile(_marker("fw", "match"))
    assert not os.path.exists(_marker("fw", "full-reel"))
    assert not os.path.exists(_marker("fw", "render"))


def test_fw_from_match_reruns_post_gate_slice(tmp_path, monkeypatch):
    """--from a stage on the far side of the gamescript gate: earlier stages all
    skip, the named stage and everything after it re-run."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    gamescript = tmp_path / "gamescript.md"
    gamescript.write_text("Aloy: Hello.\n", encoding="utf-8")
    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    cfg = {"fw_package": "PKG"}
    rc = run_mod.run_game("fw", cfg, ["--gamescript", str(gamescript)])
    assert rc == 0
    calls.clear()

    rc = run_mod.run_game("fw", cfg, ["--gamescript", str(gamescript), "--from", "match"])
    assert rc == 0

    assert [m for m, _ in calls] == [mods["match"], mods["full-reel"], mods["render"]]


def test_hzd_from_after_until_is_usage_error_and_deletes_nothing(tmp_path, monkeypatch, capsys):
    """--from naming a stage AFTER --until can never execute its re-run target --
    reject it as a usage error (exit 2) BEFORE deleting any marker or running
    any stage."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    _seed_markers("hzd", ["render"])
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"},
                          ["--from", "render", "--until", "catalog"])
    assert rc == 2

    assert calls == []
    assert os.path.isfile(_marker("hzd", "render"))  # nothing deleted
    # stderr, not stdout: every other exit-2 usage error from these parsers
    # (unknown flag, invalid choice) goes to stderr via argparse -- this one
    # must land on the same stream so wrappers see one error channel.
    err = capsys.readouterr().err
    assert "--from render" in err
    assert "--until catalog" in err


def test_hzd_until_unknown_stage_is_usage_error(tmp_path, monkeypatch, capsys):
    """Stage names are validated by the parser (choices): a typo'd stage is a
    usage error naming the bad value, not a KeyError mid-run."""
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, {}))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, ["--until", "bogus"])

    assert rc == 2
    assert calls == []
    err = capsys.readouterr().err
    assert "invalid choice" in err
    assert "bogus" in err


def test_hzd_run_help_documents_until_and_from(tmp_path, monkeypatch, capsys):
    """`run --help` must document --until/--from and list the game's real stage
    names as their valid values -- the GUI spec calls these out as the Scan and
    re-run-from-here primitives, and users can't guess stage names."""
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, {}))

    with pytest.raises(SystemExit) as exc:
        run_mod.run_game("hzd", {"hzd_package": "PKG"}, ["--help"])

    assert exc.value.code == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "--until" in out
    assert "--from" in out
    assert "wem-metadata" in out


def test_fw_until_match_without_gamescript_fails_upfront(tmp_path, monkeypatch, capsys):
    """--until naming a post-gamescript-gate stage (match/full-reel/render) with
    no gamescript at all: the run provably cannot execute the requested stage,
    so it must fail (rc 1) UPFRONT -- zero stages run, unlike the plain-run BYO
    soft stop (rc 0), which only applies when the user didn't explicitly ask
    for a post-gate stage. The error must show a re-run command that carries
    the slice flag (a plain re-run would run MORE than the user asked for)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    rc = run_mod.run_game("fw", {"fw_package": "PKG"}, ["--until", "match"])
    assert rc == 1

    assert [m for m, _ in calls] == []
    out = capsys.readouterr().out
    assert "--gamescript" in out
    assert "--until match" in out


def test_fw_from_match_without_gamescript_fails_upfront_and_keeps_marker(tmp_path, monkeypatch, capsys):
    """--from naming a post-gate stage with no gamescript: same upfront failure,
    and crucially the stage's done-marker must NOT have been deleted -- a run
    that can't do what was asked must not destroy the stage's done state on
    its way out."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    _seed_markers("fw", ["extract", "asr", "subtitle-bind", "match", "full-reel", "render"])
    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    rc = run_mod.run_game("fw", {"fw_package": "PKG"}, ["--from", "match"])
    assert rc == 1

    assert [m for m, _ in calls] == []
    assert os.path.isfile(_marker("fw", "match"))  # not deleted
    assert "--gamescript" in capsys.readouterr().out


def test_fw_until_subtitle_bind_ignores_broken_configured_gamescript(tmp_path, monkeypatch):
    """DECISION (review of #62): a slice ending at/before subtitle-bind never
    consumes the gamescript, so a configured-but-now-missing fw_gamescript
    must NOT fail it -- the GUI Scan button (`--until subtitle-bind` at most)
    would otherwise break over a config problem irrelevant to scanning.
    Config health is `doctor`'s job (check_fw_gamescript already reports the
    broken path with a fix hint); any run that actually CROSSES the gate
    still fails upfront on it (tests above)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    mods = _mods("fw")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _fw_outputs(mods)))

    cfg = {"fw_package": "PKG", "fw_gamescript": str(tmp_path / "gone.md")}
    rc = run_mod.run_game("fw", cfg, ["--until", "subtitle-bind"])
    assert rc == 0

    assert [m for m, _ in calls] == [mods["extract"], mods["asr"], mods["subtitle-bind"]]


def test_hzd_from_equals_until_reruns_exactly_one_stage(tmp_path, monkeypatch):
    """--from X --until X is the GUI's "re-run just this stage": valid (not a
    usage error -- guards the > vs >= boundary in the from-after-until check),
    re-executes exactly that stage, and still cascade-invalidates the later
    markers outside the slice (they're stale even though they don't re-run
    now)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    _seed_markers("hzd", ["catalog", "clip-index", "wem-metadata", "bind", "render"])
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"},
                          ["--from", "clip-index", "--until", "clip-index"])
    assert rc == 0

    assert [m for m, _ in calls] == [mods["clip-index"]]
    assert os.path.isfile(_marker("hzd", "catalog"))     # earlier: untouched
    assert os.path.isfile(_marker("hzd", "clip-index"))  # re-ran, re-marked
    for stage in ("wem-metadata", "bind", "render"):
        assert not os.path.exists(_marker("hzd", stage))  # stale -> invalidated


def test_hzd_from_clears_stage_coverage_sections_with_markers(tmp_path, monkeypatch):
    """A deleted done-marker says "not done" -- the stage's persisted coverage
    section (engine/coverage.py, #63) must stop asserting the old completeness
    too (issue #81), for --from's explicit delete AND for the cascade
    invalidation of later stages. Section absent = coverage unknown, exactly
    like markers; sections of stages that aren't invalidated stay."""
    import json

    from deciwaves.engine.coverage import default_coverage_path, write_stage_coverage

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    _seed_markers("hzd", ["catalog", "clip-index", "wem-metadata", "bind", "render"])
    cov = default_coverage_path("hzd")
    write_stage_coverage(cov, "wem-metadata", {"coverage_pct": 100.0})
    write_stage_coverage(cov, "bind", {"bound": 54564})
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, ["--from", "wem-metadata"])
    assert rc == 0

    data = json.loads(Path(cov).read_text(encoding="utf-8"))
    assert "wem-metadata" not in data  # --from's own marker delete cleared it
    assert "bind" not in data          # cascade invalidation cleared it too


def test_hzd_from_bind_without_whisperx_gate_fires_after_marker_delete(tmp_path, monkeypatch, capsys):
    """--from bind without the [asr] extra: the marker is deleted FIRST (that's
    what makes the invalidation-aware upfront gate see bind as about-to-run and
    abort with zero stages executed). The deleted marker is deliberate, not
    damage: it's the exact state the manual delete-marker-and-re-run flow
    leaves behind, and a plain `run` after installing the extra resumes at
    bind."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    _seed_markers("hzd", ["catalog", "clip-index", "wem-metadata", "bind", "render"])
    mods = _mods("hzd")
    calls = []
    monkeypatch.setattr(run_mod, "_import_stage", _make_fake_import_stage(calls, _hzd_outputs(mods)))

    rc = run_mod.run_game("hzd", {"hzd_package": "PKG"}, ["--from", "bind"])
    assert rc == 1

    assert calls == []
    assert not os.path.exists(_marker("hzd", "bind"))
    assert "pip install deciwaves[asr]" in capsys.readouterr().out
