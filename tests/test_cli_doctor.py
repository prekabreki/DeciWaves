"""TDD for `deciwaves doctor`: pure check functions (env -> tools_dir -> PATH
resolution, matching engine/audio_clip.py / games/fw/extract.py /
games/hzd/atrac9.py) plus the run_doctor() wiring and exit-code contract.
"""


from deciwaves.cli import config
from deciwaves.cli import doctor


# --- check_tool: env var -> tools_dir -> PATH -------------------------------

def test_check_tool_found_via_env(tmp_path, monkeypatch):
    exe = tmp_path / "vgmstream-cli.exe"
    exe.write_bytes(b"x")
    monkeypatch.setenv("DECIWAVES_VGMSTREAM", str(exe))
    ok, msg = doctor.check_tool("vgmstream-cli", "vgmstream-cli", "DECIWAVES_VGMSTREAM", "")
    assert ok
    assert "vgmstream-cli.exe" in msg
    assert msg.startswith("[ok]")


def test_check_tool_env_var_bare_name_resolves_on_path(tmp_path, monkeypatch):
    """Finding 5: a DECIWAVES_* env var set to a bare command name that lives on
    PATH must PASS doctor -- engine/tool_paths.resolve() hands that value straight
    to subprocess.run, where PATH lookup works, so doctor's is_file()-only check
    used to fail a genuinely-working config. Restores the env-on-PATH coverage the
    deleted test_check_tool_found_via_env used to give."""
    (tmp_path / "vgmstream-cli.exe").write_bytes(b"x")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("PATHEXT", ".EXE")
    monkeypatch.setenv("DECIWAVES_VGMSTREAM", "vgmstream-cli")  # bare name, on PATH
    ok, msg = doctor.check_tool("vgmstream-cli", "vgmstream-cli", "DECIWAVES_VGMSTREAM", "")
    assert ok
    assert "vgmstream-cli" in msg
    assert "DECIWAVES_VGMSTREAM" in msg


def test_check_tool_env_var_garbage_bare_name_not_on_path_fails(tmp_path, monkeypatch):
    """The other half of finding 5: an env value that is neither an existing file
    nor resolvable on PATH must still fail (the failure message is unchanged)."""
    monkeypatch.setenv("PATH", str(tmp_path))  # empty dir, nothing to resolve
    monkeypatch.setenv("PATHEXT", ".EXE")
    monkeypatch.setenv("DECIWAVES_VGMSTREAM", "not-a-real-tool-name")
    ok, msg = doctor.check_tool("vgmstream-cli", "vgmstream-cli", "DECIWAVES_VGMSTREAM", "")
    assert not ok
    assert "DECIWAVES_VGMSTREAM" in msg


def test_check_tool_env_var_points_to_missing_file(monkeypatch):
    """An env var that's SET but points nowhere real must not pass doctor's
    check silently -- doctor's whole job is to catch exactly this before a
    decode subprocess fails at spawn time (engine/tool_paths.py resolves the
    env var unconditionally, broken or not)."""
    monkeypatch.setenv("DECIWAVES_VGMSTREAM", r"C:\fake\vgmstream-cli.exe")
    ok, msg = doctor.check_tool("vgmstream-cli", "vgmstream-cli", "DECIWAVES_VGMSTREAM", "")
    assert not ok
    assert "DECIWAVES_VGMSTREAM" in msg
    assert r"C:\fake\vgmstream-cli.exe" in msg


def test_check_tool_found_via_tools_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("DECIWAVES_VGAUDIO", raising=False)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    (tmp_path / "VGAudioCli.exe").write_bytes(b"x")
    ok, msg = doctor.check_tool("VGAudioCli", "VGAudioCli", "DECIWAVES_VGAUDIO", str(tmp_path))
    assert ok
    assert "tools_dir" in msg


def test_check_tool_found_via_path(monkeypatch):
    monkeypatch.delenv("DECIWAVES_VGMSTREAM", raising=False)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: r"C:\PATH\vgmstream-cli.exe" if name == "vgmstream-cli" else None)
    ok, msg = doctor.check_tool("vgmstream-cli", "vgmstream-cli", "DECIWAVES_VGMSTREAM", "")
    assert ok
    assert "PATH" in msg


def test_check_tool_not_found(tmp_path, monkeypatch):
    monkeypatch.delenv("DECIWAVES_VGMSTREAM", raising=False)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    ok, msg = doctor.check_tool("vgmstream-cli", "vgmstream-cli", "DECIWAVES_VGMSTREAM", str(tmp_path))
    assert not ok
    assert msg.startswith("[--]")
    assert "deciwaves setup" in msg  # fix hint


# --- Oodle DLL ---------------------------------------------------------------

def test_check_oodle_found(tmp_path):
    dll = tmp_path / "oo2core_7_win64.dll"
    dll.write_bytes(b"x")
    ok, msg = doctor.check_oodle(str(dll), str(tmp_path))
    assert ok and msg.startswith("[ok]")


def test_check_oodle_missing(tmp_path):
    # DS is configured, but the DLL itself is missing -- this must fail.
    ok, msg = doctor.check_oodle(str(tmp_path / "nope.dll"), str(tmp_path))
    assert not ok
    assert msg.startswith("[--]")
    assert "deciwaves setup" in msg


def test_check_oodle_not_configured():
    # When DS is not configured (keyed off ds_install), Oodle is "not needed"
    # and must not fail the exit code -- regardless of oodle_dll.
    ok, msg = doctor.check_oodle("", "")
    assert ok  # must not fail
    assert "not needed" in msg.lower() or "not configured" in msg.lower()
    assert msg.startswith("[--]")


def test_check_oodle_ds_configured_but_oodle_dll_unset():
    # DS install is configured but oodle_dll itself is empty (e.g. a hand-edited
    # config): this must fail, not report "not needed" -- ds_install is the
    # actual condition the message names.
    ok, msg = doctor.check_oodle("", "/some/ds/install")
    assert not ok
    assert msg.startswith("[--]")


# --- DS / HZD / FW game checks: unconfigured never fails exit code ----------
#
# Issue #32: these three checks return a doctor.CheckResult, not a bare tuple
# -- it carries a structured doctor.Availability (OK / NOT_CONFIGURED /
# BROKEN) alongside the message, so guided.py's game-availability menu can
# read `.status` instead of substring-matching the message text. CheckResult
# still unpacks as a plain (ok, message) 2-tuple, so every `ok, msg = ...`
# call below is unaffected.

def test_check_ds_install_not_configured():
    ok, msg = doctor.check_ds_install("")
    assert ok  # does not fail the exit code
    assert "not configured" in msg
    assert msg.startswith("[--]")


def test_check_ds_install_status_is_structured_tri_state():
    assert doctor.check_ds_install("").status is doctor.Availability.NOT_CONFIGURED


def test_check_ds_install_valid(tmp_path):
    (tmp_path / "data").mkdir()
    ok, msg = doctor.check_ds_install(str(tmp_path))
    assert ok and msg.startswith("[ok]")


def test_check_ds_install_configured_but_broken(tmp_path):
    # configured, but the data/ dir isn't there -- this DOES fail (unlike unconfigured)
    ok, msg = doctor.check_ds_install(str(tmp_path))
    assert not ok
    assert msg.startswith("[--]")
    assert doctor.check_ds_install(str(tmp_path)).status is doctor.Availability.BROKEN


def test_check_ds_install_valid_status_is_ok(tmp_path):
    (tmp_path / "data").mkdir()
    assert doctor.check_ds_install(str(tmp_path)).status is doctor.Availability.OK


# --- CheckResult: positional indexing must agree with iteration (issue #51 item
# 10) -- NamedTuple's inherited tuple.__getitem__ would otherwise hand back the
# raw (status, message) fields instead of (ok, message), so result[0] would
# silently be the Availability enum rather than the bool iteration/unpacking give.

def test_check_result_indexing_matches_iteration_for_ok_case(tmp_path):
    (tmp_path / "data").mkdir()
    result = doctor.check_ds_install(str(tmp_path))
    assert result[0] is result.ok is True
    assert result[1] == result.message
    assert list(result) == [result[0], result[1]]


def test_check_result_indexing_matches_iteration_for_broken_case(tmp_path):
    result = doctor.check_ds_install(str(tmp_path))  # no data/ dir -> BROKEN
    assert result.status is doctor.Availability.BROKEN
    assert result[0] is result.ok is False  # NOT the Availability enum
    assert result[1] == result.message


def test_check_result_indexing_matches_iteration_for_not_configured_case():
    result = doctor.check_ds_install("")  # NOT_CONFIGURED -- ok is still True
    assert result.status is doctor.Availability.NOT_CONFIGURED
    assert result[0] is result.ok is True
    assert result[1] == result.message


def test_check_hzd_package_not_configured():
    ok, msg = doctor.check_hzd_package("")
    assert ok
    assert "not configured" in msg


def test_check_hzd_package_valid(tmp_path):
    # A correct package dir -- the one containing PackFileLocators.bin --
    # must pass (issue #34).
    (tmp_path / "PackFileLocators.bin").write_bytes(b"x")
    ok, msg = doctor.check_hzd_package(str(tmp_path))
    assert ok and msg.startswith("[ok]")


def test_check_hzd_package_configured_but_broken(tmp_path):
    ok, msg = doctor.check_hzd_package(str(tmp_path / "missing"))
    assert not ok


def test_check_hzd_package_install_root_is_not_ok(tmp_path):
    # issue #34: an install-root-shaped dir (exists, but no PackFileLocators.bin
    # -- e.g. the user pointed --hzd-package at the game root instead of
    # <root>\LocalCacheDX12\package) must NOT be reported [ok]. Mirrors
    # check_fw_package's streaming_graph.core requirement.
    (tmp_path / "some_other_file.txt").write_bytes(b"x")  # dir exists, wrong shape
    ok, msg = doctor.check_hzd_package(str(tmp_path))
    assert not ok
    assert msg.startswith("[--]")
    assert "PackFileLocators.bin" in msg
    assert "LocalCacheDX12" in msg  # names the expected subdir in the fix hint
    assert "--hzd-package" in msg


def test_check_fw_package_not_configured():
    ok, msg = doctor.check_fw_package("")
    assert ok
    assert "not configured" in msg


def test_check_fw_package_valid(tmp_path):
    (tmp_path / "streaming_graph.core").write_bytes(b"x")
    ok, msg = doctor.check_fw_package(str(tmp_path))
    assert ok and msg.startswith("[ok]")


def test_check_fw_package_configured_but_broken(tmp_path):
    ok, msg = doctor.check_fw_package(str(tmp_path))  # no streaming_graph.core
    assert not ok


def test_check_fw_gamescript_not_configured():
    # Optional even when FW itself is owned/configured -- must not fail the
    # exit code just because the user hasn't supplied a gamescript yet (#23).
    ok, msg = doctor.check_fw_gamescript("")
    assert ok
    assert "not configured" in msg


def test_check_fw_gamescript_valid(tmp_path):
    gamescript = tmp_path / "gamescript.md"
    gamescript.write_text("Aloy: Hello.\n", encoding="utf-8")
    ok, msg = doctor.check_fw_gamescript(str(gamescript))
    assert ok and msg.startswith("[ok]")


def test_check_fw_gamescript_configured_but_missing(tmp_path):
    # Configured but the file has since moved/been deleted: this DOES fail --
    # it was explicitly configured, just earlier (same "configured but
    # broken" contract as check_ds_install/check_hzd_package/check_fw_package).
    ok, msg = doctor.check_fw_gamescript(str(tmp_path / "gone.md"))
    assert not ok
    assert msg.startswith("[--]")


# --- ASR extra / CUDA: informational, never fail the exit code -------------

def test_check_asr_extra_never_fails():
    ok, msg = doctor.check_asr_extra()
    assert ok  # pass or fail on this machine, it must never affect exit code
    if "not installed" in msg:
        assert "GPU stages: ds trim, hzd bind, fw asr" in msg


def test_check_cuda_never_fails():
    ok, msg = doctor.check_cuda()
    assert ok


def test_check_cuda_survives_broken_torch_import(monkeypatch):
    # A half-installed/locked torch raises non-ImportError (e.g. PermissionError
    # on a DLL); doctor must report a row, never traceback.
    import builtins

    real_import = builtins.__import__

    def broken_import(name, *args, **kwargs):
        if name == "torch":
            raise PermissionError("[WinError 32] shm.dll is locked")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(__import__("sys").modules, "torch", raising=False)
    monkeypatch.setattr(builtins, "__import__", broken_import)
    ok, msg = doctor.check_cuda()
    assert ok
    assert "torch import failed" in msg
    assert "WinError 32" in msg


def test_check_config_file_echo():
    ok, msg = doctor.check_config_file()
    assert ok
    assert str(config.path()) in msg


# --- run_doctor(): full wiring + exit-code contract -------------------------

def _write_config(tmp_path, monkeypatch, **cfg):
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))
    config.save(cfg)


def test_run_doctor_exit_1_on_missing_tools(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    for var in ("DECIWAVES_VGMSTREAM", "DECIWAVES_VGAUDIO"):
        monkeypatch.delenv(var, raising=False)
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    _write_config(tmp_path, monkeypatch, tools_dir=str(empty_dir),
                  ds_install=str(empty_dir), oodle_dll=str(empty_dir / "nope.dll"))
    rc = doctor.run_doctor([])
    out = capsys.readouterr().out.lower()
    assert rc == 1
    for word in ("vgmstream", "ffmpeg", "oodle", "ds install"):
        assert word in out, f"missing {word!r} in doctor output:\n{out}"


def test_run_doctor_exit_0_when_all_found(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: str(tmp_path / name))
    for var in ("DECIWAVES_VGMSTREAM", "DECIWAVES_VGAUDIO"):
        monkeypatch.delenv(var, raising=False)
    ds = tmp_path / "ds"
    (ds / "data").mkdir(parents=True)
    oodle = ds / "oo2core_7_win64.dll"
    oodle.write_bytes(b"x")
    _write_config(tmp_path, monkeypatch, tools_dir=str(tmp_path),
                  ds_install=str(ds), oodle_dll=str(oodle))
    # hzd_package / fw_package intentionally left unconfigured -- must not fail
    rc = doctor.run_doctor([])
    assert rc == 0


def test_run_doctor_exit_1_when_ds_configured_but_oodle_dll_missing(tmp_path, monkeypatch, capsys):
    # DS configured and everything else healthy -- only the Oodle DLL itself is
    # missing. Isolates check_oodle's own fail case from the exit-code wiring
    # (see check_oodle: keyed off ds_install, not oodle_dll being empty).
    monkeypatch.setattr(doctor.shutil, "which", lambda name: str(tmp_path / name))
    for var in ("DECIWAVES_VGMSTREAM", "DECIWAVES_VGAUDIO"):
        monkeypatch.delenv(var, raising=False)
    ds = tmp_path / "ds"
    (ds / "data").mkdir(parents=True)
    _write_config(tmp_path, monkeypatch, tools_dir=str(tmp_path),
                  ds_install=str(ds), oodle_dll=str(ds / "oo2core_7_win64.dll"))
    rc = doctor.run_doctor([])
    out = capsys.readouterr().out.lower()
    assert rc == 1
    assert "oodle" in out


def test_run_doctor_exit_0_with_hzd_fw_only(tmp_path, monkeypatch, capsys):
    # Healthy machine with only HZD/FW configured, no DS: must exit 0 (not 1)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: str(tmp_path / name))
    for var in ("DECIWAVES_VGMSTREAM", "DECIWAVES_VGAUDIO"):
        monkeypatch.delenv(var, raising=False)
    hzd = tmp_path / "hzd"
    hzd.mkdir()
    (hzd / "PackFileLocators.bin").write_bytes(b"x")
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "streaming_graph.core").write_bytes(b"x")
    # DS intentionally not configured: ds_install and oodle_dll both empty
    _write_config(tmp_path, monkeypatch, tools_dir=str(tmp_path),
                  hzd_package=str(hzd), fw_package=str(fw))
    rc = doctor.run_doctor([])
    assert rc == 0, "doctor should exit 0 when only HZD/FW configured (DS not owned)"


def test_run_doctor_exit_1_when_fw_gamescript_configured_but_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: str(tmp_path / name))
    for var in ("DECIWAVES_VGMSTREAM", "DECIWAVES_VGAUDIO"):
        monkeypatch.delenv(var, raising=False)
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "streaming_graph.core").write_bytes(b"x")
    _write_config(tmp_path, monkeypatch, tools_dir=str(tmp_path),
                  fw_package=str(fw), fw_gamescript=str(tmp_path / "gone.md"))
    rc = doctor.run_doctor([])
    out = capsys.readouterr().out.lower()
    assert rc == 1
    assert "gamescript" in out


def test_run_doctor_config_roundtrips_through_env_override(tmp_path, monkeypatch):
    # Sanity: config.load() picks up DECIWAVES_CONFIG_DIR the same way doctor uses it.
    _write_config(tmp_path, monkeypatch, tools_dir="X")
    assert config.load()["tools_dir"] == "X"


# --- doctor --json (issue #65): machine-readable checks for the GUI Doctor
# panel (docs/deciwaves-gui-spec.md §3), so it never has to substring-parse the
# [ok]/[--] text lines -- the exact brittleness CheckResult was introduced to
# kill (#32), now closed for every check.

def _healthy_config(tmp_path, monkeypatch):
    """A config where DS+HZD+FW are all configured and valid, tools on PATH."""
    monkeypatch.setattr(doctor.shutil, "which", lambda name: str(tmp_path / name))
    for var in ("DECIWAVES_VGMSTREAM", "DECIWAVES_VGAUDIO"):
        monkeypatch.delenv(var, raising=False)
    ds = tmp_path / "ds"
    (ds / "data").mkdir(parents=True)
    oodle = ds / "oo2core_7_win64.dll"
    oodle.write_bytes(b"x")
    hzd = tmp_path / "hzd"; hzd.mkdir()
    (hzd / "PackFileLocators.bin").write_bytes(b"x")
    fw = tmp_path / "fw"; fw.mkdir()
    (fw / "streaming_graph.core").write_bytes(b"x")
    _write_config(tmp_path, monkeypatch, tools_dir=str(tmp_path),
                  ds_install=str(ds), oodle_dll=str(oodle),
                  hzd_package=str(hzd), fw_package=str(fw))


def test_doctor_json_emits_structured_object_per_check(tmp_path, monkeypatch, capsys):
    import json
    _healthy_config(tmp_path, monkeypatch)
    rc = doctor.run_doctor(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    checks = {c["name"]: c for c in payload["checks"]}
    # every check carries the five structured fields, no [ok]/[--] prefix in message
    for c in payload["checks"]:
        assert set(c) == {"name", "ok", "status", "message", "fix"}
        assert not c["message"].startswith("[ok]")
        assert not c["message"].startswith("[--]")
    # named checks cover tools, oodle, per-game installs, gamescript, asr, cuda
    for name in ("vgmstream-cli", "ffmpeg", "oodle", "ds_install", "hzd_package",
                 "fw_package", "fw_gamescript", "asr_extra", "cuda", "config_file"):
        assert name in checks, f"missing check {name!r} in {sorted(checks)}"
    assert checks["ds_install"]["status"] == "ok"
    assert checks["ds_install"]["ok"] is True


def test_doctor_json_reports_not_configured_and_broken_status(tmp_path, monkeypatch, capsys):
    import json
    # tools missing -> broken+fail; HZD/FW unconfigured -> not_configured, exit-ok
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    for var in ("DECIWAVES_VGMSTREAM", "DECIWAVES_VGAUDIO"):
        monkeypatch.delenv(var, raising=False)
    empty = tmp_path / "empty"; empty.mkdir()
    _write_config(tmp_path, monkeypatch, tools_dir=str(empty))
    rc = doctor.run_doctor(["--json"])
    payload = json.loads(capsys.readouterr().out)
    checks = {c["name"]: c for c in payload["checks"]}

    assert rc == 1 and payload["ok"] is False
    assert checks["vgmstream-cli"]["status"] == "broken"
    assert checks["vgmstream-cli"]["ok"] is False
    assert checks["vgmstream-cli"]["fix"]                    # a fix hint is present
    assert checks["hzd_package"]["status"] == "not_configured"
    assert checks["hzd_package"]["ok"] is True               # unowned never fails


def test_doctor_json_does_not_print_text_lines(tmp_path, monkeypatch, capsys):
    import json
    _healthy_config(tmp_path, monkeypatch)
    doctor.run_doctor(["--json"])
    out = capsys.readouterr().out
    # pure JSON: parses whole, and none of the text-mode [ok]/[--] lines leak
    json.loads(out)
    assert "[ok]" not in out and "[--]" not in out


def test_doctor_text_output_unchanged_without_json_flag(tmp_path, monkeypatch, capsys):
    # The default (no --json) path stays byte-for-byte the [ok]/[--] report.
    _healthy_config(tmp_path, monkeypatch)
    rc = doctor.run_doctor([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[ok]" in out
    assert out.startswith("[ok]") or out.startswith("[--]")
