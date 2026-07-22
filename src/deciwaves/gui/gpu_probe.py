"""Torch-free GPU probe + GPU-aware ASR install-command builder (#264).

Detects NVIDIA GPU via ``nvidia-smi`` (no torch import), selects the
appropriate torch CUDA wheel tag, and builds the ``pip install`` command
with ``sys.executable`` and the correct extras form.

Qt-free — no PySide6 import.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from deciwaves.gui import ASR_INSTALL_HINT

_NVIDIA_SMI_TIMEOUT = 10

_CUDA_INDEX_URLS: dict[str, str] = {
    "cu124": "https://download.pytorch.org/whl/cu124",
    "cu121": "https://download.pytorch.org/whl/cu121",
    "cu118": "https://download.pytorch.org/whl/cu118",
    "cu117": "https://download.pytorch.org/whl/cu117",
    "cu116": "https://download.pytorch.org/whl/cu116",
}

_DEFAULT_WHEEL_TAG = "cu124"
_DEFAULT_INDEX_URL = _CUDA_INDEX_URLS[_DEFAULT_WHEEL_TAG]

_CUDA_WHEEL_THRESHOLDS: list[tuple[float, str]] = [
    (12.4, "cu124"),
    (12.1, "cu121"),
    (11.8, "cu118"),
    (11.7, "cu117"),
    (0.0, "cu116"),
]


@dataclass(frozen=True)
class GpuProbeResult:
    has_nvidia_gpu: bool
    gpu_name: str
    wheel_tag: str
    index_url: str


CPU_RESULT = GpuProbeResult(
    has_nvidia_gpu=False, gpu_name="", wheel_tag="", index_url="",
)


def _select_wheel_tag(max_cuda_version: float | None) -> tuple[str, str]:
    if max_cuda_version is None:
        return (_DEFAULT_WHEEL_TAG, _DEFAULT_INDEX_URL)
    for threshold, tag in _CUDA_WHEEL_THRESHOLDS:
        if max_cuda_version >= threshold:
            return (tag, _CUDA_INDEX_URLS[tag])
    return (_DEFAULT_WHEEL_TAG, _DEFAULT_INDEX_URL)


def _parse_nvidia_smi_cuda_version(text: str) -> float | None:
    m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", text)
    if m:
        try:
            return float(f"{m.group(1)}.{m.group(2)}")
        except ValueError:
            return None
    return None


def _parse_nvidia_smi_gpu_name(text: str) -> str | None:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    return lines[0] if lines else None


def probe_gpu() -> GpuProbeResult:
    """Detect NVIDIA GPU via nvidia-smi without importing torch.

    Returns a :class:`GpuProbeResult` with the GPU details and selected
    wheel tag, or a CPU-only result if no NVIDIA GPU is detected.

    Never raises — all errors (missing binary, timeout, parse failure)
    resolve to the CPU result.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=_NVIDIA_SMI_TIMEOUT,
        )
        if result.returncode != 0:
            return CPU_RESULT
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return CPU_RESULT

    gpu_name = _parse_nvidia_smi_gpu_name(result.stdout)
    if not gpu_name:
        return CPU_RESULT

    try:
        version_result = subprocess.run(
            ["nvidia-smi"],
            capture_output=True, text=True, timeout=_NVIDIA_SMI_TIMEOUT,
        )
        max_cuda = _parse_nvidia_smi_cuda_version(version_result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        max_cuda = None

    wheel_tag, index_url = _select_wheel_tag(max_cuda)
    return GpuProbeResult(
        has_nvidia_gpu=True,
        gpu_name=gpu_name,
        wheel_tag=wheel_tag,
        index_url=index_url,
    )


def _extract_asr_extras() -> str:
    start = ASR_INSTALL_HINT.find("[")
    end = ASR_INSTALL_HINT.find("]")
    if start != -1 and end != -1 and end > start:
        return ASR_INSTALL_HINT[start:end + 1]
    return "[asr]"


def _is_editable() -> bool:
    import deciwaves
    return "site-packages" not in Path(deciwaves.__file__).resolve().parts


def build_asr_install_command(probe_result: GpuProbeResult) -> str:
    """Build the GPU-aware ASR ``pip install`` command.

    Uses ``sys.executable`` (targets the running venv, not PATH) and
    selects the extras form based on editable-vs-installed detection.
    GPU-aware ``--index-url`` is appended when the probe found an NVIDIA
    GPU with a CUDA wheel index URL.

    Reuses the ``[asr]`` extras fragment from :data:`ASR_INSTALL_HINT`.
    """
    extras = _extract_asr_extras()
    executable = sys.executable

    if _is_editable():
        cmd = f'"{executable}" -m pip install -e ".{extras}"'
    else:
        cmd = f'"{executable}" -m pip install "deciwaves{extras}"'

    if probe_result.has_nvidia_gpu and probe_result.index_url:
        cmd += f" --index-url {probe_result.index_url}"

    return cmd
