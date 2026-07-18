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


def needs_gpu_warning(game: str, payload: dict | None) -> bool:
    """True when starting a GPU stage for HZD/FW without doctor confirming a CUDA GPU."""
    if game not in _GPU_GAMES:
        return False
    return cuda_status(payload) != "ok"
