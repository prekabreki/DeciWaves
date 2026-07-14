"""TDD for `deciwaves doctor`: pure check functions (env -> tools_dir -> PATH
resolution, matching engine/audio_clip.py / games/fw/extract.py /
games/hzd/atrac9.py) plus the run_doctor() wiring and exit-code contract.
"""
import json
import os

import pytest

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
    ok, msg = doctor.check_oodle(str(dll))
    assert ok and msg.startswith("[ok]")


def test_check_oodle_missing(tmp_path):
    ok, msg = doctor.check_oodle(str(tmp_path / "nope.dll"))
    assert not ok
    assert msg.startswith("[--]")
    assert "deciwaves setup" in msg


# --- DS / HZD / FW game checks: unconfigured never fails exit code ----------

def test_check_ds_install_not_configured():
    ok, msg = doctor.check_ds_install("")
    assert ok  # does not fail the exit code
    assert "not configured" in msg
    assert msg.startswith("[--]")


def test_check_ds_install_valid(tmp_path):
    (tmp_path / "data").mkdir()
    ok, msg = doctor.check_ds_install(str(tmp_path))
    assert ok and msg.startswith("[ok]")


def test_check_ds_install_configured_but_broken(tmp_path):
    # configured, but the data/ dir isn't there -- this DOES fail (unlike unconfigured)
    ok, msg = doctor.check_ds_install(str(tmp_path))
    assert not ok
    assert msg.startswith("[--]")


def test_check_hzd_package_not_configured():
    ok, msg = doctor.check_hzd_package("")
    assert ok
    assert "not configured" in msg


def test_check_hzd_package_valid(tmp_path):
    ok, msg = doctor.check_hzd_package(str(tmp_path))
    assert ok and msg.startswith("[ok]")


def test_check_hzd_package_configured_but_broken(tmp_path):
    ok, msg = doctor.check_hzd_package(str(tmp_path / "missing"))
    assert not ok


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


# --- ASR extra / CUDA: informational, never fail the exit code -------------

def test_check_asr_extra_never_fails():
    ok, msg = doctor.check_asr_extra()
    assert ok  # pass or fail on this machine, it must never affect exit code
    if "not installed" in msg:
        assert "GPU stages: ds trim, hzd bind, fw asr" in msg


def test_check_cuda_never_fails():
    ok, msg = doctor.check_cuda()
    assert ok


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


def test_run_doctor_config_roundtrips_through_env_override(tmp_path, monkeypatch):
    # Sanity: config.load() picks up DECIWAVES_CONFIG_DIR the same way doctor uses it.
    _write_config(tmp_path, monkeypatch, tools_dir="X")
    assert config.load()["tools_dir"] == "X"
