"""Torch-free GPU probe + GPU-aware ASR install-command builder (#264). Qt-free.

Tests cover: nvidia-smi present/absent/old-driver → correct wheel tag;
builder editable vs installed form; sys.executable usage; error resilience."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from deciwaves.gui.gpu_probe import (
    CPU_RESULT,
    GpuProbeResult,
    _extract_asr_extras,
    _parse_nvidia_smi_cuda_version,
    _parse_nvidia_smi_gpu_name,
    _select_wheel_tag,
    build_asr_install_steps,
    probe_gpu,
)

# ---------------------------------------------------------------------------
# _parse_nvidia_smi_cuda_version
# ---------------------------------------------------------------------------


def test_parse_cuda_version_extracts_major_minor():
    assert _parse_nvidia_smi_cuda_version(
        "NVIDIA-SMI 551.86 Driver Version: 551.86 CUDA Version: 12.4"
    ) == 12.4


def test_parse_cuda_version_single_digit_minor():
    assert _parse_nvidia_smi_cuda_version(
        "CUDA Version: 11.8"
    ) == 11.8


def test_parse_cuda_version_returns_none_when_missing():
    assert _parse_nvidia_smi_cuda_version("no CUDA here") is None


def test_parse_cuda_version_returns_none_on_empty():
    assert _parse_nvidia_smi_cuda_version("") is None


def test_parse_cuda_version_multiline():
    text = (
        "Tue Jul 22 10:00:00 2026\n"
        "+-----------------------------------------------------------------------------+\n"
        "| NVIDIA-SMI 551.86 Driver Version: 551.86 CUDA Version: 12.4 |\n"
    )
    assert _parse_nvidia_smi_cuda_version(text) == 12.4


def test_parse_cuda_version_new_umd_format():
    # Newer drivers print "CUDA UMD Version:" instead of "CUDA Version:".
    assert _parse_nvidia_smi_cuda_version(
        "| NVIDIA-SMI 610.62  KMD Version: 610.62  CUDA UMD Version: 13.3 |"
    ) == 13.3


# ---------------------------------------------------------------------------
# _parse_nvidia_smi_gpu_name
# ---------------------------------------------------------------------------


def test_parse_gpu_name_first_line():
    assert _parse_nvidia_smi_gpu_name(
        "NVIDIA GeForce RTX 4080\n"
    ) == "NVIDIA GeForce RTX 4080"


def test_parse_gpu_name_empty_returns_none():
    assert _parse_nvidia_smi_gpu_name("") is None


def test_parse_gpu_name_whitespace_only():
    assert _parse_nvidia_smi_gpu_name("   \n  \n") is None


def test_parse_gpu_name_multiple_lines():
    assert _parse_nvidia_smi_gpu_name(
        "NVIDIA GeForce RTX 4090\nNVIDIA GeForce RTX 4080"
    ) == "NVIDIA GeForce RTX 4090"


# ---------------------------------------------------------------------------
# _select_wheel_tag
# ---------------------------------------------------------------------------


def test_select_wheel_tag_default_is_cu128():
    # cu128 is the floor for a torch 2.8 CUDA build (what whisperx pins).
    tag, url = _select_wheel_tag(None)
    assert tag == "cu128"
    assert "cu128" in url


def test_select_wheel_tag_cu128_for_128():
    tag, url = _select_wheel_tag(12.8)
    assert tag == "cu128"
    assert "cu128" in url


def test_select_wheel_tag_cu126_for_126():
    tag, _url = _select_wheel_tag(12.6)
    assert tag == "cu126"


def test_select_wheel_tag_cu124_for_124():
    tag, url = _select_wheel_tag(12.4)
    assert tag == "cu124"


def test_select_wheel_tag_new_driver_uses_cu128():
    tag, _url = _select_wheel_tag(13.3)
    assert tag == "cu128"


def test_select_wheel_tag_downgrades_to_cu121():
    tag, url = _select_wheel_tag(12.1)
    assert tag == "cu121"
    assert "cu121" in url


def test_select_wheel_tag_downgrades_to_cu118():
    tag, url = _select_wheel_tag(11.8)
    assert tag == "cu118"


def test_select_wheel_tag_downgrades_to_cu117():
    tag, url = _select_wheel_tag(11.7)
    assert tag == "cu117"


def test_select_wheel_tag_lowest_is_cu116():
    tag, url = _select_wheel_tag(11.0)
    assert tag == "cu116"


def test_select_wheel_tag_edge_121():
    tag, _url = _select_wheel_tag(12.3)
    assert tag == "cu121"


def test_select_wheel_tag_edge_124():
    tag, _url = _select_wheel_tag(12.39)
    assert tag == "cu121"


# ---------------------------------------------------------------------------
# _extract_asr_extras
# ---------------------------------------------------------------------------


def test_extract_asr_extras_returns_bracketed():
    extras = _extract_asr_extras()
    assert extras == "[asr]"


# ---------------------------------------------------------------------------
# probe_gpu — mocked (no real nvidia-smi)
# ---------------------------------------------------------------------------


def _mock_nvidia_smi(monkeypatch, gpu_name="NVIDIA GeForce RTX 4080",
                     returncode=0, cuda_version="12.4"):
    """Mock subprocess.run to simulate nvidia-smi responses."""

    def _fake_run(args, **kwargs):
        if "--query-gpu=name" in args:
            return type("Result", (), {
                "returncode": returncode,
                "stdout": gpu_name + "\n" if gpu_name else "\n",
                "stderr": "",
            })()
        if args == ["nvidia-smi"]:
            header = f"CUDA Version: {cuda_version}" if cuda_version else ""
            return type("Result", (), {
                "returncode": 0,
                "stdout": header,
                "stderr": "",
            })()
        raise AssertionError(f"unexpected args: {args}")

    monkeypatch.setattr(subprocess, "run", _fake_run)


def test_probe_gpu_modern_driver_returns_cu124(monkeypatch):
    _mock_nvidia_smi(monkeypatch, cuda_version="12.4")
    result = probe_gpu()
    assert result.has_nvidia_gpu is True
    assert result.gpu_name == "NVIDIA GeForce RTX 4080"
    assert result.wheel_tag == "cu124"
    assert "cu124" in result.index_url


def test_probe_gpu_old_driver_downgrades(monkeypatch):
    _mock_nvidia_smi(monkeypatch, cuda_version="11.8")
    result = probe_gpu()
    assert result.has_nvidia_gpu is True
    assert result.wheel_tag == "cu118"


def test_probe_gpu_old_driver_cu121(monkeypatch):
    _mock_nvidia_smi(monkeypatch, cuda_version="12.1")
    result = probe_gpu()
    assert result.wheel_tag == "cu121"


def test_probe_gpu_missing_binary_returns_cpu(monkeypatch):
    def _raise(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi not found")
    monkeypatch.setattr(subprocess, "run", _raise)
    assert probe_gpu() is CPU_RESULT


def test_probe_gpu_nonzero_exit_returns_cpu(monkeypatch):
    _mock_nvidia_smi(monkeypatch, returncode=1)
    result = probe_gpu()
    assert result is CPU_RESULT


def test_probe_gpu_timeout_returns_cpu(monkeypatch):
    def _raise(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=10)
    monkeypatch.setattr(subprocess, "run", _raise)
    assert probe_gpu() is CPU_RESULT


def test_probe_gpu_unparseable_output_defaults_to_cu128(monkeypatch):
    _mock_nvidia_smi(monkeypatch, cuda_version=None)
    result = probe_gpu()
    assert result.has_nvidia_gpu is True
    assert result.wheel_tag == "cu128"


def test_probe_gpu_empty_gpu_name_returns_cpu(monkeypatch):
    _mock_nvidia_smi(monkeypatch, gpu_name="")
    result = probe_gpu()
    assert result is CPU_RESULT


# ---------------------------------------------------------------------------
# build_asr_install_steps
# ---------------------------------------------------------------------------


def _gpu_probe_result(tag="cu124", url="https://download.pytorch.org/whl/cu124"):
    return GpuProbeResult(
        has_nvidia_gpu=True,
        gpu_name="NVIDIA GeForce RTX 4080",
        wheel_tag=tag,
        index_url=url,
    )


def test_steps_gpu_is_single_command_with_extra_index_url(monkeypatch):
    monkeypatch.setattr("deciwaves.gui.gpu_probe._is_editable", lambda: True)
    monkeypatch.setattr(
        "deciwaves.gui.gpu_probe._editable_project_dir",
        lambda: Path(r"C:\repo\DeciWaves"),
    )
    steps = build_asr_install_steps(_gpu_probe_result())
    assert len(steps) == 1
    _label, cmd = steps[0]
    assert "[asr]" in cmd
    # --extra-index-url ADDS the pytorch index (whisperx still from PyPI); it must
    # NOT be the bare --index-url replace form, which 404s whisperx.
    assert "--extra-index-url" in cmd
    assert "--index-url" not in cmd
    assert "cu124" in cmd  # threaded from the probe's index_url
    # Let pip resolve the pinned version — no explicit torch / --force-reinstall.
    assert "--force-reinstall" not in cmd
    assert "install torch" not in cmd  # not force-installing torch by name


def test_steps_editable_uses_absolute_path(monkeypatch):
    monkeypatch.setattr("deciwaves.gui.gpu_probe._is_editable", lambda: True)
    monkeypatch.setattr(
        "deciwaves.gui.gpu_probe._editable_project_dir",
        lambda: Path(r"C:\repo\DeciWaves"),
    )
    _label, cmd = build_asr_install_steps(_gpu_probe_result())[0]
    assert '-e ".[asr]"' not in cmd
    assert r'-e "C:\repo\DeciWaves[asr]"' in cmd


def test_steps_editable_falls_back_to_dot_when_root_unknown(monkeypatch):
    monkeypatch.setattr("deciwaves.gui.gpu_probe._is_editable", lambda: True)
    monkeypatch.setattr(
        "deciwaves.gui.gpu_probe._editable_project_dir", lambda: None)
    steps = build_asr_install_steps(CPU_RESULT)
    assert '-e ".[asr]"' in steps[0][1]


def test_steps_installed_form(monkeypatch):
    monkeypatch.setattr("deciwaves.gui.gpu_probe._is_editable", lambda: False)
    _label, cmd = build_asr_install_steps(_gpu_probe_result())[0]
    assert '"deciwaves[asr]"' in cmd
    assert "-e " not in cmd


def test_steps_cpu_result_has_no_index_url(monkeypatch):
    monkeypatch.setattr("deciwaves.gui.gpu_probe._is_editable", lambda: True)
    monkeypatch.setattr(
        "deciwaves.gui.gpu_probe._editable_project_dir", lambda: None)
    steps = build_asr_install_steps(CPU_RESULT)
    assert len(steps) == 1
    assert "index-url" not in steps[0][1]   # neither --index-url nor --extra-index-url
    assert "[asr]" in steps[0][1]


def test_steps_every_command_uses_call_operator_and_sys_executable(monkeypatch):
    monkeypatch.setattr("deciwaves.gui.gpu_probe._is_editable", lambda: True)
    monkeypatch.setattr(
        "deciwaves.gui.gpu_probe._editable_project_dir", lambda: None)
    for _label, cmd in build_asr_install_steps(_gpu_probe_result()):
        assert cmd.startswith(f'& "{sys.executable}"')
        assert "-m pip install" in cmd


def test_steps_threads_index_url(monkeypatch):
    monkeypatch.setattr("deciwaves.gui.gpu_probe._is_editable", lambda: True)
    monkeypatch.setattr(
        "deciwaves.gui.gpu_probe._editable_project_dir", lambda: None)
    result = _gpu_probe_result(tag="cu128", url="https://download.pytorch.org/whl/cu128")
    _label, cmd = build_asr_install_steps(result)[0]
    assert "cu128" in cmd
