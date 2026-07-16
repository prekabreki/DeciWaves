"""TDD for `deciwaves doctor`: pure check functions (env -> tools_dir -> PATH
resolution, matching engine/audio_clip.py / games/fw/extract.py /
games/hzd/atrac9.py) plus the run_doctor() wiring and exit-code contract.
"""


from deciwaves.cli import config
from deciwaves.cli import doctor


# --- check_tool: env var -> tools_dir -> PATH -------------------------------

def test_check_tool_found_via_env(monkeypatch):
    monkeypatch.setenv("DECIWAVES_VGMSTREAM", r"C:\fake\vgmstream-cli.exe")
    ok, msg = doctor.check_tool("vgmstream-cli", "vgmstream-cli", "DECIWAVES_VGMSTREAM", "")
    assert ok
    assert "vgmstream-cli.exe" in msg
    assert msg.startswith("[ok]")


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
