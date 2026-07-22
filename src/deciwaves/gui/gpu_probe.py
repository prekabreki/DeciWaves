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


def _editable_project_dir() -> Path | None:
    """Locate the editable checkout's project root (the dir with pyproject.toml).

    An editable ``pip install -e .`` command only resolves if the shell's CWD
    is the repo root. The GUI hands the user a copy-pasteable command that they
    run in a fresh console (which opens at their home dir), so a bare ``.`` fails
    with "does not appear to be a Python project". Resolve the absolute project
    root from the imported package location instead, so the command is
    CWD-independent. Returns ``None`` if no ``pyproject.toml`` is found upward.
    """
    import deciwaves
    start = Path(deciwaves.__file__).resolve().parent
    for parent in (start, *start.parents):
        if (parent / "pyproject.toml").is_file():
            return parent
    return None


def _asr_extra_target() -> str:
    """The pip target for the deciwaves ASR extra.

    Editable checkout → ``-e "<abs-project-dir>[asr]"`` (absolute, not a bare
    ``.``, so the copied command works from any console CWD). Installed →
    ``"deciwaves[asr]"``.
    """
    extras = _extract_asr_extras()
    if _is_editable():
        project_dir = _editable_project_dir()
        target = f"{project_dir}{extras}" if project_dir is not None else f".{extras}"
        return f'-e "{target}"'
    return f'"deciwaves{extras}"'


def build_asr_install_steps(probe_result: GpuProbeResult) -> list[tuple[str, str]]:
    """Ordered ``(label, command)`` steps to install the ASR extra.

    With an NVIDIA GPU this is **two** steps: first install the CUDA build of
    PyTorch from the pytorch wheel index, THEN install ``deciwaves[asr]`` from
    PyPI. They must be separate because ``--index-url`` *replaces* PyPI, and the
    pytorch index hosts no ``whisperx`` (a single combined command fails with
    "No matching distribution found for whisperx"). Without a GPU it's a single
    step — a CPU ``torch`` resolves from PyPI as an ordinary dependency of the
    extra.

    Every command uses ``sys.executable`` (targets the running venv, not PATH)
    and is prefixed with PowerShell's call operator (``&``): Windows 11's default
    shell parses a line that *starts* with a quoted string as a string literal,
    not a command, so ``"C:\\...python.exe" -m pip ...`` fails with a
    ParserError. ``&`` tells PowerShell to invoke the quoted path. (This repo is
    Windows/PowerShell-only — see CLAUDE.md.)
    """
    call = f'& "{sys.executable}"'  # PowerShell call operator; see docstring
    extra_cmd = f"{call} -m pip install {_asr_extra_target()}"

    if probe_result.has_nvidia_gpu and probe_result.index_url:
        torch_cmd = (
            f"{call} -m pip install torch torchaudio "
            f"--index-url {probe_result.index_url}"
        )
        return [
            ("1. Install the CUDA build of PyTorch", torch_cmd),
            ("2. Install the ASR extra (deciwaves[asr])", extra_cmd),
        ]
    return [("Install the ASR extra (deciwaves[asr])", extra_cmd)]
