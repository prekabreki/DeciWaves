import io
import json
import urllib.request
import zipfile

import pytest

from deciwaves.cli import setup as s

# Shared stub for a fully-successful download+unpack: writes the exe each
# tool's URL is expected to produce, so `_fetch_tools` reports "fetched"
# instead of a missing-exe failure. Tests that want a failure path build
# their own stub instead of using this one.
_TOOL_EXES = {
    s.VGMSTREAM_URL: "vgmstream-cli.exe",
    s.VGAUDIO_URL: "VGAudioCli.exe",
    s.FFMPEG_URL: "ffmpeg.exe",
}


def _stub_download_ok(url, dest, **_kwargs):
    # **_kwargs swallows manifest_path=... (and any future kwarg) -- this
    # stub replaces the real _download_and_unpack, which is now called with
    # manifest_path as a keyword; ignoring it here (rather than writing a
    # manifest) is deliberate: tests that need a "fully installed" fixture
    # use _mark_fully_installed below instead.
    dest.mkdir(parents=True, exist_ok=True)
    (dest / _TOOL_EXES[url]).write_bytes(b"x")


def _mark_fully_installed(tools_dir, exe):
    """Write *exe* plus a complete sidecar manifest for it, so
    `_tool_fully_installed` (and therefore `_fetch_tools`' skip-if-present
    check) considers it genuinely, fully installed -- not just "a file
    happens to be sitting there" (issue #32 follow-up)."""
    (tools_dir / exe).write_bytes(b"already-here")
    (tools_dir / f"{exe}.files.txt").write_text(f"{exe}\n", encoding="utf-8")


def test_setup_writes_config_and_finds_oodle(tmp_path, monkeypatch):
    ds = tmp_path / "DS"; ds.mkdir(); (ds / "oo2core_7_win64.dll").write_bytes(b"x"); (ds / "data").mkdir()
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)
    rc = s.run_setup(["--ds-install", str(ds), "--tools-dir", str(tmp_path / "tools")])
    assert rc == 0
    cfg = json.loads((tmp_path / "cfg" / "config.json").read_text())
    assert cfg["oodle_dll"].endswith("oo2core_7_win64.dll")
    assert cfg["ds_install"] == str(ds)


def test_setup_warns_but_succeeds_without_any_game(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)
    assert s.run_setup(["--tools-dir", str(tmp_path / "t")]) == 0
    assert "no game install configured" in capsys.readouterr().out.lower()


def test_setup_warns_when_oodle_missing_under_ds_install(tmp_path, monkeypatch, capsys):
    ds = tmp_path / "DS_no_oodle"; ds.mkdir()  # no oo2core_7_win64.dll inside
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)
    rc = s.run_setup(["--ds-install", str(ds), "--tools-dir", str(tmp_path / "tools")])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "oo2core_7_win64.dll" in out
    assert "not found" in out
    cfg = json.loads((tmp_path / "cfg" / "config.json").read_text())
    assert cfg["oodle_dll"] == ""
    assert cfg["ds_install"] == str(ds)


def test_setup_warns_when_hzd_package_missing_locators(tmp_path, monkeypatch, capsys):
    # issue #34: setup used to accept any existing dir for --hzd-package with
    # no validation at all, so a wrong path (e.g. the install root) silently
    # "succeeded" and only broke later, at catalog time, with a traceback.
    hzd = tmp_path / "hzd_wrong_dir"; hzd.mkdir()  # exists, but no PackFileLocators.bin
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)
    rc = s.run_setup(["--hzd-package", str(hzd), "--tools-dir", str(tmp_path / "tools")])
    assert rc == 0  # non-blocking, same as the oodle-missing warning
    out = capsys.readouterr().out
    assert "PackFileLocators.bin" in out
    assert "--hzd-package" in out
    # config is still written with whatever the user passed (consistent with
    # how a broken ds_install/oodle_dll is still persisted, not silently dropped)
    cfg = json.loads((tmp_path / "cfg" / "config.json").read_text())
    assert cfg["hzd_package"] == str(hzd)


def test_setup_suggests_localcachedx12_subdir_when_install_root_given(tmp_path, monkeypatch, capsys):
    # The "nicety" from issue #34: when the user points --hzd-package at the
    # install root and the LocalCacheDX12\package subdir actually exists
    # (with PackFileLocators.bin in it), name that exact subdir in the hint.
    root = tmp_path / "Horizon Zero Dawn Remastered"
    pkg_dir = root / "LocalCacheDX12" / "package"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "PackFileLocators.bin").write_bytes(b"x")
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)
    rc = s.run_setup(["--hzd-package", str(root), "--tools-dir", str(tmp_path / "tools")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "LocalCacheDX12" in out
    assert str(pkg_dir) in out  # names the exact corrected path, not just the pattern
    assert "--hzd-package" in out


def test_setup_no_hzd_warning_when_package_dir_correct(tmp_path, monkeypatch, capsys):
    hzd = tmp_path / "hzd_pkg"; hzd.mkdir()
    (hzd / "PackFileLocators.bin").write_bytes(b"x")
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)
    rc = s.run_setup(["--hzd-package", str(hzd), "--tools-dir", str(tmp_path / "tools")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "WARNING" not in out


def test_setup_saves_hzd_and_fw_package_paths(tmp_path, monkeypatch, capsys):
    hzd = tmp_path / "hzd.package"
    fw = tmp_path / "fw.package"
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)
    rc = s.run_setup([
        "--tools-dir", str(tmp_path / "tools"),
        "--hzd-package", str(hzd),
        "--fw-package", str(fw),
    ])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "no game install configured" not in out
    cfg = json.loads((tmp_path / "cfg" / "config.json").read_text())
    assert cfg["hzd_package"] == str(hzd)
    assert cfg["fw_package"] == str(fw)
    assert cfg["ds_install"] == ""


def test_setup_saves_absolute_path_for_relative_flags(tmp_path, monkeypatch):
    # A relative path (relative to wherever the user ran `deciwaves setup`
    # from) has no fixed meaning once persisted: a later `deciwaves` run can
    # invoke from any directory, or chdir into an unrelated --workspace,
    # before this value is ever read again -- so config-sourced paths must
    # always be saved absolute (issue #32).
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    ds = workdir / "DS"
    ds.mkdir()
    (ds / "oo2core_7_win64.dll").write_bytes(b"x")
    (ds / "data").mkdir()
    (workdir / "gamescript.md").write_text("Aloy: Hi.\n", encoding="utf-8")
    monkeypatch.chdir(workdir)
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)

    rc = s.run_setup([
        "--ds-install", "DS",
        "--fw-gamescript", "gamescript.md",
        "--tools-dir", "tools",
    ])
    assert rc == 0

    cfg = json.loads((tmp_path / "cfg" / "config.json").read_text())
    assert cfg["ds_install"] == str(ds)
    assert cfg["fw_gamescript"] == str(workdir / "gamescript.md")
    assert cfg["tools_dir"] == str(workdir / "tools")
    assert cfg["oodle_dll"] == str(ds / "oo2core_7_win64.dll")


def test_setup_second_run_with_different_game_preserves_first(tmp_path, monkeypatch):
    # Registering game A, then later registering game B without repeating A's
    # flags, must not blank out A's previously-saved entries (issue #36).
    ds = tmp_path / "DS"; ds.mkdir(); (ds / "oo2core_7_win64.dll").write_bytes(b"x")
    hzd = tmp_path / "hzd.package"
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)

    rc1 = s.run_setup(["--ds-install", str(ds), "--tools-dir", str(tmp_path / "tools")])
    assert rc1 == 0

    rc2 = s.run_setup(["--hzd-package", str(hzd), "--tools-dir", str(tmp_path / "tools")])
    assert rc2 == 0

    cfg = json.loads((cfg_dir / "config.json").read_text())
    assert cfg["ds_install"] == str(ds)
    assert cfg["oodle_dll"].endswith("oo2core_7_win64.dll")
    assert cfg["hzd_package"] == str(hzd)


def test_setup_saves_fw_gamescript_path(tmp_path, monkeypatch):
    gamescript = tmp_path / "gamescript.md"
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)
    rc = s.run_setup([
        "--tools-dir", str(tmp_path / "tools"),
        "--fw-gamescript", str(gamescript),
    ])
    assert rc == 0
    cfg = json.loads((tmp_path / "cfg" / "config.json").read_text())
    assert cfg["fw_gamescript"] == str(gamescript)


def test_setup_saves_fw_types_path(tmp_path, monkeypatch):
    # #103: --fw-types persists a BYO Forbidden West types.json path, mirroring
    # --fw-gamescript. A real path is saved (absolutized -- see the round-trip
    # relative-flag test below).
    types_json = tmp_path / "types.json"
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)
    rc = s.run_setup([
        "--tools-dir", str(tmp_path / "tools"),
        "--fw-types", str(types_json),
    ])
    assert rc == 0
    cfg = json.loads((tmp_path / "cfg" / "config.json").read_text())
    assert cfg["fw_types"] == str(types_json)


def test_setup_saves_absolute_path_for_relative_fw_types(tmp_path, monkeypatch):
    # #103: a relative --fw-types is persisted absolute (issue #32 discipline),
    # same as every other config-sourced path.
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "types.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(workdir)
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)

    rc = s.run_setup(["--fw-types", "types.json", "--tools-dir", "tools"])
    assert rc == 0

    cfg = json.loads((tmp_path / "cfg" / "config.json").read_text())
    assert cfg["fw_types"] == str(workdir / "types.json")


def test_setup_second_run_preserves_fw_types_when_omitted(tmp_path, monkeypatch):
    # #103: registering fw_types, then re-running setup for an unrelated flag
    # without repeating --fw-types, must not blank it out -- same merge-over-saved
    # contract (issue #36) as the other config keys.
    types_json = tmp_path / "types.json"
    hzd = tmp_path / "hzd.package"
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)

    assert s.run_setup(["--fw-types", str(types_json), "--tools-dir", str(tmp_path / "tools")]) == 0
    assert s.run_setup(["--hzd-package", str(hzd), "--tools-dir", str(tmp_path / "tools")]) == 0

    cfg = json.loads((cfg_dir / "config.json").read_text())
    assert cfg["fw_types"] == str(types_json)
    assert cfg["hzd_package"] == str(hzd)


def test_setup_explicit_empty_clears_saved_fw_types(tmp_path, monkeypatch):
    # #103: `--fw-types ""` clears a previously saved value (the None-default
    # argparse trick makes "explicit empty" distinguishable from "omitted"),
    # same recovery path as --fw-gamescript "".
    types_json = tmp_path / "types.json"
    types_json.write_text("{}", encoding="utf-8")
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)

    assert s.run_setup(["--fw-types", str(types_json), "--tools-dir", str(tmp_path / "tools")]) == 0
    assert json.loads((cfg_dir / "config.json").read_text())["fw_types"] == str(types_json)

    assert s.run_setup(["--fw-types", "", "--tools-dir", str(tmp_path / "tools")]) == 0
    assert json.loads((cfg_dir / "config.json").read_text())["fw_types"] == ""


def test_setup_second_run_preserves_fw_gamescript_when_omitted(tmp_path, monkeypatch):
    # Registering fw_gamescript, then later re-running setup for an unrelated
    # game/flag without repeating --fw-gamescript, must not blank it out --
    # same merge-over-saved contract issue #36 already guarantees for the
    # other config keys (see test_setup_second_run_with_different_game_preserves_first).
    gamescript = tmp_path / "gamescript.md"
    hzd = tmp_path / "hzd.package"
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)

    rc1 = s.run_setup(["--fw-gamescript", str(gamescript), "--tools-dir", str(tmp_path / "tools")])
    assert rc1 == 0

    rc2 = s.run_setup(["--hzd-package", str(hzd), "--tools-dir", str(tmp_path / "tools")])
    assert rc2 == 0

    cfg = json.loads((cfg_dir / "config.json").read_text())
    assert cfg["fw_gamescript"] == str(gamescript)
    assert cfg["hzd_package"] == str(hzd)


def test_setup_reregistering_fw_gamescript_updates_not_stuck_on_old_path(tmp_path, monkeypatch):
    old = tmp_path / "old-gamescript.md"
    new = tmp_path / "new-gamescript.md"
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)

    assert s.run_setup(["--fw-gamescript", str(old), "--tools-dir", str(tmp_path / "tools")]) == 0
    assert s.run_setup(["--fw-gamescript", str(new), "--tools-dir", str(tmp_path / "tools")]) == 0

    cfg = json.loads((cfg_dir / "config.json").read_text())
    assert cfg["fw_gamescript"] == str(new)


def test_setup_reregistering_same_game_updates_not_stuck_on_old_path(tmp_path, monkeypatch):
    ds_old = tmp_path / "DS_old"; ds_old.mkdir(); (ds_old / "oo2core_7_win64.dll").write_bytes(b"x")
    ds_new = tmp_path / "DS_new"; ds_new.mkdir(); (ds_new / "oo2core_7_win64.dll").write_bytes(b"x")
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)

    assert s.run_setup(["--ds-install", str(ds_old), "--tools-dir", str(tmp_path / "tools")]) == 0
    assert s.run_setup(["--ds-install", str(ds_new), "--tools-dir", str(tmp_path / "tools")]) == 0

    cfg = json.loads((cfg_dir / "config.json").read_text())
    assert cfg["ds_install"] == str(ds_new)
    assert cfg["oodle_dll"] == str(ds_new / "oo2core_7_win64.dll")


def test_setup_explicit_empty_clears_saved_ds_install(tmp_path, monkeypatch):
    # Finding 4: a stale ds_install must be recoverable from the CLI. An explicit
    # empty string clears the saved value (the None-default argparse trick makes
    # "explicit empty" distinguishable from "omitted"); oodle_dll, recomputed from
    # the now-empty ds_install, clears too.
    ds = tmp_path / "DS"; ds.mkdir(); (ds / "oo2core_7_win64.dll").write_bytes(b"x"); (ds / "data").mkdir()
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)

    assert s.run_setup(["--ds-install", str(ds), "--tools-dir", str(tmp_path / "tools")]) == 0
    cfg = json.loads((cfg_dir / "config.json").read_text())
    assert cfg["ds_install"] == str(ds)
    assert cfg["oodle_dll"].endswith("oo2core_7_win64.dll")

    assert s.run_setup(["--ds-install", "", "--tools-dir", str(tmp_path / "tools")]) == 0
    cfg = json.loads((cfg_dir / "config.json").read_text())
    assert cfg["ds_install"] == ""
    assert cfg["oodle_dll"] == ""


def test_setup_explicit_empty_clears_saved_fw_gamescript(tmp_path, monkeypatch):
    # The finding's headline recovery case: a configured-but-now-broken
    # fw_gamescript makes doctor exit 1 forever; `--fw-gamescript ""` clears it.
    gamescript = tmp_path / "gamescript.md"
    gamescript.write_text("Aloy: Hi.\n", encoding="utf-8")
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)

    assert s.run_setup(["--fw-gamescript", str(gamescript), "--tools-dir", str(tmp_path / "tools")]) == 0
    assert json.loads((cfg_dir / "config.json").read_text())["fw_gamescript"] == str(gamescript)

    assert s.run_setup(["--fw-gamescript", "", "--tools-dir", str(tmp_path / "tools")]) == 0
    assert json.loads((cfg_dir / "config.json").read_text())["fw_gamescript"] == ""


def test_setup_omitted_flag_still_keeps_saved_value(tmp_path, monkeypatch):
    # Guard for finding 4's None-default change: omitting a flag must still keep
    # the saved value (only an explicit "" clears). Complements the existing
    # preserve-other-game tests.
    hzd = tmp_path / "hzd.package"
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)

    assert s.run_setup(["--hzd-package", str(hzd), "--tools-dir", str(tmp_path / "tools")]) == 0
    # Re-run with hzd-package omitted entirely -- must NOT be blanked.
    assert s.run_setup(["--tools-dir", str(tmp_path / "tools")]) == 0
    assert json.loads((cfg_dir / "config.json").read_text())["hzd_package"] == str(hzd)


def test_setup_after_corrupted_config_yields_only_current_game(tmp_path, monkeypatch, capsys):
    # Per the load()-hardening fix landed on this branch: a corrupted
    # config.json is ignored (with a warning) and treated as if empty, so a
    # one-game setup after corruption yields a config with just that game --
    # not a crash, and not silently retaining unreadable stale data.
    hzd = tmp_path / "hzd.package"
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)

    rc = s.run_setup(["--hzd-package", str(hzd), "--tools-dir", str(tmp_path / "tools")])
    assert rc == 0
    assert "corrupted" in capsys.readouterr().out.lower()

    cfg = json.loads((cfg_dir / "config.json").read_text())
    assert cfg["hzd_package"] == str(hzd)
    assert cfg["ds_install"] == ""


def test_existing_tools_are_not_redownloaded_without_force(tmp_path, monkeypatch):
    # issue #32: every non-skip run used to re-fetch all ~200 MB regardless of
    # whether the exe was already sitting in tools_dir. A tool that's fully
    # installed (exe + complete manifest) must now be left alone unless
    # --force is passed.
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    for exe in _TOOL_EXES.values():
        _mark_fully_installed(tools_dir, exe)

    def _boom(url, dest, **_kwargs):
        raise AssertionError("must not re-download an already-present tool without --force")

    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _boom)
    rc = s.run_setup(["--tools-dir", str(tools_dir)])
    assert rc == 0  # the _boom guard above is the real check: no re-download happened


def test_force_redownloads_even_when_already_present(tmp_path, monkeypatch):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    for exe in _TOOL_EXES.values():
        _mark_fully_installed(tools_dir, exe)  # genuinely complete -- --force must still refetch

    calls = []

    def _record(url, dest, **kwargs):
        calls.append(url)
        _stub_download_ok(url, dest, **kwargs)

    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _record)
    rc = s.run_setup(["--tools-dir", str(tools_dir), "--force"])
    assert rc == 0
    assert calls == [s.VGMSTREAM_URL, s.VGAUDIO_URL, s.FFMPEG_URL]


def test_missing_tool_is_still_fetched_even_without_force(tmp_path, monkeypatch):
    # Only some tools present (and fully verified) -- the missing ones must
    # still be fetched on a normal (non---force) run; only the genuinely
    # complete one is skipped.
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    _mark_fully_installed(tools_dir, "vgmstream-cli.exe")

    calls = []

    def _record(url, dest, **kwargs):
        calls.append(url)
        _stub_download_ok(url, dest, **kwargs)

    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _record)
    rc = s.run_setup(["--tools-dir", str(tools_dir)])
    assert rc == 0
    assert calls == [s.VGAUDIO_URL, s.FFMPEG_URL]  # vgmstream skipped, the other two fetched


def test_partial_install_missing_sibling_file_is_refetched_without_force(tmp_path, monkeypatch):
    # issue #32 follow-up: an interrupted prior unpack that landed the exe
    # but not a sibling decoder DLL must NOT be silently treated as fully
    # installed -- it must be refetched on the next normal (non---force) run,
    # not require the user to know to pass --force.
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "vgmstream-cli.exe").write_bytes(b"partial-unpack")
    # Manifest claims a sibling DLL that never actually landed on disk --
    # simulates a download that was interrupted mid-unpack.
    (tools_dir / "vgmstream-cli.exe.files.txt").write_text(
        "vgmstream-cli.exe\nlibvgmstream.dll\n", encoding="utf-8"
    )

    calls = []

    def _record(url, dest, **kwargs):
        calls.append(url)
        _stub_download_ok(url, dest, **kwargs)

    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _record)
    rc = s.run_setup(["--tools-dir", str(tools_dir)])
    assert rc == 0
    assert s.VGMSTREAM_URL in calls  # re-fetched despite the exe already being present


def test_legacy_install_without_manifest_is_refetched_once(tmp_path, monkeypatch):
    # A tools_dir populated before this manifest check existed (exe present,
    # no manifest at all) must be treated as "not verified" and refetched --
    # matching the old always-download default, self-healing, and leaving a
    # manifest behind so a LATER run can genuinely skip.
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    for exe in _TOOL_EXES.values():
        (tools_dir / exe).write_bytes(b"pre-manifest-install")  # no .files.txt sidecar

    calls = []

    def _record(url, dest, **kwargs):
        calls.append(url)
        _stub_download_ok(url, dest, **kwargs)

    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _record)
    rc = s.run_setup(["--tools-dir", str(tools_dir)])
    assert rc == 0
    assert calls == [s.VGMSTREAM_URL, s.VGAUDIO_URL, s.FFMPEG_URL]  # all re-fetched once


def test_download_and_unpack_writes_manifest_listing_every_extracted_file(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("vgmstream-win64/vgmstream-cli.exe", b"exe-bytes")
        zf.writestr("vgmstream-win64/libvgmstream.dll", b"dll-bytes")
    zip_bytes = buf.getvalue()
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: io.BytesIO(zip_bytes))

    dest = tmp_path / "tools"
    manifest = dest / "vgmstream-cli.exe.files.txt"
    s._download_and_unpack("https://example.invalid/vgmstream-win64.zip", dest, manifest_path=manifest)

    assert manifest.is_file()
    listed = manifest.read_text(encoding="utf-8").split()
    assert set(listed) == {"vgmstream-cli.exe", "libvgmstream.dll"}


def test_download_and_unpack_writes_no_manifest_when_not_asked(tmp_path, monkeypatch):
    # Backward-compatible default: existing callers that don't pass
    # manifest_path (and the many tests that call _download_and_unpack via
    # the plain 2-arg stub shape) must see no new file appear.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("vgmstream-cli.exe", b"exe-bytes")
    zip_bytes = buf.getvalue()
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: io.BytesIO(zip_bytes))

    dest = tmp_path / "tools"
    s._download_and_unpack("https://example.invalid/vgmstream-win64.zip", dest)

    assert list(dest.glob("*.files.txt")) == []


def test_skip_downloads_never_calls_download(tmp_path, monkeypatch):
    tools_dir = tmp_path / "tools"; tools_dir.mkdir()
    (tools_dir / "vgmstream-cli.exe").write_bytes(b"x")  # only one of the three present

    def _boom(url, dest, **_kwargs):
        raise AssertionError("must not fetch when --skip-downloads is passed")

    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _boom)
    rc = s.run_setup(["--tools-dir", str(tools_dir), "--skip-downloads"])
    assert rc == 0
    cfg = json.loads((tmp_path / "cfg" / "config.json").read_text())
    assert cfg["tools_dir"] == str(tools_dir)


def test_default_tools_dir_uses_localappdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)
    rc = s.run_setup([])
    assert rc == 0
    cfg = json.loads((tmp_path / "cfg" / "config.json").read_text())
    assert cfg["tools_dir"] == str(tmp_path / "AppData" / "Local" / "DeciWaves" / "tools")


def test_download_and_unpack_flattens_nested_zip(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("vgmstream-win64/vgmstream-cli.exe", b"exe-bytes")
        zf.writestr("vgmstream-win64/libvgmstream.dll", b"dll-bytes")
        zf.writestr("vgmstream-win64/docs/README.txt", b"read me")
    zip_bytes = buf.getvalue()

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: io.BytesIO(zip_bytes))

    dest = tmp_path / "tools"
    s._download_and_unpack("https://example.invalid/vgmstream-win64.zip", dest)

    assert (dest / "vgmstream-cli.exe").read_bytes() == b"exe-bytes"
    assert (dest / "libvgmstream.dll").read_bytes() == b"dll-bytes"
    assert (dest / "README.txt").read_bytes() == b"read me"
    # flattened -- no nested folder survives
    assert not (dest / "vgmstream-win64").exists()
    assert not (dest / "docs").exists()


def test_find_oodle_empty_when_no_ds_install():
    assert s._find_oodle("") == ""


def test_download_failure_returns_nonzero_and_reports_failed_row_and_continues(tmp_path, monkeypatch, capsys):
    calls = []

    def _flaky(url, dest, **kwargs):
        calls.append(url)
        if url == s.VGMSTREAM_URL:
            raise TimeoutError("timed out")
        # remaining tools still get attempted and succeed
        _stub_download_ok(url, dest, **kwargs)

    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _flaky)
    rc = s.run_setup(["--tools-dir", str(tmp_path / "tools")])

    assert rc == 1
    # every tool was attempted despite the first one failing
    assert calls == [s.VGMSTREAM_URL, s.VGAUDIO_URL, s.FFMPEG_URL]
    out = capsys.readouterr().out
    assert "FAILED: vgmstream" in out
    assert "timed out" in out
    # no raw traceback leaked into the captured output
    assert "Traceback (most recent call last)" not in out


def test_config_still_written_correctly_when_one_tool_fails(tmp_path, monkeypatch):
    # A partial-failure run (one tool's download blows up) must still persist
    # the rest of the config -- tools_dir, ds_install, oodle_dll -- exactly as
    # a fully-successful run would. The exit code reports the failure; the
    # config write is unconditional.
    ds = tmp_path / "DS"; ds.mkdir(); (ds / "oo2core_7_win64.dll").write_bytes(b"x"); (ds / "data").mkdir()

    def _flaky(url, dest, **kwargs):
        if url == s.VGAUDIO_URL:
            raise TimeoutError("timed out")
        _stub_download_ok(url, dest, **kwargs)

    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _flaky)
    rc = s.run_setup(["--ds-install", str(ds), "--tools-dir", str(tmp_path / "tools")])

    assert rc == 1
    cfg = json.loads((tmp_path / "cfg" / "config.json").read_text())
    assert cfg["tools_dir"] == str(tmp_path / "tools")
    assert cfg["ds_install"] == str(ds)
    assert cfg["oodle_dll"].endswith("oo2core_7_win64.dll")


def test_unpack_succeeds_but_exe_missing_returns_nonzero(tmp_path, monkeypatch, capsys):
    # _download_and_unpack "succeeds" (no exception) but never drops the exe --
    # simulates an upstream zip whose layout changed.
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", lambda url, dest, **kwargs: None)
    rc = s.run_setup(["--tools-dir", str(tmp_path / "tools")])
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "not found after unpack" in out.lower()


def test_all_success_still_returns_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _stub_download_ok)
    rc = s.run_setup(["--tools-dir", str(tmp_path / "tools")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "FAILED" not in out


def test_download_and_unpack_passes_timeout_to_urlopen(tmp_path, monkeypatch):
    captured = {}

    def _fake_urlopen(url, timeout=None):
        captured["timeout"] = timeout
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("vgmstream-cli.exe", b"exe-bytes")
        return io.BytesIO(buf.getvalue())

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    s._download_and_unpack("https://example.invalid/vgmstream-win64.zip", tmp_path / "tools")
    assert captured["timeout"] is not None
    assert captured["timeout"] > 0


@pytest.mark.parametrize("url", [s.VGMSTREAM_URL, s.VGAUDIO_URL, s.FFMPEG_URL])
def test_pinned_urls_are_github_release_downloads(url):
    assert url.startswith("https://github.com/")
    assert "/releases/download/" in url
    assert url.endswith(".zip")
    # The tag segment (.../releases/download/<tag>/<asset>) must be a fixed,
    # dated/versioned release -- never a rolling alias like "latest", whose
    # underlying asset upstream can change out from under a pinned run
    # (issue #39: this caught the ffmpeg URL still pointing at "latest").
    tag = url.split("/releases/download/", 1)[1].split("/", 1)[0]
    assert tag != "latest", f"{url} points at a rolling 'latest' release tag, not a pinned one"
