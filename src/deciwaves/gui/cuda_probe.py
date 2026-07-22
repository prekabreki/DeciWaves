"""Qt-free pre-bind CUDA probe (#68, spec §3).

The CLI's GPU gate only checks that ``whisperx`` imports -- CPU-only torch passes it and
then a bind grinds for days. Before an HZD/FW GPU stage the GUI adds this probe, reading
the ``cuda`` check from a `doctor --json` payload (issue #65 already runs
``torch.cuda.is_available()`` there, in a child process). No doctor evidence of a GPU ->
warn, rather than let the user unknowingly start a days-long CPU run."""
from __future__ import annotations

_GPU_GAMES = frozenset({"hzd", "fw"})

GPU_WARNING_TEXT = "No GPU visible — this stage may take days on CPU. Continue?"


def cuda_status(payload: dict | None) -> str:
    """The ``status`` of doctor's ``cuda`` check, or ``""`` if absent."""
    for c in (payload or {}).get("checks", []):
        if c.get("name") == "cuda":
            return c.get("status", "")
    return ""


def cuda_message(payload: dict | None) -> str:
    """The ``message`` of doctor's ``cuda`` check, or ``""`` if absent."""
    for c in (payload or {}).get("checks", []):
        if c.get("name") == "cuda":
            return c.get("message", "")
    return ""


def cuda_display_text(payload: dict | None) -> str:
    """Human-readable GPU status line for the GUI, distinguishing all four
    doctor cuda outcomes plus the no-doctor-yet case."""
    status = cuda_status(payload)
    if status == "ok":
        return "GPU: CUDA ready"
    if status == "":
        return "GPU: unknown — run Doctor to check CUDA"

    message = cuda_message(payload)
    if "not installed" in message:
        return "GPU: acceleration not installed — see ASR extra"
    if "no GPU visible" in message:
        return "GPU: no CUDA GPU visible"
    if "import failed" in message:
        return "GPU: torch import failed"
    return "GPU: no CUDA GPU detected"


def needs_gpu_warning(game: str, payload: dict | None) -> bool:
    """True when starting a GPU stage for HZD/FW without doctor confirming a CUDA GPU."""
    if game not in _GPU_GAMES:
        return False
    return cuda_status(payload) != "ok"
